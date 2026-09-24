import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { checkUrlPublic } from './_web.mjs';
import { deadlineSignal } from './_image-utils.mjs';

const MAX_IMAGE_BYTES = 15 * 1024 * 1024;
const SIZES = new Set(['1024x1024', '1536x1024', '1024x1536', '1792x1024', '1024x1792']);
const QUALITIES = new Set(['low', 'medium', 'high', 'standard', 'hd']);

export const name = 'image_generate';
export const description = 'Generate an original image from a prompt using the configured OpenAI-compatible image API, save it under generated-images in the current workspace, and return its path for preview in the desktop app.';
export const parameters = {
  type: 'object',
  properties: {
    prompt: { type: 'string', description: 'Detailed visual description of the image to create.' },
    size: { type: 'string', enum: [...SIZES], description: 'Output dimensions; default 1024x1024.' },
    quality: { type: 'string', enum: [...QUALITIES], description: 'Optional provider-supported quality. Leave unset to use the model default.' },
    filename: { type: 'string', description: 'Optional simple filename (without a directory). The tool chooses a unique name by default.' },
  },
  required: ['prompt'],
};
export const readOnly = false;
export const needsApproval = true;

export function approval(args = {}, ctx = {}) {
  const model = ctx.config?.imageModel || 'gpt-image-1';
  return `Generate an image with ${model} and save it in this workspace?\nPrompt: ${String(args.prompt || '').slice(0, 700)}`;
}

function safeFilename(value, extension) {
  const leaf = path.basename(String(value || '')).replace(/\.[a-z0-9]{2,5}$/i, '');
  const base = leaf.replace(/[^a-zA-Z0-9_-]/g, '-').replace(/^-+|-+$/g, '');
  return `${base || `image-${Date.now()}-${randomUUID().slice(0, 8)}`}.${extension}`;
}

function extensionFor(mime) {
  return ({ 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' })[mime] || null;
}

async function downloadImage(url, fetchImpl, parentSignal) {
  let parsed;
  try { parsed = new URL(url); } catch { throw new Error('Image provider returned an invalid image URL'); }
  if (parsed.protocol !== 'https:') throw new Error('Image provider returned an unsafe non-HTTPS image URL');
  const denied = await checkUrlPublic(parsed.href);
  if (denied) throw new Error('Image provider returned a non-public image URL');
  const deadline = deadlineSignal(parentSignal, 30_000);
  try {
    const response = await fetchImpl(parsed.href, { signal: deadline.signal, redirect: 'error' });
    if (!response.ok) throw new Error(`Could not download generated image (HTTP ${response.status})`);
    const mime = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (!extensionFor(mime)) throw new Error('Image provider returned an unsupported image format');
    const declared = Number(response.headers.get('content-length'));
    if (Number.isFinite(declared) && declared > MAX_IMAGE_BYTES) throw new Error('Generated image is larger than 15 MB');
    const bytes = Buffer.from(await response.arrayBuffer());
    if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) throw new Error('Generated image is empty or larger than 15 MB');
    return { bytes, mime };
  } finally { deadline.dispose(); }
}

export async function run(args = {}, ctx = {}, fetchImpl = globalThis.fetch) {
  const prompt = String(args.prompt || '').trim();
  if (!prompt) throw new Error('Describe the image you want to generate');
  if (prompt.length > 4000) throw new Error('Image prompt must be 4000 characters or fewer');

  const config = ctx.config || {};
  const base = String(config.imageApiBase || config.apiBase || '').trim().replace(/\/+$/, '');
  const key = String(config.imageApiKey || config.apiKey || '').trim();
  const model = String(config.imageModel || 'gpt-image-1').trim();
  if (!base) throw new Error('Configure an image API base URL in Settings → Images (or set IMAGE_API_BASE)');
  if (!model) throw new Error('Configure an image model in Settings → Images');
  if (typeof fetchImpl !== 'function') throw new Error('HTTP fetch is unavailable');

  const size = args.size || '1024x1024';
  const quality = args.quality;
  if (!SIZES.has(size)) throw new Error('Unsupported image size');
  if (quality && !QUALITIES.has(quality)) throw new Error('Unsupported image quality');

  let response;
  let payload;
  const deadline = deadlineSignal(ctx.signal, 120_000);
  try {
    response = await fetchImpl(`${base}/images/generations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(key ? { Authorization: `Bearer ${key}` } : {}),
      },
      body: JSON.stringify({ model, prompt, size, ...(quality ? { quality } : {}), n: 1 }),
      signal: deadline.signal,
    });
    if (!response.ok) throw new Error(`Image API returned HTTP ${response.status}`);
    payload = await response.json().catch(() => null);
  } catch (error) {
    if (String(error?.message || '').startsWith('Image API returned HTTP')) throw error;
    if (deadline.signal.aborted) throw new Error('Image generation timed out or was cancelled');
    throw new Error('Could not reach the configured image API');
  } finally { deadline.dispose(); }
  const item = payload?.data?.[0];
  if (!item) throw new Error('Image API response did not contain an image');

  let bytes;
  let mime;
  if (typeof item.b64_json === 'string' && item.b64_json) {
    bytes = Buffer.from(item.b64_json, 'base64');
    // PNG is the standard format for OpenAI-compatible b64_json responses.
    mime = 'image/png';
  } else if (typeof item.url === 'string') {
    ({ bytes, mime } = await downloadImage(item.url, fetchImpl, ctx.signal));
  } else {
    throw new Error('Image API returned neither b64_json nor a downloadable URL');
  }
  if (!bytes.length || bytes.length > MAX_IMAGE_BYTES || !extensionFor(mime)) throw new Error('Generated image is empty, too large, or in an unsupported format');

  const ext = extensionFor(mime);
  const name = safeFilename(args.filename || '', ext);
  const cwd = path.resolve(ctx.cwd || process.cwd());
  const outputDir = path.join(cwd, 'generated-images');
  await fs.mkdir(outputDir, { recursive: true });
  const outputPath = path.join(outputDir, name);
  // Never overwrite an existing image, including an explicitly named file.
  try { await fs.writeFile(outputPath, bytes, { flag: 'wx' }); }
  catch (error) {
    if (error.code === 'EEXIST') throw new Error('That image filename already exists; choose a different filename');
    throw error;
  }

  return JSON.stringify({
    type: 'generated_image',
    prompt,
    model,
    path: path.relative(cwd, outputPath).split(path.sep).join('/'),
    mime,
    bytes: bytes.length,
    revisedPrompt: typeof item.revised_prompt === 'string' ? item.revised_prompt.slice(0, 1000) : undefined,
  });
}
