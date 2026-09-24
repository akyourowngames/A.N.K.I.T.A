const ENDPOINT = 'https://api.unsplash.com/search/photos';
import { deadlineSignal } from './_image-utils.mjs';

export const name = 'unsplash_search';
export const description = 'Search Unsplash for stock photos. Returns preview/full image URLs with photographer attribution and the source page; this is separate from image generation.';
export const parameters = {
  type: 'object',
  properties: {
    query: { type: 'string', description: 'What the photo should show.' },
    orientation: { type: 'string', enum: ['landscape', 'portrait', 'squarish'], description: 'Optional preferred orientation.' },
    limit: { type: 'integer', description: 'Results to return, 1–10; default 5.' },
  },
  required: ['query'],
};
export const readOnly = true;
export const needsApproval = false;

export async function run(args = {}, ctx = {}, fetchImpl = globalThis.fetch) {
  const query = String(args.query || '').trim();
  if (!query) throw new Error('Enter a search query for Unsplash');
  if (query.length > 200) throw new Error('Search query must be 200 characters or fewer');
  const key = String(ctx.config?.unsplashAccessKey || '').trim();
  if (!key) throw new Error('Add an Unsplash access key in Settings → Images (or set UNSPLASH_ACCESS_KEY)');
  const limit = Math.max(1, Math.min(10, Math.floor(Number(args.limit) || 5)));
  const url = new URL(ENDPOINT);
  url.search = new URLSearchParams({ query, per_page: String(limit), ...(args.orientation ? { orientation: String(args.orientation) } : {}) }).toString();
  const deadline = deadlineSignal(ctx.signal, 15_000);
  let payload;
  try {
    const response = await fetchImpl(url, { headers: { Authorization: `Client-ID ${key}`, Accept: 'application/json' }, signal: deadline.signal });
    if (!response.ok) throw new Error(`Unsplash search failed (HTTP ${response.status}); check the access key in Settings → Images`);
    payload = await response.json();
  } catch (error) {
    if (String(error?.message || '').startsWith('Unsplash search failed')) throw error;
    if (deadline.signal.aborted) throw new Error('Unsplash search timed out or was cancelled');
    throw new Error('Unsplash search failed; check the access key and network');
  } finally { deadline.dispose(); }
  const results = (Array.isArray(payload?.results) ? payload.results : []).slice(0, limit).map(photo => ({
    id: String(photo.id || ''),
    title: String(photo.alt_description || photo.description || query).slice(0, 240),
    previewUrl: photo.urls?.small || photo.urls?.thumb || '',
    imageUrl: photo.urls?.regular || photo.urls?.full || '',
    pageUrl: photo.links?.html || '',
    photographer: String(photo.user?.name || 'Unsplash photographer').slice(0, 120),
    photographerUrl: photo.user?.links?.html || '',
    source: 'Unsplash',
  })).filter(photo => photo.previewUrl && photo.pageUrl);
  return JSON.stringify({ type: 'stock_image_results', provider: 'unsplash', query, results });
}
