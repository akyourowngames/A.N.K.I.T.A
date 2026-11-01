import fs from 'node:fs/promises';
import path from 'node:path';
import { recentArtifacts } from '../../../desktop/electron/workspace.mjs';
import { MAX_ARTIFACTS, MAX_ARTIFACT_BYTES, TELEGRAM_PHOTO_BYTES } from './contract.mjs';

const ARTIFACT_FOLDERS = new Set(['generated-images', 'downloaded-images']); // Existing workspace preview/Telegram containment boundary.
const IMAGE_MIMES = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };

export async function readChannelArtifact(cwd, requested) {
  const root = await fs.realpath(cwd), candidate = path.resolve(cwd, requested);
  const absolute = await fs.realpath(candidate), relative = path.relative(root, absolute);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative) || !ARTIFACT_FOLDERS.has(relative.split(path.sep)[0])) throw new Error('Artifact is outside generated/downloaded images');
  const mime = IMAGE_MIMES[path.extname(absolute).toLowerCase()];
  if (!mime) throw new Error('Unsupported artifact format');
  const handle = await fs.open(absolute, 'r');
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > MAX_ARTIFACT_BYTES) throw new Error('Artifact exceeds the upload limit');
    const bytes = await handle.readFile();
    if (bytes.length > MAX_ARTIFACT_BYTES) throw new Error('Artifact exceeds the upload limit');
    return { bytes, mime, filename: path.basename(absolute), photo: ['image/png', 'image/jpeg'].includes(mime) && bytes.length <= TELEGRAM_PHOTO_BYTES };
  } finally { await handle.close(); }
}

export async function sendChannelArtifacts(adapter, ref, cwd, messages, cancelled = () => false, outbox = null) {
  if (!adapter.manifest.capabilities.includes('upload')) return;
  const artifacts = recentArtifacts(cwd, messages).slice(0, MAX_ARTIFACTS);
  for (let index = 0; index < artifacts.length; index++) {
    if (cancelled()) break;
    const artifact = artifacts[index];
    try {
      const file = await readChannelArtifact(cwd, artifact.path);
      if (cancelled()) break;
      if (adapter.manifest.capabilities.includes('typing')) await adapter.typing(ref, file.photo ? 'upload_photo' : 'upload_document');
      const { bytes, ...metadata } = file;
      const payload = { ...metadata, base64: bytes.toString('base64'), caption: artifact.name };
      const envelope = { ...ref, parts: [], files: [payload], replyTo: ref.messageId, intent: `artifact:${index}` };
      if (outbox) await outbox.deliver(envelope, adapter);
      else await adapter.upload(envelope, payload);
    } catch { await adapter.send({ ...ref, parts: [`Could not upload ${artifact.name}. The artifact remains in the workspace.`], replyTo: ref.messageId, intent: 'notice' }).catch(() => {}); }
  }
}
