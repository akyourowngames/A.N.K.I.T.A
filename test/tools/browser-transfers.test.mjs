import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-transfers-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { BrowserDownloads, BROWSER_DOWNLOAD_DIRECTORY } = await import('../../tools/browser/transfers.mjs');
const browser = await import('../../tools/browser/browser.mjs');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

async function fixture(t) {
  const directory = fs.mkdtempSync(path.join(root, 'workspace-'));
  const server = http.createServer((req, res) => {
    if (req.url === '/download' || req.url === '/slow') {
      res.setHeader('content-type', 'application/octet-stream');
      res.setHeader('content-disposition', 'attachment; filename="../bad:name.txt"');
      if (req.url === '/slow') { res.write('partial'.repeat(128)); return; }
      res.end('verified download'); return;
    }
    res.setHeader('content-type', 'text/html');
    res.end('<label>Document<input type="file" onchange="document.querySelector(\'main\').textContent=this.files[0]?.name||\'empty\'"></label><a href="/download">Download</a><a href="/slow">Slow</a><main></main>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true }, cwd: directory, workspacePath: directory };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, ctx);
  const ref = label => adapter.observation.controls.find(control => control.name === label).ref;
  const file = path.join(directory, 'selected.txt'); fs.writeFileSync(file, 'authorized fixture');
  return { adapter, ctx, ref, file, directory };
}

test('live upload uses an explicitly selected file and refuses model-invented paths', async t => {
  const { adapter, ctx, ref, file } = await fixture(t);
  const args = { action: 'upload', ref: ref('Document') };
  const unauthorized = await adapter.execute({ ...args, file }, ctx);
  assert.equal(unauthorized.status, 'failed');
  assert.match(unauthorized.error.message, /selected|authorized/);
  assert.equal(await adapter.page.locator('input').evaluate(node => node.files.length), 0);
  const result = await adapter.execute(args, { ...ctx, selectBrowserUpload: async () => file });
  assert.equal(result.status, 'executed');
  assert.match(result.output, /selected\.txt/);
  assert.equal(await adapter.page.locator('input').evaluate(node => node.files[0].size), fs.statSync(file).size);
  console.log('UPLOAD_SELECTED_LIVE', JSON.stringify({ unauthorizedWrites: 0, selectedFiles: 1, bytes: fs.statSync(file).size }));
});

test('upload cancellation, tab changes and workspace symlinks refuse before dispatch', async t => {
  const { adapter, ctx, ref, file, directory } = await fixture(t);
  let writes = 0;
  const args = { action: 'upload', ref: ref('Document') };
  const cancelled = await adapter.execute(args, { ...ctx, selectBrowserUpload: async () => null, onBrowserDispatch: () => writes++ });
  assert.equal(cancelled.status, 'failed'); assert.match(cancelled.error.message, /cancel/i);
  const controller = new AbortController();
  const aborted = await adapter.execute(args, { ...ctx, signal: controller.signal, selectBrowserUpload: async () => { controller.abort(); return file; }, onBrowserDispatch: () => writes++ });
  assert.equal(aborted.status, 'failed');
  const changed = await adapter.execute(args, { ...ctx, selectBrowserUpload: async () => { await adapter.context.newPage(); await adapter.selectTab('2'); return file; }, onBrowserDispatch: () => writes++ });
  assert.equal(changed.status, 'failed'); assert.match(changed.error.message, /changed|snapshot/i);
  await adapter.selectTab('1'); await adapter.run({ action: 'snapshot' }, ctx);
  const link = path.join(directory, 'link');
  fs.symlinkSync(root, link, 'junction');
  const outside = await adapter.execute({ action: 'upload', ref: ref('Document'), file: path.join(link, 'anything.txt') }, { ...ctx, browserUploadFiles: [path.join(link, 'anything.txt')], onBrowserDispatch: () => writes++ });
  assert.equal(outside.status, 'failed'); assert.match(outside.error.message, /symlink|junction/);
  assert.equal(writes, 0);
});

test('live download completion is read back as a safe workspace artifact', async t => {
  const { adapter, ctx, ref, directory } = await fixture(t);
  assert.equal((await adapter.execute({ action: 'act', op: 'click', ref: ref('Download') }, ctx)).status, 'executed');
  const listed = await adapter.execute({ action: 'downloads' }, ctx);
  const records = JSON.parse(listed.output);
  assert.equal(records.length, 1);
  const saved = await adapter.execute({ action: 'download', download_id: records[0].id }, ctx);
  assert.equal(saved.status, 'executed');
  assert.equal(saved.artifacts.length, 1);
  const artifact = saved.artifacts[0];
  assert.equal(artifact.kind, 'download');
  assert.ok(path.relative(directory, artifact.path) && !path.relative(directory, artifact.path).startsWith('..'));
  assert.ok(!path.basename(artifact.path).includes(':'));
  assert.equal(fs.readFileSync(artifact.path, 'utf8'), 'verified download');
  assert.equal(fs.statSync(artifact.path).size, artifact.bytes);
  const traversal = await adapter.execute({ action: 'download', download_id: records[0].id, destination: '../outside' }, ctx);
  assert.equal(traversal.status, 'failed'); assert.match(traversal.error.message, /boundary/);
  console.log('DOWNLOAD_ARTIFACT_LIVE', JSON.stringify({ files: saved.artifacts.length, bytes: artifact.bytes, contained: true }));
});

test('a canceled partial download produces no success artifact', async t => {
  const { adapter, ctx, ref, directory } = await fixture(t);
  const started = adapter.page.waitForEvent('download');
  await adapter.execute({ action: 'act', op: 'click', ref: ref('Slow') }, ctx);
  await started;
  const listed = await adapter.execute({ action: 'downloads' }, ctx);
  const record = JSON.parse(listed.output)[0];
  assert.equal(record.status, 'pending');
  const cancelled = await adapter.execute({ action: 'cancel_download', download_id: record.id }, ctx);
  assert.equal(cancelled.status, 'executed');
  const status = JSON.parse((await adapter.execute({ action: 'downloads' }, ctx)).output)[0];
  assert.equal(status.status, 'canceled');
  const save = await adapter.execute({ action: 'download', download_id: record.id }, ctx);
  assert.equal(save.status, 'failed'); assert.equal(save.artifacts.length, 0);
  assert.ok(!fs.existsSync(path.join(directory, 'browser-downloads')));
});

test('Stop while waiting for a download cancels the native transfer promptly', async t => {
  const { adapter, ctx, ref } = await fixture(t);
  const started = adapter.page.waitForEvent('download');
  await adapter.execute({ action: 'act', op: 'click', ref: ref('Slow') }, ctx);
  await started;
  const record = [...adapter.downloads.records.values()][0];
  const controller = new AbortController();
  const saving = adapter.execute({ action: 'download', download_id: record.id }, { ...ctx, signal: controller.signal });
  controller.abort();
  const result = await saving;
  assert.equal(result.status, 'failed'); assert.equal(result.artifacts.length, 0);
  await Promise.race([record.done, new Promise(resolve => setTimeout(resolve, 500))]);
  assert.equal(record.status, 'canceled');
});

test('Chrome missing transfer proofs refuse writes and expose capability gaps', async () => {
  let writes = 0;
  const adapter = new ChromeBrowserAdapter({ has: () => true, findTool: () => ({}), callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]';
    writes++; return 'ok';
  } });
  for (const action of ['upload', 'downloads', 'download', 'cancel_download']) {
    const result = await adapter.execute({ action });
    assert.equal(result.status, 'failed'); assert.match(result.error.message, /does not support|cannot prove/);
  }
  assert.equal(writes, 0);
  assert.equal(browser.needsApproval({ action: 'upload' }), true);
  assert.equal(browser.needsApproval({ action: 'download' }), true);
  assert.equal(browser.readOnly({ action: 'downloads' }), true);
});

test('a completed download that grows during copy never writes past its artifact bound', async t => {
  const directory = fs.mkdtempSync(path.join(root, 'growing-download-'));
  const source = path.join(directory, 'native-source');
  const original = 'small'; fs.writeFileSync(source, original);
  const artifactLimit = 16; // Test bytes: expose an in-copy limit using a tiny regular source.
  const downloads = new BrowserDownloads({ limits: { bytes: artifactLimit, chunk: 8, waitMs: 1000, records: 2, filename: 32 } });
  const record = downloads.capture({ suggestedFilename: () => 'report.txt', failure: async () => null, path: async () => source, cancel: async () => {} }, 'owned');
  await record.done;
  const stream = fs.createReadStream.bind(fs);
  t.mock.method(fs, 'createReadStream', (...args) => { fs.appendFileSync(source, 'growth'.repeat(12)); return stream(...args); });
  const unlink = fs.promises.unlink.bind(fs.promises);
  let removedBytes = null;
  t.mock.method(fs.promises, 'unlink', async file => { removedBytes = (await fs.promises.stat(file)).size; return unlink(file); });
  await assert.rejects(downloads.save({ download_id: record.id }, 'owned', { cwd: directory, workspacePath: directory }), /limit|size changed|changed while/i);
  assert.ok(removedBytes <= artifactLimit, `temporary artifact wrote ${removedBytes} bytes past its ${artifactLimit}-byte bound`);
  assert.deepEqual(fs.readdirSync(path.join(directory, BROWSER_DOWNLOAD_DIRECTORY)), []);
  console.log('DOWNLOAD_GROWTH_BOUND_LIVE', JSON.stringify({ limitBytes: artifactLimit, removedBytes, published: 0 }));
});

test('completed download source changes of equal size refuse artifact publication', async t => {
  const directory = fs.mkdtempSync(path.join(root, 'changed-download-'));
  const source = path.join(directory, 'native-source'); fs.writeFileSync(source, 'original');
  const downloads = new BrowserDownloads();
  const record = downloads.capture({ suggestedFilename: () => 'report.txt', failure: async () => null, path: async () => source, cancel: async () => {} }, 'owned');
  await record.done;
  const stream = fs.createReadStream.bind(fs);
  t.mock.method(fs, 'createReadStream', (...args) => { const stat = fs.statSync(source); fs.writeFileSync(source, 'replaced'); fs.utimesSync(source, stat.atime, new Date(stat.mtimeMs + 2000)); return stream(...args); });
  await assert.rejects(downloads.save({ download_id: record.id }, 'owned', { cwd: directory, workspacePath: directory }), /changed while|changed before/i);
  assert.deepEqual(fs.readdirSync(path.join(directory, BROWSER_DOWNLOAD_DIRECTORY)), []);
});

test('a native download source cannot be a file symlink', async t => {
  const directory = fs.mkdtempSync(path.join(root, 'symlink-download-'));
  const source = path.join(directory, 'native-source'), linked = path.join(directory, 'linked-source'); fs.writeFileSync(source, 'owned content');
  let sourcePath = linked, coverage = 'real filesystem';
  try { fs.symlinkSync(source, linked, 'file'); }
  catch (error) {
    if (error.code !== 'EPERM') throw error;
    coverage = 'stub lstat on host without file symlinks'; sourcePath = source;
    const lstat = fs.promises.lstat.bind(fs.promises);
    t.mock.method(fs.promises, 'lstat', async file => { const stat = await lstat(file); if (file === source) stat.isSymbolicLink = () => true; return stat; });
  }
  const downloads = new BrowserDownloads();
  const record = downloads.capture({ suggestedFilename: () => 'report.txt', failure: async () => null, path: async () => sourcePath, cancel: async () => {} }, 'owned');
  await record.done;
  await assert.rejects(downloads.save({ download_id: record.id }, 'owned', { cwd: directory, workspacePath: directory }), /regular|symlink|junction/i);
  assert.ok(!fs.existsSync(path.join(directory, BROWSER_DOWNLOAD_DIRECTORY)));
  console.log('DOWNLOAD_SOURCE_LINK_GUARD', JSON.stringify({ coverage, published: 0 }));
});
