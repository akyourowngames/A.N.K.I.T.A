import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const apps = await import('../../tools/apps/open-app.mjs');
const discover = await import('../../tools/apps/discover.mjs');

const BS = String.fromCharCode(92);
const GUID = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}';
const SAMPLE = [
  { name: 'Notepad', target: `${GUID}${BS}notepad.exe`, source: 'start-apps' },
  { name: 'Paint', target: `${GUID}${BS}mspaint.exe`, source: 'start-apps' },
  { name: 'Paint 3D', target: 'Microsoft.MSPaint_8wekyb3d8bbwe!Microsoft.MSPaint', source: 'start-apps' },
  { name: 'Visual Studio Code', target: `C:${BS}Apps${BS}Code.exe`, source: 'start-apps' },
];
// validateTarget now requires an absolute path, so routes use real shapes.
const CREATES = { exists: () => true };

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-apps-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

/** A ctx whose index and launcher are fully controlled by the test. */
function ctxWith(t, entries, { platform = 'win32' } = {}) {
  const dir = tempDir(t);
  discover.writeIndex(dir, entries);
  const launched = [];
  return { ctx: { configDir: dir, platform, spawn: () => { launched.push(true); return { on() {}, unref() {} }; } }, launched, dir };
}

/* ------------------------------- matching -------------------------------- */

test('an exact name wins, even when a similar app also exists', () => {
  assert.equal(apps.matchApps(SAMPLE, 'paint').match.name, 'Paint', '"paint" must not open "Paint 3D"');
  assert.equal(apps.matchApps(SAMPLE, 'notepad').kind, 'exact');
});

test('a unique prefix or partial name still resolves', () => {
  assert.equal(apps.matchApps(SAMPLE, 'note').match.name, 'Notepad');
  assert.equal(apps.matchApps(SAMPLE, 'code').match.name, 'Visual Studio Code');
  assert.equal(apps.matchApps(SAMPLE, 'studio code').match.name, 'Visual Studio Code');
});

test('an unknown name is reported, never guessed', () => {
  const result = apps.matchApps(SAMPLE, 'photoshop');
  assert.equal(result.kind, 'none');
  assert.deepEqual(result.matches, []);
});

test('two plausible matches are returned as candidates instead of a guess', () => {
  // "studio" is a unique prefix of one app, so prefix matching narrowly wins;
  // a query that prefixes two apps must still come back ambiguous.
  const two = [...SAMPLE,
    { name: 'Visual Studio', target: 'Microsoft.VisualStudio_abc!App', source: 'start-apps' }];
  // "visual" prefixes both; an exact name would still win, which is the point of
  // trying exact first.
  const result = apps.matchApps(two, 'visual');
  assert.equal(result.kind, 'ambiguous');
  assert.ok(result.matches.every(item => item.name.startsWith('Visual')));
  assert.equal(apps.matchApps(two, 'visual studio').kind, 'exact', 'an exact name is never ambiguous');
});

/* -------------------------------- targets -------------------------------- */

test('shell AppIDs are recognised and real paths are checked', () => {
  assert.equal(apps.isShellTarget(`${GUID}${BS}notepad.exe`), true, 'GUID namespace form');
  assert.equal(apps.isShellTarget('Microsoft.MSPaint_8wekyb3d8bbwe!Microsoft.MSPaint'), true, 'package form');
  assert.equal(apps.isShellTarget(`C:${BS}Apps${BS}Code.exe`), false, 'a real path is not a shell target');
  assert.equal(apps.validateTarget(SAMPLE[3], { exists: () => false }), 'That application is no longer installed (Code.exe is missing).');
  assert.equal(apps.validateTarget(SAMPLE[3], { exists: () => true }), null);
  assert.equal(apps.validateTarget(SAMPLE[0], { exists: () => false }), null, 'a shell target needs no file check');
});

/* -------------------------------- launching ------------------------------- */

test('opening a known app launches once and reports success', async t => {
  const { ctx, launched } = ctxWith(t, SAMPLE);
  const result = JSON.parse(await apps.run({ name: 'notepad' }, ctx));
  assert.equal(result.opened, true);
  assert.equal(result.app, 'Notepad');
  assert.equal(launched.length, 1);
});

test('an ambiguous request opens nothing and asks which one', async t => {
  const { ctx, launched } = ctxWith(t, [...SAMPLE, { name: 'Visual Studio', target: 'Microsoft.VisualStudio_abc!App', source: 'start-apps' }]);
  const result = JSON.parse(await apps.run({ name: 'visual' }, ctx));
  assert.equal(result.opened, false);
  assert.equal(result.ambiguous, true);
  assert.equal(launched.length, 0, 'nothing is started until the name is exact');
});

test('a missing app opens nothing and offers the browse action', async t => {
  const { ctx, launched } = ctxWith(t, SAMPLE);
  const result = JSON.parse(await apps.run({ name: 'zzzz' }, ctx));
  assert.equal(result.found, false);
  assert.match(result.notice, /action=list/);
  assert.equal(launched.length, 0);
});

test('list shows matches without launching anything', async t => {
  const { ctx, launched } = ctxWith(t, SAMPLE);
  const result = JSON.parse(await apps.run({ action: 'list', name: 'paint' }, ctx));
  assert.equal(result.action, 'list');
  assert.ok(result.apps.some(item => item.name === 'Paint'));
  assert.equal(launched.length, 0);
});

test('a launch is never registered as a background job, so it cannot hold voice', async t => {
  const { ctx } = ctxWith(t, SAMPLE);
  const jobs = new Map();
  await apps.run({ name: 'notepad' }, { ...ctx, state: { jobs } });
  assert.equal(jobs.size, 0, 'open_app asynchronously detaches: nothing to wait for');
});

/* --------------------------------- safety -------------------------------- */

test('an app that is not in the index needs approval; a known one does not', async t => {
  const dir = tempDir(t);
  discover.writeIndex(dir, SAMPLE);
  assert.equal(apps.needsApproval({ name: 'notepad' }, { configDir: dir }), false);
  assert.equal(apps.needsApproval({ action: 'list', name: 'notepad' }, { configDir: dir }), false);
  assert.equal(apps.needsApproval({ name: 'some brand new app' }, { configDir: dir }), true);
});

test('the model cannot launch an executable path it invents', async t => {
  // Matching is over discovered names only; a path never matches a name.
  const result = apps.matchApps(SAMPLE, `C:${BS}Windows${BS}System32${BS}cmd.exe`);
  assert.equal(result.kind, 'none', 'a path is not a name, so nothing is launched');
});

/* -------------------------------- discovery ------------------------------ */

test('the Windows Start-apps table parses to name and AppID', () => {
  const parsed = discover.parseStartApps(`Name   AppID
Notepad   Microsoft.WindowsNotepad_8wekyb3d8bbwe!App
7-Zip File Manager   7-Zip.FileManager_abc!App`);
  assert.equal(parsed.length, 2);
  assert.deepEqual(parsed[0], { name: 'Notepad', target: 'Microsoft.WindowsNotepad_8wekyb3d8bbwe!App', args: [], source: 'start-apps' });
});

test('a freedesktop entry yields a name and a command without field codes', () => {
  const entry = discover.parseDesktopEntry('[Desktop Entry]\nType=Application\nName=Firefox Web Browser\nExec=firefox %u\n');
  assert.deepEqual(entry, { name: 'Firefox Web Browser', target: 'firefox', args: [], source: 'desktop-entry' });
  assert.equal(discover.parseDesktopEntry('Name=Hidden\nExec=hidden\nNoDisplay=true'), null, 'hidden entries are skipped');
});

test('one app listed several ways collapses to one row, preferring the canonical handle', () => {
  const merged = discover.finalize([
    { name: 'Notepad', target: `${GUID}${BS}notepad.exe`, source: 'start-apps' },
    { name: 'Notepad', target: `C:${BS}Start${BS}Notepad.lnk`, source: 'shortcut' },
    { name: '== Web Site ==', target: 'https://example.com', source: 'shortcut' },
  ]);
  assert.equal(merged.length, 1, 'duplicates and separator junk are dropped');
  assert.equal(merged[0].source, 'start-apps');
});

test('a stale index is rescanned and a failed rescan keeps the old list', (t) => {
  const dir = tempDir(t);
  const stale = new Date(Date.now() - 30 * 86400000).toISOString();
  fs.writeFileSync(path.join(dir, discover.APP_INDEX_FILE), JSON.stringify({ version: discover.APP_INDEX_VERSION, scannedAt: stale, apps: SAMPLE }));
  const refreshed = discover.loadApps(dir, { refresh: true, scan: () => [{ name: 'Fresh', target: 'Microsoft.Fresh_abc!App', args: [], source: 'start-apps' }] });
  assert.equal(refreshed.refreshed, true);
  assert.equal(refreshed.apps[0].name, 'Fresh');

  const rescanned = discover.loadApps(dir, { refresh: true, scan: () => { throw new Error('scan unavailable'); } });
  assert.equal(rescanned.apps.length, 1, 'a failed scan falls back to the cached index rather than losing apps');
});

/* ------------------------- security regressions -------------------------- */

test('a cached entry carrying shell metacharacters is refused, never launched', async t => {
  const { ctx, launched } = ctxWith(t, [
    { name: 'Injected', target: 'nul&whoami', source: 'start-apps' },
    { name: 'PercentVar', target: 'C:\Apps\%COMSPEC%.exe', source: 'start-apps' },
    { name: 'Quoted', target: 'C:\Apps\\" & calc & ".exe', source: 'start-apps' },
  ]);
  for (const name of ['Injected', 'PercentVar', 'Quoted']) {
    const result = JSON.parse(await apps.run({ name }, ctx));
    assert.equal(result.opened, false, `${name} must not launch`);
  }
  assert.equal(launched.length, 0, 'nothing reached the spawner');
});

test('a poisoned index cannot smuggle a non-absolute or malformed target', (t) => {
  const dir = tempDir(t);
  fs.writeFileSync(path.join(dir, discover.APP_INDEX_FILE), JSON.stringify({
    version: discover.APP_INDEX_VERSION, scannedAt: new Date().toISOString(),
    apps: [
      { name: 'Good', target: 'Microsoft.Good_abc!App', source: 'start-apps' },
      { name: 'Relative', target: 'evil.exe', source: 'start-apps' },
      { name: 'Backslash', target: `nul${BS}..${BS}evil.exe`, source: 'start-apps' },
    ],
  }));
  const read = discover.readIndex(dir);
  assert.deepEqual(read.apps.map(item => item.name), ['Good'], 'only the well-formed entry survives');
});

test('only a real AppID goes through cmd; a file path is spawned directly', async t => {
  const { ctx, spawned } = (() => {
    const dir = tempDir(t);
    discover.writeIndex(dir, SAMPLE);
    const calls = [];
    return { ctx: { configDir: dir, platform: 'win32', exists: () => true, spawn: (exe, args) => { calls.push([exe, args]); return { on() {}, unref() {} }; } }, spawned: calls };
  })();
  await apps.run({ name: 'notepad' }, ctx);
  await apps.run({ name: 'Visual Studio Code' }, { ...ctx, configDir: ctx.configDir });
  const [[firstExe, firstArgs], [secondExe]] = spawned;
  assert.equal(firstExe, 'cmd.exe', 'an AppID needs the shell namespace');
  assert.equal(firstArgs[0], '/c', 'cmd flag');
  assert.equal(firstArgs[1], 'start', 'the shell start verb');
  assert.ok(firstArgs[3].startsWith('shell:AppsFolder'), 'the AppID is passed as a shell namespace');
  assert.equal(secondExe, `C:${BS}Apps${BS}Code.exe`, 'a real path is executed directly, with no cmd re-parse');
});
