import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const apiUrl = new URL('../../src/skills/manager.mjs', import.meta.url);
const commit = 'a'.repeat(40);
const content = '---\nname: mobile-helper\ndescription: Use for a repeatable mobile workflow.\n---\n# Mobile helper\nObserve, act, then verify.\n';
const skillPath = 'skills/mobile-helper/SKILL.md';
async function setup(t, overrides = {}) {
  assert.ok(fs.existsSync(apiUrl), 'native skill manager exists');
  const { SkillManager } = await import(apiUrl.href);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-manager-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push(String(url));
    assert.equal(options.redirect, 'error');
    const address = new URL(url);
    if (address.hostname === 'skills.sh') return Response.json(overrides.search ?? { skills: [{ name: 'mobile-helper', source: 'example/workflows', installs: 40 }] });
    if (address.pathname.includes('/commits/')) return Response.json({ sha: commit });
    if (address.pathname.includes('/git/trees/')) return Response.json(overrides.tree ?? { tree: [{ path: skillPath, type: 'blob', mode: '100644' }], truncated: false });
    if (address.hostname === 'raw.githubusercontent.com') return new Response(overrides.content ?? content);
    throw new Error(`Unexpected request: ${url}`);
  };
  return { dir, requests, manager: new SkillManager({ root: path.join(dir, 'installed'), rootsFile: path.join(dir, 'roots.json'), fetchImpl, ...overrides.options }) };
}

test('search returns validated source selectors and never treats popularity as a trust grant', async t => {
  const { manager } = await setup(t, { search: { skills: [
    null,
    { name: 'mobile-helper', source: 'example/workflows', installs: 40 },
    { name: '../bad', source: 'evil/repo' }, { name: 'bad-host', source: 'https://localhost/private' },
  ] } });
  const results = await manager.search('mobile actions');
  assert.equal(results.length, 1);
  assert.equal(results[0].source, 'example/workflows');
  assert.equal(results[0].name, 'mobile-helper');
  assert.equal(manager.list().some(item => item.name === 'commit-review'), true);
  await assert.rejects(manager.search(''), /query/i);
});

test('preview pins a commit and hash; install uses it, persists provenance and registers a loadable root', async t => {
  const { manager, dir, requests } = await setup(t);
  const preview = await manager.preview({ source: 'example/workflows', name: 'mobile-helper' });
  assert.equal(preview.commit, commit);
  assert.equal(preview.path, skillPath);
  assert.equal(preview.content, content);
  assert.match(preview.sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(fs.readdirSync(dir), [], 'preview does not install');
  const installed = await manager.install(preview);
  assert.equal(fs.readFileSync(path.join(installed.directory, 'SKILL.md'), 'utf8'), content);
  const { loadSkills } = await import('../../src/core/skills.mjs');
  const { registeredSkillRoots } = await import('../../src/skills/roots.mjs');
  assert.deepEqual(loadSkills(registeredSkillRoots(path.join(dir, 'roots.json'))[0]).map(item => item.name), ['mobile-helper']);
  assert.equal(JSON.parse(fs.readFileSync(path.join(installed.directory, 'source.json'))).commit, commit);
  assert.ok(requests.at(-1).includes(commit), 'install fetches immutable content');
  await assert.rejects(manager.install(preview), /exists|installed/i);
});

test('mismatched hash and invalid pins never write a skill', async t => {
  const { manager, dir } = await setup(t);
  const preview = await manager.preview({ source: 'example/workflows', name: 'mobile-helper' });
  await assert.rejects(manager.install({ ...preview, sha256: 'b'.repeat(64) }), /hash|changed/i);
  await assert.rejects(manager.install({ ...preview, commit: 'main' }), /commit/i);
  await assert.rejects(manager.install({ ...preview, path: undefined }), /path/i);
  assert.deepEqual(fs.readdirSync(dir), []);
});

test('source and path traversal are rejected before contacting the network', async t => {
  const { manager, requests } = await setup(t);
  for (const source of ['https://localhost/x', 'https://github.com/example/workflows?x=y', '../bad', 'example/repo/extra', 'https://u:p@github.com/example/repo']) {
    await assert.rejects(manager.preview({ source, name: 'mobile-helper' }), /source/i);
  }
  await assert.rejects(manager.preview({ source: 'example/workflows', name: '../escape' }), /name/i);
  await assert.rejects(manager.preview({ source: 'example/workflows', name: 'mobile-helper', path: '../SKILL.md' }), /path/i);
  assert.equal(requests.length, 0);
});

test('support files, links, incomplete trees and incompatible instructions fail with an actionable reason', async t => {
  for (const tree of [
    { tree: [{ path: skillPath, type: 'blob', mode: '120000' }] },
    { tree: [{ path: skillPath, type: 'blob', mode: '100644' }, { path: 'skills/mobile-helper/scripts/run.py', type: 'blob', mode: '100644' }] },
    { tree: [{ path: skillPath, type: 'blob', mode: '100644' }, { path: 'skills/mobile-helper/examples/forms.md', type: 'blob', mode: '100644' }] },
    { tree: [{ path: skillPath, type: 'blob', mode: '100644' }, { path: 'skills/mobile-helper/helper.py', type: 'blob', mode: '100644' }] },
    { tree: [], truncated: true },
  ]) {
    const { manager } = await setup(t, { tree });
    await assert.rejects(manager.preview({ source: 'example/workflows', name: 'mobile-helper' }), /link|support|truncated/i);
  }
  for (const text of [
    content + '\nRead [guide](references/guide.md).',
    content + '\nRead `../../shared/rules.md` first.',
    content + '\n[guide][rules]\n\n[rules]: ../rules.md',
    content + '\nRead <a href="../rules.md">the rules</a>.',
    content.replace('Observe, act, then verify.', 'x'.repeat(12001)),
    content.replace('Observe, act, then verify.', '🙂'.repeat(2100)),
  ]) {
    const { manager } = await setup(t, { content: text });
    await assert.rejects(manager.preview({ source: 'example/workflows', name: 'mobile-helper' }), /support|compatible|body/i);
  }
});

test('bounded downloads, malformed search and HTTP failures surface without an empty-success result', async t => {
  const { manager } = await setup(t, { search: { unexpected: [] } });
  await assert.rejects(manager.search('mobile'), /response/i);
  const { manager: large } = await setup(t, { options: { fetchImpl: async () => new Response('x'.repeat(1024 * 1024 + 1)) } });
  await assert.rejects(large.search('mobile'), /large|limit/i);
  const { manager: unavailable } = await setup(t, { options: { fetchImpl: async () => new Response('Unavailable', { status: 503 }) } });
  await assert.rejects(unavailable.search('mobile'), /503/);
});

test('root links, bundled collisions and broken registration cannot leave a partial install', async t => {
  const { manager, dir } = await setup(t);
  const preview = await manager.preview({ source: 'example/workflows', name: 'mobile-helper' });
  const root = path.join(dir, 'installed');
  fs.mkdirSync(root);
  fs.mkdirSync(path.join(root, preview.name));
  await assert.rejects(manager.install(preview), /exists|installed/i);
  fs.rmdirSync(path.join(root, preview.name));
  fs.writeFileSync(path.join(dir, 'roots.json'), 'broken');
  await assert.rejects(manager.install(preview));
  assert.deepEqual(fs.readdirSync(root), []);
  const { manager: collision } = await setup(t, { content: content.replaceAll('mobile-helper', 'commit-review'), tree: { tree: [{ path: 'skills/commit-review/SKILL.md', type: 'blob', mode: '100644' }] } });
  const bundled = await collision.preview({ source: 'example/workflows', name: 'commit-review' });
  await assert.rejects(collision.install(bundled), /bundled|installed/i);
});

test('real linked install roots and linked destinations cannot redirect writes', async t => {
  const { manager, dir } = await setup(t);
  const preview = await manager.preview({ source: 'example/workflows', name: 'mobile-helper' });
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(outside);
  fs.writeFileSync(path.join(outside, 'keep.txt'), 'preserve');
  const root = path.join(dir, 'installed');
  const kind = process.platform === 'win32' ? 'junction' : 'dir';
  fs.symlinkSync(outside, root, kind);
  await assert.rejects(manager.install(preview), /link/i);
  assert.deepEqual(fs.readdirSync(outside), ['keep.txt']);
  fs.unlinkSync(root);
  fs.mkdirSync(root);
  fs.symlinkSync(outside, path.join(root, 'mobile-helper'), kind);
  await assert.rejects(manager.install(preview), /exist/i);
  assert.deepEqual(fs.readdirSync(outside), ['keep.txt']);
});

test('cancellation rejects installation without leaving profile files', async t => {
  const controller = new AbortController();
  const { manager, dir } = await setup(t, { options: { signal: controller.signal } });
  const preview = await manager.preview({ source: 'example/workflows', name: 'mobile-helper' });
  controller.abort();
  await assert.rejects(manager.install(preview), /abort/i);
  assert.deepEqual(fs.readdirSync(dir), []);
});

test('an omitted README cannot supply required instructions even though ancillary files are otherwise allowed', async t => {
  const { manager } = await setup(t, {
    content: content + '\nBefore proceeding, read README.md and follow its required steps.',
    tree: { tree: [{ path: skillPath, type: 'blob', mode: '100644' }, { path: 'skills/mobile-helper/README.md', type: 'blob', mode: '100644' }] },
  });
  await assert.rejects(manager.preview({ source: 'example/workflows', name: 'mobile-helper' }), /support/i);
});
