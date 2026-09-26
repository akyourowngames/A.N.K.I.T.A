import fs from 'node:fs';
import path from 'node:path';
import { resolvePath } from '../shared/_shared.mjs';

// Shared artifact contract and workspace folder; only browser-produced PNG receipts qualify.
export const BROWSER_SCREENSHOT_TYPE = 'browser_screenshot';
export const BROWSER_SCREENSHOT_DIRECTORY = 'downloaded-images';
const BROWSER_CAPTURE_NAME = /^browser-\d+-[a-f\d-]+\.png$/i;
// Bytes/count: match the desktop image cap and bound automatic vision attachments per request.
export const MAX_BROWSER_SCREENSHOT_BYTES = 15 * 1024 * 1024;
export const MAX_BROWSER_SCREENSHOTS_PER_TURN = 3;
const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

export function browserScreenshotImage(result, ctx) {
  try {
    const receipt = typeof result === 'string' ? JSON.parse(result) : result;
    if (receipt?.type !== BROWSER_SCREENSHOT_TYPE || typeof receipt.path !== 'string') return null;
    const file = resolvePath(receipt.path, ctx);
    const relative = path.relative(path.resolve(ctx.cwd), file);
    if (path.dirname(relative) !== BROWSER_SCREENSHOT_DIRECTORY || !BROWSER_CAPTURE_NAME.test(path.basename(relative))) return null;
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.size > MAX_BROWSER_SCREENSHOT_BYTES || stat.size !== receipt.bytes) return null;
    const bytes = fs.readFileSync(file);
    if (!bytes.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)) return null;
    return { receipt, dataUrl: `data:image/png;base64,${bytes.toString('base64')}` };
  } catch { return null; }
}
