/**
 * Similarity between memory facts, used for two decisions that must never
 * destroy data on their own:
 *
 *   - merge: two facts say the same thing in different words
 *   - conflict: two facts look related but disagree
 *
 * Embeddings are used when available, but the module always has a deterministic
 * lexical fallback so memory quality never depends on a configured provider.
 */
export const DEFAULT_DEDUP_THRESHOLD = 0.85; // Above this, one fact, not two.
export const DEFAULT_CONFLICT_LOW = 0.55; // Below this, unrelated.
const MAX_COMPARE_FACTS = 2000; // Bounds a pathological profile without skipping recent facts.
const STOP_WORDS = new Set(['i', 'a', 'an', 'the', 'is', 'am', 'are', 'was', 'were', 'be', 'been', 'my', 'me', 'to', 'of', 'for', 'and', 'or', 'in', 'on', 'at', 'it', 'that', 'this', 'with', 'use', 'used', 'using', 'database', 'db', 'app', 'project', 'thing', 'stuff', 'like', 'prefer', 'want', 'need']);

const normalize = value => String(value ?? '').trim().toLocaleLowerCase().replace(/[^\p{L}\p{N}\s]+/gu, ' ').replace(/\s+/g, ' ').trim();

/** Content words only: "I use Postgres" and "Database is Postgres" share "postgres". */
export function tokens(value) {
  return new Set(normalize(value).split(' ').filter(word => word && !STOP_WORDS.has(word)));
}

// Two words match when equal, or when the shorter is a prefix of the longer and
// long enough to be meaningful: postgres/postgresql, migrate/migrated.
const MIN_PREFIX = 4;
function wordMatches(a, b) {
  if (a === b) return true;
  const [short, long] = a.length <= b.length ? [a, b] : [b, a];
  return short.length >= MIN_PREFIX && long.startsWith(short);
}

/**
 * Lexical overlap, deliberately conservative.
 *
 * Jaccard catches near-identical wording. A second, harsher term only counts
 * when EVERY content word of the shorter fact appears in the longer one
 * ("I use Postgres" ⊂ "Database is Postgres"), which is the common shape of a
 * repeated preference. It never matches on a single shared word alone.
 */
export function lexicalSimilarity(a, b) {
  const { jaccard, contained, small } = overlap(a, b);
  if (!small.size) return 0;
  const containment = small.size >= 2 && contained === small.size ? 0.9 : 0;
  // A single shared distinctive word ("postgres") links two short facts about
  // the same subject even when the phrasing differs. Requiring both sides to be
  // short keeps this from matching long, incidental sentences.
  const left = tokens(a), right = tokens(b);
  const single = left.size <= 2 && right.size <= 2 && contained === 1 && small.size === 1 ? 0.6 : 0;
  return Math.max(jaccard, containment, single);
}

function overlap(a, b) {
  const left = tokens(a), right = tokens(b);
  const [small, large] = left.size <= right.size ? [left, right] : [right, left];
  let contained = 0;
  for (const word of small) if ([...large].some(other => wordMatches(word, other))) contained++;
  const jaccard = left.size + right.size ? contained / (left.size + right.size - contained) : 0;
  return { jaccard, contained, small };
}

/**
 * True when two facts are about the same thing but say different things:
 * half or more of their content words agree, yet the wording is not identical.
 * Two-word facts cannot contradict lexically (one shared word is ambiguous),
 * so this requires at least three meaningful words and two agreements.
 */
export function lexicalRelated(a, b) {
  const { jaccard, contained } = overlap(a, b);
  const words = Math.max(tokens(a).size, tokens(b).size);
  return words >= 3 && contained >= 2 && jaccard >= 0.5 && normalize(a) !== normalize(b);
}

/**
 * Pick the most similar existing fact, if any.
 *
 * Returns `{ fact, score, kind: 'duplicate' | 'conflict' | null }`. With an
 * embedder the score is cosine similarity; otherwise lexical Jaccard. Facts
 * with a different declared `kind` never conflict with each other, only merge.
 */
export async function findSimilar(text, facts, {
  embedder = null, dedup = DEFAULT_DEDUP_THRESHOLD, conflictLow = DEFAULT_CONFLICT_LOW,
  kind = null, limit = MAX_COMPARE_FACTS, signal,
} = {}) {
  const candidates = (Array.isArray(facts) ? facts : [])
    // A punctuation-only variant ("I prefer dark mode." vs "I prefer dark mode")
    // is the same fact; it is handled by exact matching in the store, so it must
    // not be reported as a conflict either.
    .filter(fact => fact && typeof fact.text === 'string' && normalize(fact.text) !== normalize(text))
    .slice(-limit);
  if (!candidates.length) return { fact: null, score: 0, kind: null };

  let scores = null;
  if (embedder && typeof embedder.rank === 'function') {
    try {
      const result = await embedder.rank(String(text), candidates, { signal });
      if (result?.scores?.size) scores = result.scores;
    } catch { scores = null; } // A provider problem must never block a memory write.
  }

  let best = null;
  let scoredByEmbedder = false;
  for (const fact of candidates) {
    const fromEmbedder = Boolean(scores?.has(fact));
    const score = fromEmbedder ? scores.get(fact) : lexicalSimilarity(text, fact.text);
    if (!Number.isFinite(score)) continue;
    if (!best || score > best.score) { best = { fact, score }; scoredByEmbedder = fromEmbedder; }
  }
  if (!best) return { fact: null, score: 0, kind: null };
  if (best.score >= dedup) return { ...best, kind: 'duplicate' };
  // A conflict is only claimed between facts of the same declared category;
  // unrelated kinds sharing vocabulary are not a disagreement. A cold or partial
  // embedding index mixes cosine and lexical scores, so the cosine threshold is
  // only trusted when the winning score actually came from the embedder.
  const sameKind = !kind || !best.fact.kind || String(best.fact.kind) === String(kind);
  const related = scoredByEmbedder ? best.score >= conflictLow : lexicalRelated(text, best.fact.text);
  if (related && sameKind) return { ...best, kind: 'conflict' };
  return { fact: null, score: best.score, kind: null };
}

/** True when a fact has not been touched within the stale window. */
export function isStale(fact, { staleDays, now = Date.now() } = {}) {
  if (!fact || fact.always === true) return false; // Pins are deliberate and permanent.
  const days = Number(staleDays);
  if (!Number.isFinite(days) || days <= 0) return false;
  const at = Date.parse(fact.lastRecalledAt || fact.updatedAt || fact.createdAt || '');
  if (!Number.isFinite(at)) return false;
  return now - at > days * 86400000;
}
