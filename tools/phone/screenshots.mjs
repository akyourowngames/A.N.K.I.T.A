import fs from 'node:fs';
import { PHONE_SCREENSHOT_TYPE, resolvePhoneScreenshot } from '../../src/integrations/phone-control.mjs';

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]); // The receipt must describe a real PNG, not a renamed file.

export const MAX_PHONE_SCREENSHOTS_PER_TURN = 3; // Images/turn; mirrors the browser cap so one loop cannot flood the conversation.

/**
 * Validates a `phone` screenshot receipt and returns the image the host can
 * attach. Same contract as the browser receipt: the bytes on disk are checked
 * again here, because the receipt is model-visible JSON and cannot be trusted
 * on its own.
 */
export function phoneScreenshotImage(result, ctx = {}) {
  try {
    const receipt = typeof result === 'string' ? JSON.parse(result) : result;
    if (receipt?.type !== PHONE_SCREENSHOT_TYPE) return null;
    const file = resolvePhoneScreenshot(receipt, ctx);
    if (!file) return null;
    const bytes = fs.readFileSync(file);
    if (bytes.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE) === false) return null;
    return { receipt, dataUrl: `data:image/png;base64,${bytes.toString('base64')}` };
  } catch { return null; }
}
