import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { checkUrlPublic } from './_web.mjs';
import { deadlineSignal } from './_image-utils.mjs';

const MAX_BYTES = 15 * 1024 * 1024;
const HOSTS = new Set(['images.unsplash.com', 'pixabay.com', 'cdn.pixabay.com']);
const EXTENSIONS = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' };

export const name = 'image_download';
export const description = 'Download one selected Unsplash or Pixabay image into downloaded-images in the current workspace. Use the imageUrl and attribution from unsplash_search or pixabay_search results.';
export const parameters = {
  type: 'object',
  properties: {
    url: { type: 'string', description: 'imageUrl from Unsplash or Pixabay results.' },
    source: { type: 'string', enum: ['unsplash', 'pixabay'], description: 'Image source.' },
    pageUrl: { type: 'string', description: 'Source page URL from the search result, retained for attribution.' },
    photographer: { type: 'string', description: 'Photographer/contributor name from the search result.' },
    filename: { type: 'string', description: 'Optional filename. The file extension is chosen from the downloaded image format.' },
  },
  required: ['url', 'source'],
};
export const readOnly = false;
export const needsApproval = true;

export function approval(args = {}) {
  let host = 'unknown host';
  try { host = new URL(args.url).hostname; } catch {}
  return `Download this ${args.source || 'stock'} image from ${host} into downloaded-images in the current workspace?\nAttribution: ${String(args.photographer || 'unknown contributor').slice(0, 120)}`;
}

function filenameFor(value, extension) {
  const leaf = path.basename(String(value || '')).replace(/\.[a-z0-9]{2,5}$/i, '');
  const base = leaf.replace(/[^a-zA-Z0-9_-]/g, '-').replace(/^-+|-+$/g, '');
  return `${base || `stock-${Date.now()}-${randomUUID().slice(0, 8)}`}.${extension}`;
}

export async function run(args = {}, ctx = {}, fetchImpl = globalThis.fetch, resolveFn) {
  let url;
  try { url = new URL(String(args.url || '')); } catch { throw new Error('Provide an imageUrl from Unsplash or Pixabay search results'); }
  const source = String(args.source || '').toLowerCase();
  if (!['unsplash', 'pixabay'].includes(source)) throw new Error('Image source must be unsplash or pixabay');
  const hostAllowed = source === 'unsplash'
    ? url.hostname === 'images.unsplash.com'
    : ['pixabay.com', 'cdn.pixabay.com'].includes(url.hostname);
  if (url.protocol !== 'https:' || !hostAllowed) throw new Error('Only HTTPS image URLs from the selected Unsplash or Pixabay CDN are allowed');
  const denied = await checkUrlPublic(url.href, resolveFn);
  if (denied) throw new Error('Refusing to fetch an image URL that does not resolve to a public host');
  const deadline = deadlineSignal(ctx.signal, 30_000);
  let bytes;
  let mime;
  let extension;
  try {
    const response = await fetchImpl(url.href, { signal: deadline.signal, redirect: 'error' });
    if (!response.ok) throw new Error(`Image download failed (HTTP ${response.status})`);
    mime = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    extension = EXTENSIONS[mime];
    if (!extension) throw new Error('The selected image has an unsupported format (PNG, JPEG and WebP are supported)');
    const declared = Number(response.headers.get('content-length'));
    if (Number.isFinite(declared) && declared > MAX_BYTES) throw new Error('Image is larger than 15 MB');
    bytes = Buffer.from(await response.arrayBuffer());
    if (!bytes.length || bytes.length > MAX_BYTES) throw new Error('Image is empty or larger than 15 MB');
  } finally { deadline.dispose(); }

  const cwd = path.resolve(ctx.cwd || process.cwd());
  const outputDir = path.join(cwd, 'downloaded-images');
  await fs.mkdir(outputDir, { recursive: true });
  const filename = filenameFor(args.filename, extension);
  const outputPath = path.join(outputDir, filename);
  try { await fs.writeFile(outputPath, bytes, { flag: 'wx' }); }
  catch (error) {
    if (error.code === 'EEXIST') throw new Error('That filename already exists; choose another filename');
    throw error;
  }
  const pageUrl = String(args.pageUrl || '');
  return JSON.stringify({
    type: 'downloaded_image',
    source,
    path: path.relative(cwd, outputPath).split(path.sep).join('/'),
    mime,
    bytes: bytes.length,
    photographer: String(args.photographer || '').slice(0, 120),
    pageUrl: /^https:\/\//i.test(pageUrl) ? pageUrl : '',
  });
}
