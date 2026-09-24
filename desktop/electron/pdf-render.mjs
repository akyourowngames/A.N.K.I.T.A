import path from 'node:path';
import fs from 'node:fs/promises';
import os from 'node:os';
import { BrowserWindow } from 'electron';

const MAX_PAGES = 10;
const PAGE_WIDTH = 900;
const PAGE_HEIGHT = 1165; // ~A4 at 96dpi
const SETTLE_MS = 450;

/**
 * Rasterize PDF pages to compressed JPEG data URLs.
 *
 * Chromium's PDF viewer can render but does not expose its pixels to the page,
 * so this is done in a hidden window in the main process: load the PDF from a
 * temporary file, let the viewer paint, and capture the window rectangle once
 * per page while scrolling. JPEG keeps multi-page scans small enough to send
 * and store; the result feeds vision models directly and the OCR fallback.
 *
 * Returns [] (never throws) when rendering is unavailable, so a caller can fall
 * back to reporting that the document had no readable text.
 */
export async function renderPdfPages(base64, { maxPages = MAX_PAGES } = {}) {
  if (typeof base64 !== 'string' || !base64) return [];
  let file;
  let window;
  try {
    const bytes = Buffer.from(base64, 'base64');
    if (!bytes.length) return [];
    file = path.join(os.tmpdir(), `ankita-pdf-${process.pid}-${Date.now()}.pdf`);
    await fs.writeFile(file, bytes);

    window = new BrowserWindow({
      show: false,
      width: PAGE_WIDTH,
      height: PAGE_HEIGHT,
      webPreferences: { offscreen: false, plugins: true, sandbox: true },
    });
    await window.loadURL(`file://${file.replace(/\\/g, '/').replace(/^([a-zA-Z]:)/, '$1')}`);
    // The built-in viewer needs a moment to lay the document out.
    await new Promise(resolve => setTimeout(resolve, SETTLE_MS));

    const pages = [];
    for (let index = 0; index < maxPages; index++) {
      const image = await window.webContents.capturePage({ x: 0, y: 0, width: PAGE_WIDTH, height: PAGE_HEIGHT });
      const jpeg = image.isEmpty() ? Buffer.alloc(0) : image.toJPEG(80);
      const dataUrl = jpeg.length ? `data:image/jpeg;base64,${jpeg.toString('base64')}` : '';
      if (!dataUrl || dataUrl.length > 2_500_000) break;
      pages.push(dataUrl);
      // Scroll the viewer one viewport down for the next page.
      await window.webContents.executeJavaScript(
        `(() => { const el = document.querySelector('embed, #viewer'); if (el && el.scrollTo) el.scrollTo(0, ${index + 1} * ${PAGE_HEIGHT}); else window.scrollTo(0, ${index + 1} * ${PAGE_HEIGHT}); return true; })()`
      ).catch(() => {});
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    return pages;
  } catch {
    return [];
  } finally {
    try { window?.destroy(); } catch { /* already gone */ }
    if (file) await fs.unlink(file).catch(() => {});
  }
}
