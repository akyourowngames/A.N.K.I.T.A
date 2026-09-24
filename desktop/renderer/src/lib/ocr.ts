/**
 * On-demand OCR for documents that carry no text layer (scans, photos of
 * pages).
 *
 * The engine prefers a vision model reading page images, and this is the
 * fallback for when the selected model cannot see. Tesseract is fetched the
 * first time it is needed rather than bundled, so a normal session pays nothing
 * for it and an offline machine simply reports that OCR is unavailable instead
 * of failing the attachment.
 *
 * The browser caches the language data after the first use.
 */

const TESSERACT_URL = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.esm.min.js';
const MAX_OCR_PAGES = 10;
const MAX_OCR_SIDE = 2000;

type TesseractWorker = { recognize: (image: string) => Promise<{ data?: { text?: string } }>; terminate: () => Promise<unknown> };
type TesseractModule = { createWorker: (lang: string) => Promise<TesseractWorker> };

let modulePromise: Promise<TesseractModule | null> | null = null;

function loadTesseract(): Promise<TesseractModule | null> {
  if (!modulePromise) {
    modulePromise = import(/* @vite-ignore */ TESSERACT_URL)
      .then(mod => (typeof (mod as TesseractModule)?.createWorker === 'function' ? (mod as TesseractModule) : null))
      .catch(() => null);
  }
  return modulePromise;
}

/** True when OCR could run: online and the library is reachable. */
export async function ocrAvailable(): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return false;
  return Boolean(await loadTesseract());
}

/**
 * OCR one or more image data URLs into a single text block.
 *
 * Returns '' when OCR is unavailable or produced nothing, so the caller keeps
 * the original (possibly empty) text rather than inventing content.
 */
export async function ocrImages(dataUrls: string[]): Promise<string> {
  const tesseract = await loadTesseract();
  if (!tesseract || !Array.isArray(dataUrls) || !dataUrls.length) return '';
  let worker: TesseractWorker | null = null;
  try {
    worker = await tesseract.createWorker('eng');
    const pages: string[] = [];
    for (const url of dataUrls.slice(0, MAX_OCR_PAGES)) {
      const prepared = await prepare(url);
      if (!prepared) continue;
      const { data } = await worker.recognize(prepared);
      const text = data?.text?.trim();
      if (text) pages.push(text);
    }
    return pages.join('\n\n');
  } catch {
    return '';
  } finally {
    try { await worker?.terminate(); } catch { /* worker already gone */ }
  }
}

/**
 * Downscale a data URL before OCR.
 *
 * A phone photo can be several thousand pixels wide; Tesseract is both slower
 * and no more accurate above roughly 2000px, and a smaller bitmap keeps the
 * worker's memory bounded.
 */
async function prepare(dataUrl: string): Promise<string | null> {
  try {
    const image = await loadImage(dataUrl);
    const longest = Math.max(image.width, image.height) || MAX_OCR_SIDE;
    const scale = Math.min(1, MAX_OCR_SIDE / longest);
    if (scale === 1) return dataUrl;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const context = canvas.getContext('2d');
    if (!context) return dataUrl;
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/png');
  } catch {
    return null;
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('image failed to load'));
    image.src = src;
  });
}
