import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as imageGenerate from '../../tools/images/image-generate.mjs';
import * as imageDownload from '../../tools/images/image-download.mjs';
import * as unsplash from '../../tools/images/unsplash-search.mjs';
import * as pixabay from '../../tools/images/pixabay-search.mjs';
import { CATEGORIES } from '../../tools/catalog.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';

const jsonResponse = (data, status = 200, headers = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(headers),
  json: async () => data,
  text: async () => '',
});

test('image capabilities are separate deferred tools in one discoverable category', () => {
  const imageCategory = CATEGORIES.find(category => category.id === 'images');
  assert.ok(imageCategory);
  assert.deepEqual(imageCategory.tools.map(tool => tool.name), ['image_generate', 'unsplash_search', 'pixabay_search', 'image_download']);
  assert.equal(imageGenerate.needsApproval, true);
  assert.equal(unsplash.needsApproval, false);
  assert.equal(pixabay.needsApproval, false);
});

test('image download saves selected Unsplash/Pixabay images and preserves attribution', async t => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-stock-download-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const bytes = Buffer.from('stock-test-image');
  let requestedUrl;
  const output = await imageDownload.run({
    url: 'https://images.unsplash.com/photo-123?auto=format', source: 'unsplash',
    pageUrl: 'https://unsplash.com/photos/photo-123', photographer: 'Photo Maker', filename: 'fox-photo',
  }, { cwd }, async url => {
    requestedUrl = String(url);
    return { ...jsonResponse({}), headers: new Headers({ 'content-type': 'image/jpeg', 'content-length': String(bytes.length) }), arrayBuffer: async () => bytes };
  }, async host => { assert.equal(host, 'images.unsplash.com'); return ['8.8.8.8']; });
  assert.equal(requestedUrl, 'https://images.unsplash.com/photo-123?auto=format');
  const result = JSON.parse(output);
  assert.equal(result.type, 'downloaded_image');
  assert.equal(result.path, 'downloaded-images/fox-photo.jpg');
  assert.equal(result.photographer, 'Photo Maker');
  assert.deepEqual(fs.readFileSync(path.join(cwd, result.path)), bytes);
});

test('image download refuses a host outside the selected stock source', async () => {
  await assert.rejects(imageDownload.run({ url: 'https://example.com/image.png', source: 'pixabay' }, { cwd: process.cwd() }, async () => { throw new Error('must not fetch'); }), /Only HTTPS image URLs/);
});

test('image generation posts to the configured endpoint and saves a bounded image in the workspace', async t => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-image-gen-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const bytes = Buffer.from('small-test-image');
  let request;
  const output = await imageGenerate.run({ prompt: 'A tiny test landscape', size: '1024x1024', quality: 'low' }, {
    cwd,
    config: { imageApiBase: 'https://images.example/v1/', imageApiKey: 'private-image-key', imageModel: 'image-test' },
  }, async (url, options) => {
    request = { url: String(url), options, body: JSON.parse(options.body) };
    return jsonResponse({ data: [{ b64_json: bytes.toString('base64'), revised_prompt: 'Revised landscape' }] });
  });

  assert.equal(request.url, 'https://images.example/v1/images/generations');
  assert.equal(request.options.headers.Authorization, 'Bearer private-image-key');
  assert.equal(request.body.model, 'image-test');
  assert.equal(request.body.prompt, 'A tiny test landscape');
  const result = JSON.parse(output);
  assert.equal(result.type, 'generated_image');
  assert.equal(result.revisedPrompt, 'Revised landscape');
  assert.match(result.path, /^generated-images\/image-.*\.png$/);
  assert.deepEqual(fs.readFileSync(path.join(cwd, result.path)), bytes);
  assert.equal(output.includes('private-image-key'), false);
});

test('image generation requires a configured image or compatible model endpoint', async () => {
  await assert.rejects(imageGenerate.run({ prompt: 'A poster' }, { cwd: process.cwd(), config: {} }, async () => { throw new Error('must not fetch'); }), /IMAGE_API_BASE/);
});

test('image generation never overwrites an explicitly named image', async t => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-image-existing-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const dir = path.join(cwd, 'generated-images');
  fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, 'logo.png'), 'original');
  await assert.rejects(imageGenerate.run({ prompt: 'A logo', filename: 'logo.png' }, {
    cwd, config: { apiBase: 'https://images.example/v1', apiKey: 'key' },
  }, async () => jsonResponse({ data: [{ b64_json: Buffer.from('new').toString('base64') }] })), /already exists/);
  assert.equal(fs.readFileSync(path.join(dir, 'logo.png'), 'utf8'), 'original');
});

test('Unsplash search uses its own key and returns attributed previews', async () => {
  let request;
  const output = await unsplash.run({ query: 'red fox', limit: 1 }, { config: { unsplashAccessKey: 'unsplash-secret' } }, async (url, options) => {
    request = { url: new URL(url), options };
    return jsonResponse({ results: [{
      id: 'photo-1', alt_description: 'Red fox in snow', urls: { small: 'https://images.unsplash.com/photo-small', regular: 'https://images.unsplash.com/photo-large' },
      links: { html: 'https://unsplash.com/photos/photo-1' }, user: { name: 'Photo Maker', links: { html: 'https://unsplash.com/@maker' } },
    }] });
  });
  assert.equal(request.options.headers.Authorization, 'Client-ID unsplash-secret');
  assert.equal(request.url.searchParams.get('query'), 'red fox');
  const result = JSON.parse(output);
  assert.equal(result.provider, 'unsplash');
  assert.equal(result.results[0].photographer, 'Photo Maker');
  assert.equal(output.includes('unsplash-secret'), false);
});

test('Pixabay search uses a separate key and returns contributor metadata', async () => {
  let request;
  const output = await pixabay.run({ query: 'blue bicycle', imageType: 'photo' }, { config: { pixabayApiKey: 'pixabay-secret' } }, async (url) => {
    request = new URL(url);
    return jsonResponse({ hits: [{ id: 2, tags: 'blue bicycle', previewURL: 'https://cdn.pixabay.com/preview.jpg', webformatURL: 'https://cdn.pixabay.com/image.jpg', pageURL: 'https://pixabay.com/photos/bicycle-2/', user: 'Contributor' }] });
  });
  assert.equal(request.searchParams.get('key'), 'pixabay-secret');
  assert.equal(request.searchParams.get('q'), 'blue bicycle');
  const result = JSON.parse(output);
  assert.equal(result.provider, 'pixabay');
  assert.equal(result.results[0].photographer, 'Contributor');
  assert.equal(output.includes('pixabay-secret'), false);
});

test('desktop image preview only reads images within the teammate workspace', async t => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-image-preview-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  fs.mkdirSync(path.join(cwd, 'generated-images'));
  fs.writeFileSync(path.join(cwd, 'generated-images', 'preview.png'), Buffer.from('image-bytes'));
  const engine = Object.create(DesktopEngine.prototype);
  engine.agents = new Map([['chief', { cwd }]]);
  engine.teammates = { find: id => id === 'chief' ? { id, projectId: null } : null };
  const value = await engine.readGeneratedImage('chief', 'generated-images/preview.png');
  assert.equal(value.dataUrl, `data:image/png;base64,${Buffer.from('image-bytes').toString('base64')}`);
  const absolute = await engine.readGeneratedImage('chief', path.join(cwd, 'generated-images', 'preview.png'));
  assert.equal(absolute.dataUrl, value.dataUrl);
  await assert.rejects(engine.readGeneratedImage('chief', '../outside.png'), /workspace/);
  await assert.rejects(engine.readGeneratedImage('missing', 'generated-images/preview.png'), /Teammate not found/);
});

test('desktop image preview accepts paths through a workspace junction', async t => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-image-alias-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const workspace = path.join(base, 'workspace');
  const alias = path.join(base, 'alias');
  fs.mkdirSync(path.join(workspace, 'generated-images'), { recursive: true });
  fs.writeFileSync(path.join(workspace, 'generated-images', 'preview.png'), Buffer.from('image-bytes'));
  fs.symlinkSync(workspace, alias, process.platform === 'win32' ? 'junction' : 'dir');
  const engine = Object.create(DesktopEngine.prototype);
  engine.agents = new Map([['chief', { cwd: alias }]]);
  engine.teammates = { find: id => id === 'chief' ? { id, projectId: null } : null };
  const expected = `data:image/png;base64,${Buffer.from('image-bytes').toString('base64')}`;
  assert.equal((await engine.readGeneratedImage('chief', 'generated-images/preview.png')).dataUrl, expected);
  assert.equal((await engine.readGeneratedImage('chief', path.join(alias, 'generated-images', 'preview.png'))).dataUrl, expected);
});
