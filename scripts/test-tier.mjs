#!/usr/bin/env node
/**
 * Tiered test runner.
 *
 * The full suite is slow for one structural reason: every Playwright file boots
 * Vite and a browser, and they cannot share a process safely (they race on
 * Vite's cache and HMR socket). Running all 234 files serially means ~8 minutes
 * of unit tests plus ~12 minutes of UI tests.
 *
 * So there are three tiers:
 *
 *   changed  - only the files your diff touches, plus their suites. Seconds.
 *   unit     - every non-browser test, in parallel. About a quarter of the time.
 *   full     - everything, browser tests serial and units parallel.
 *
 * `npm test` stays the full run so nothing is quietly skipped.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawn, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// fileURLToPath decodes %20 etc; a raw .pathname yields a broken path on Windows.
const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const TEST_ROOT = path.join(ROOT, 'test');
const BROWSER_MARKER = /from ['"]playwright['"]|require\(['"]playwright['"]\)/;
// Files that spawn real subprocesses and wait on their timing. Run alone: under
// parallel load their fixed deadlines expire and they hang or fail spuriously.
const HEAVY_FILES = new Set([
  'test/core/voice-cli.test.mjs',
]);

const log = (...parts) => console.log(...parts);

/** Every test file, split by whether it drives a real browser. */
export function classifyTests(dir = TEST_ROOT) {
  const files = [];
  const walk = current => {
    for (const item of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, item.name);
      if (item.isDirectory()) { walk(full); continue; }
      if (!item.name.endsWith('.test.mjs')) continue;
      const source = fs.readFileSync(full, 'utf8');
      files.push({ file: path.relative(ROOT, full).split(path.sep).join('/'), browser: BROWSER_MARKER.test(source) });
    }
  };
  walk(dir);
  const all = files.map(entry => entry.file);
  const browser = files.filter(entry => entry.browser).map(entry => entry.file);
  // Heavy files are pulled out of the parallel unit run and executed on their own.
  const heavy = all.filter(file => HEAVY_FILES.has(file));
  const unit = files.filter(entry => !entry.browser && !HEAVY_FILES.has(entry.file)).map(entry => entry.file);
  return { all, browser, heavy, unit };
}

const TIERS = {
  // Browser files one at a time: two Vite servers in one process race on the
  // cache and HMR socket, which surfaces as "WebSocket closed without opened"
  // and fails healthy tests. Heavy subprocess files run alone for the same
  // reason: their fixed deadlines expire under load.
  full: ({ browser, heavy, unit }) => [
    { label: 'unit (parallel)', files: unit, parallel: true },
    { label: 'heavy (serial)', files: heavy, parallel: false },
    { label: 'browser (serial)', files: browser, parallel: false },
  ],
  unit: ({ heavy, unit }) => [
    { label: 'unit (parallel)', files: unit, parallel: true },
    { label: 'heavy (serial)', files: heavy, parallel: false },
  ],
  browser: ({ browser }) => [{ label: 'browser (serial)', files: browser, parallel: false }],
};

function git(args) {
  try { return execFileSync('git', args, { cwd: ROOT, encoding: 'utf8' }).trim(); } catch { return ''; }
}

/** Files changed against the base branch, including staged and unstaged work. */
export function changedTests(base = 'origin/ankita') {
  const committed = git(['diff', '--name-only', `${base}...HEAD`]);
  const working = git(['diff', '--name-only', 'HEAD']);
  const untracked = git(['ls-files', '--others', '--exclude-standard']);
  const touched = [...new Set([...committed.split('\n'), ...working.split('\n'), ...untracked.split('\n')].filter(Boolean))];
  const { all } = classifyTests();
  const byName = new Map(all.map(file => [path.basename(file, '.test.mjs'), file]));

  const direct = new Set(); // A test file itself changed.
  const named = new Set();  // A source changed and a test shares its name.
  const importing = new Set(); // A source changed and a test imports it.
  for (const rel of touched) {
    if (rel.startsWith('test/') && rel.endsWith('.test.mjs')) { direct.add(rel); continue; }
    if (!rel.startsWith('src/') && !rel.startsWith('tools/') && !rel.startsWith('desktop/')) continue;
    const baseName = path.basename(rel, path.extname(rel));
    // "voice.mjs" -> voice-*, *-voice-* tests; skip 2-letter names that match everything.
    if (baseName.length >= 4) for (const [name, file] of byName) if (name.includes(baseName)) named.add(file);
    for (const file of all) {
      if (direct.has(file) || named.has(file)) continue;
      try { if (fs.readFileSync(path.join(ROOT, file), 'utf8').includes(rel)) importing.add(file); } catch {}
    }
  }
  // High confidence first: a test that changed, or shares the changed name.
  return { files: [...new Set([...direct, ...named, ...importing])], direct: [...direct], named: [...named], importing: [...importing] };
}

function runTier({ files, parallel }) {
  return new Promise(resolve => {
    if (!files.length) return resolve({ code: 0, skipped: true });
    const args = ['--test'];
    if (!parallel) args.push('--test-concurrency=1');
    args.push(...files);
    const child = spawn(process.execPath, args, { cwd: ROOT, stdio: 'inherit' });
    child.on('exit', code => resolve({ code: code ?? 1 }));
  });
}

const tier = process.argv[2] || 'full';

// Only act when run directly: importing this module (tests, tooling) must not
// start a whole test tier as a side effect.
const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) await main(tier);

async function main(tier) {
  if (tier === 'changed') {
    const result = changedTests(process.argv[3]);
    const files = result.files;
    if (!files.length) {
      log('No changed files map to a test. Run `npm run test:unit` or `npm test`.');
      process.exit(0);
    }
    // By default run the high-confidence set (tests that changed or share a name).
    // `--all-related` widens it to every test importing a changed file.
    const wide = process.argv.includes('--all-related');
    const selected = wide ? files : [...new Set([...result.direct, ...result.named])];
    const chosen = selected.length ? selected : files;
    log(`Running ${chosen.length} test file(s) touched by this change${wide ? ' (wide)' : ''}. ${wide ? '' : `${files.length - chosen.length} importers skipped; pass --all-related to include them.`}`);
    const browserOnes = chosen.filter(file => BROWSER_MARKER.test(fs.readFileSync(path.join(ROOT, file), 'utf8')));
    const unitOnes = chosen.filter(file => !browserOnes.includes(file) && !HEAVY_FILES.has(file));
    const heavyOnes = chosen.filter(file => HEAVY_FILES.has(file));
    let code = 0;
    if (unitOnes.length) code = (await runTier({ files: unitOnes, parallel: true })).code || code;
    if (heavyOnes.length) code = (await runTier({ files: heavyOnes, parallel: false })).code || code;
    if (browserOnes.length) code = (await runTier({ files: browserOnes, parallel: false })).code || code;
    process.exit(code);
  }

  const groups = classifyTests();
  const plan = TIERS[tier];
  if (!plan) {
    log(`Unknown tier "${tier}". Use: changed | unit | browser | full`);
    process.exit(2);
  }
  log(`Tier "${tier}": ${groups.all.length} test files (${groups.unit.length} unit, ${groups.browser.length} browser)`);
  let failed = 0;
  for (const group of plan(groups)) {
    if (!group.files.length) continue;
    log(`\n${group.label}: ${group.files.length} file(s)`);
    const started = Date.now();
    const { code } = await runTier(group);
    log(`${group.label} finished in ${Math.round((Date.now() - started) / 1000)}s${code ? ' (FAILED)' : ''}`);
    if (code) failed = code;
  }
  process.exit(failed);
}
