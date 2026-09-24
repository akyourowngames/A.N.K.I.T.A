const ENDPOINT = 'https://pixabay.com/api/';
import { deadlineSignal } from './_image-utils.mjs';

export const name = 'pixabay_search';
export const description = 'Search Pixabay for stock photos and illustrations. Returns preview/full image URLs with contributor attribution and the source page; this is separate from image generation.';
export const parameters = {
  type: 'object',
  properties: {
    query: { type: 'string', description: 'What the photo or illustration should show.' },
    imageType: { type: 'string', enum: ['all', 'photo', 'illustration', 'vector'], description: 'Optional Pixabay image type; default all.' },
    orientation: { type: 'string', enum: ['all', 'horizontal', 'vertical'], description: 'Optional orientation; default all.' },
    limit: { type: 'integer', description: 'Results to return, 1–10; default 5.' },
  },
  required: ['query'],
};
export const readOnly = true;
export const needsApproval = false;

export async function run(args = {}, ctx = {}, fetchImpl = globalThis.fetch) {
  const query = String(args.query || '').trim();
  if (!query) throw new Error('Enter a search query for Pixabay');
  if (query.length > 200) throw new Error('Search query must be 200 characters or fewer');
  const key = String(ctx.config?.pixabayApiKey || '').trim();
  if (!key) throw new Error('Add a Pixabay API key in Settings → Images (or set PIXABAY_API_KEY)');
  const limit = Math.max(1, Math.min(10, Math.floor(Number(args.limit) || 5)));
  const url = new URL(ENDPOINT);
  url.search = new URLSearchParams({
    key,
    q: query,
    image_type: ['all', 'photo', 'illustration', 'vector'].includes(args.imageType) ? args.imageType : 'all',
    orientation: ['all', 'horizontal', 'vertical'].includes(args.orientation) ? args.orientation : 'all',
    per_page: String(limit),
    safesearch: 'true',
  }).toString();
  const deadline = deadlineSignal(ctx.signal, 15_000);
  let payload;
  try {
    const response = await fetchImpl(url, { headers: { Accept: 'application/json' }, signal: deadline.signal });
    if (!response.ok) throw new Error(`Pixabay search failed (HTTP ${response.status}); check the API key in Settings → Images`);
    payload = await response.json();
  } catch (error) {
    if (String(error?.message || '').startsWith('Pixabay search failed')) throw error;
    if (deadline.signal.aborted) throw new Error('Pixabay search timed out or was cancelled');
    throw new Error('Pixabay search failed; check the API key and network');
  } finally { deadline.dispose(); }
  const results = (Array.isArray(payload?.hits) ? payload.hits : []).slice(0, limit).map(hit => ({
    id: String(hit.id || ''),
    title: String(hit.tags || query).slice(0, 240),
    previewUrl: hit.previewURL || '',
    imageUrl: hit.webformatURL || hit.largeImageURL || '',
    pageUrl: hit.pageURL || '',
    photographer: String(hit.user || 'Pixabay contributor').slice(0, 120),
    photographerUrl: hit.pageURL || '',
    source: 'Pixabay',
  })).filter(image => image.previewUrl && image.pageUrl);
  return JSON.stringify({ type: 'stock_image_results', provider: 'pixabay', query, results });
}
