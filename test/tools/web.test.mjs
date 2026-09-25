import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeUrl,
  truncateHeadTail,
  cacheKey,
  TtlCache,
  isPublicIp,
  checkUrlPublic,
  fitJson,
  needsStealthResult,
  formatRecord,
  decodeEntities,
  runBridge,
} from '../../tools/shared/_web.mjs';
import { parseDdgHtml, parseGnewsXml, searchDdg, searchRun } from '../../tools/web/web-search.mjs';
import { extractReadable, fetchRun } from '../../tools/web/web-fetch.mjs';
import { run as scrapeLow } from '../../tools/web/scrape-low.mjs';
import { run as scrapeMid } from '../../tools/web/scrape-mid.mjs';
import { run as scrapeHigh } from '../../tools/web/scrape-high.mjs';

const DDG_HTML = `
<html><body>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">First <b>Result</b></a>
<div class="result__snippet">Snippet one here.</div>
<a class="result__a" href="https://example.com/b">Second Result</a>
</body></html>`;

const GNEWS_XML = `
<rss><channel>
<item><title>Big News</title><link>https://news.example/x</link>
<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
<source url="https://s.example">ExampleSRC</source>
<description><p>Desc <b>bold</b> text.</p></description></item>
</channel></rss>`;

test('normalizeUrl strips trackers and lowercases', () => {
  assert.equal(
    normalizeUrl('https://Example.COM/Path/?utm_source=x&fbclid=y&q=1'),
    'https://example.com/Path?q=1'
  );
  assert.equal(normalizeUrl('https://example.com/a/'), 'https://example.com/a');
});

test('truncateHeadTail keeps both ends under budget', () => {
  const { text, truncated } = truncateHeadTail('a'.repeat(5000), 1000);
  assert.equal(truncated, true);
  assert.ok(text.length < 1200 && text.includes('truncated'));
  assert.deepEqual(truncateHeadTail('short', 1000), { text: 'short', truncated: false });
});

test('cache keys are deterministic; ttl cache expires', async () => {
  assert.equal(cacheKey('k', { a: 1, b: 2 }), cacheKey('k', { b: 2, a: 1 }));
  assert.notEqual(cacheKey('k', { a: 1 }), cacheKey('k', { a: 2 }));
  const c = new TtlCache(300);
  assert.deepEqual(c.get('x'), [null, false]);
  c.put('x', 'v');
  assert.deepEqual(c.get('x'), ['v', true]);
  const instant = new TtlCache(0);
  instant.put('x', 'v');
  assert.deepEqual(instant.get('x'), [null, false]);
});

test('isPublicIp refuses private, loopback and link-local', () => {
  for (const ip of ['127.0.0.1', '10.1.2.3', '172.16.0.1', '192.168.1.1', '169.254.1.1', '::1', 'fc00::1', 'fe80::1', 'nope']) {
    assert.equal(isPublicIp(ip), false, ip);
  }
  for (const ip of ['8.8.8.8', '1.1.1.1', '93.184.216.34', '2606:4700:4700::1111']) {
    assert.equal(isPublicIp(ip), true, ip);
  }
});

test('entity decoding covers named entities and never double-decodes', () => {
  assert.equal(decodeEntities('a&nbsp;b'), 'a b');
  assert.equal(decodeEntities('x&mdash;y'), 'x\u2014y');
  assert.equal(decodeEntities('&#8212;'), '\u2014');
  assert.equal(decodeEntities('&#x2014;'), '\u2014');
  assert.equal(decodeEntities('&amp;lt;'), '&lt;');
  assert.equal(decodeEntities('&unknownthing;'), '&unknownthing;');
  assert.equal(decodeEntities('Tom &amp; Jerry'), 'Tom & Jerry');
});

test('rss descriptions with escaped markup yield clean snippets', () => {
  const xml = `<rss><channel><item><title>T</title><link>https://e.com/1</link>
  <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><source>S</source>
  <description>&lt;a href="https://e.com/1"&gt;Headline here&lt;/a&gt;&amp;nbsp;CNN</description>
  </item></channel></rss>`;
  const results = parseGnewsXml(xml, 5);
  assert.equal(results.length, 1);
  assert.doesNotMatch(results[0].snippet, /&lt;a|&nbsp;|<a href/i);
  assert.match(results[0].snippet, /Headline here/);
});

test('checkUrlPublic fails closed with stubbed DNS', async () => {
  assert.match(await checkUrlPublic('http://localhost:3000/x'), /loopback/);
  assert.match(await checkUrlPublic('not a url'), /unparseable|missing/);
  assert.match(await checkUrlPublic('https://example.com', async () => { throw new Error('dns'); }), /DNS does not resolve/);
  assert.match(await checkUrlPublic('https://example.com', async () => ['10.0.0.5']), /non-public/);
  assert.equal(await checkUrlPublic('https://example.com', async () => ['93.184.216.34']), '');
});

test('ddg parser decodes uddg links and spots captchas', () => {
  const { results, blocked } = parseDdgHtml(DDG_HTML, 10);
  assert.equal(blocked, false);
  assert.equal(results.length, 2);
  assert.equal(results[0].url, 'https://example.com/a');
  assert.equal(results[0].title, 'First Result');
  assert.equal(results[0].snippet, 'Snippet one here.');
  assert.equal(parseDdgHtml('anomaly-modal challenge', 10).blocked, true);
});

test('search honors kill-switch, validates input, and fuses stubbed backends', async (t) => {
  assert.match(await searchRun({ query: '' }, {}), /'query' is required/);
  t.after(() => delete process.env.ANKITA_NO_WEB);
  process.env.ANKITA_NO_WEB = '1';
  assert.match(await searchRun({ query: 'x' }, {}), /disabled/);
  delete process.env.ANKITA_NO_WEB;

  const stub = async (url) => ({
    status: 200,
    headers: new Map(),
    text: url.includes('duckduckgo') ? DDG_HTML : '{"query":{"search":[]}}',
  });
  const out = await searchRun({ query: 'test', backend: 'web', limit: 5 }, {}, stub);
  assert.match(out, /First Result/);
  assert.match(out, /example\.com\/a/);
});

test('ctx config overrides env for timeouts (camelCase wiring)', async () => {
  let seen = null;
  const stub = async (url, opts) => {
    seen = opts;
    return { status: 200, headers: new Map(), text: DDG_HTML };
  };
  await searchRun({ query: 't', backend: 'web', limit: 1 }, { config: { webTimeout: 5 } }, stub);
  assert.equal(seen.timeoutMs, 5000);
});

test('readability extraction drops chrome and keeps structure', () => {
  const html = `<html><head><title>T</title><style>.x{}</style></head><body>
    <nav>menu</nav><h1>Head</h1><p>Para <b>bold</b> &amp; more.</p>
    <script>evil()</script><footer>foot</footer></body></html>`;
  const text = extractReadable(html);
  assert.match(text, /Head/);
  assert.match(text, /Para bold & more\./);
  assert.doesNotMatch(text, /menu|evil|foot|\.x\{/);
});

test('doctype, comments and CDATA never leak into readable text', () => {
  const html = `<!DOCTYPE html><!-- a comment --><html><head><?xml version="1.0"?></head>
    <body><![CDATA[raw stuff]]><p>Real content here.</p></body></html>`;
  const text = extractReadable(html);
  assert.match(text, /Real content here\./);
  assert.doesNotMatch(text, /doctype|comment|CDATA|xml version/i);
});

test('a JS shell with no article text returns empty so callers can fall back', () => {
  const shell = `<!doctype html><html><head><script>window.x=1</script></head><body><div id="root"></div></body></html>`;
  assert.equal(extractReadable(shell), '');
  assert.equal(extractReadable(''), '');
});

test('web fetch validates, refuses private hosts, and uses jina when thin', async () => {
  assert.match(await fetchRun({ url: 'notaurl' }, {}), /must start with http/);
  assert.match(
    await fetchRun({ url: 'http://localhost:9/' }, {}, async () => { throw new Error('must not fetch'); }),
    /loopback/
  );
  const thin = async (url) => ({
    status: 200,
    headers: { get: () => 'text/html' },
    text: url.startsWith('https://r.jina.ai/') ? 'Jina rendered the whole article text here.' : '<html><body><p>Hi</p></body></html>',
  });
  assert.match(await fetchRun({ url: 'https://example.com/a' }, {}, thin), /Jina rendered/);
  const fat = async () => ({
    status: 200,
    headers: { get: () => 'text/html' },
    text: `<html><body>${'<p>Long paragraph content.</p>'.repeat(100)}</body></html>`,
  });
  assert.match(await fetchRun({ url: 'https://example.com/b' }, {}, fat), /Long paragraph/);
  const bad = async () => ({ status: 404, headers: { get: () => '' }, text: '' });
  assert.match(await fetchRun({ url: 'https://example.com/c' }, {}, bad), /http 404/);
});

test('no_cache bypasses the fetch cache so watches see the current value', async () => {
  let calls = 0;
  const http = async () => {
    calls++;
    return {
      status: 200,
      headers: { get: () => 'text/plain' },
      // Over 600 chars, or the thin-page reader fallback fires a second request.
      text: `value ${calls} ${'x'.repeat(700)}`,
    };
  };
  const url = 'https://example.com/cache-probe'; // must resolve: the SSRF guard runs first

  const first = await fetchRun({ url, no_cache: true }, {}, http);
  const second = await fetchRun({ url, no_cache: true }, {}, http);
  assert.equal(calls, 2, 'no_cache must hit the network every time');
  assert.notEqual(first, second, 'and must not serve a stale body');

  const warm = await fetchRun({ url }, {}, http);
  assert.equal(calls, 3, 'a normal fetch goes to the network once');
  const cached = await fetchRun({ url }, {}, http);
  assert.equal(calls, 3, 'and the second is served from cache');
  assert.equal(cached, warm + '\n(cached)');
});

test('fitJson always parses and always fits', () => {
  const blob = [{ a: 'x'.repeat(5000), b: 'y'.repeat(5000) }];
  const out = JSON.parse(fitJson(blob, 1000));
  assert.ok(JSON.stringify(out).length <= 1000);
  assert.deepEqual(JSON.parse(fitJson([{ a: 1 }], 1000)), [{ a: 1 }]);
});

test('stealth escalation triggers on blocks and thin bodies only', () => {
  assert.equal(needsStealthResult(null), true);
  assert.equal(needsStealthResult({ status: 403, text: 'x'.repeat(1000) }), true);
  assert.equal(needsStealthResult({ status: 200, text: 'short' }), true);
  assert.equal(needsStealthResult({ status: 200, text: 'x'.repeat(1000) }), false);
  const thin = { status: 200, text: 'short', fields: { title: ['Example Domain'] } };
  assert.equal(needsStealthResult(thin, true), false);
  const empty = { status: 200, text: 'short', fields: { title: [] } };
  assert.equal(needsStealthResult(empty, true), true);
});

test('scrape tiers validate input and honor the kill-switch without network', async (t) => {
  assert.match(await scrapeLow({ url: 'notaurl' }, {}), /must start with http/);
  assert.match(await scrapeMid({ url: 'https://example.com', mode: 'nope' }, {}), /'mode' must be/);
  assert.match(await scrapeMid({ url: 'https://example.com', format: 'xml' }, {}), /'format' must be/);
  assert.match(await scrapeHigh({ urls: '' }, {}), /one or more/);
  assert.match(await scrapeHigh({ urls: 'https://example.com', depth: 'xx' }, {}), /'depth' must be/);
  t.after(() => delete process.env.ANKITA_NO_SCRAPE);
  process.env.ANKITA_NO_SCRAPE = '1';
  assert.match(await scrapeLow({ url: 'https://example.com' }, {}), /disabled/);
  assert.match(await scrapeHigh({ urls: 'https://example.com' }, {}), /disabled/);
  delete process.env.ANKITA_NO_SCRAPE;
});

const bridge = await runBridge({ cmd: 'check' }, { timeoutMs: 30000 });

test('scrape bridge is reachable and reports scrapling', { skip: !bridge.ok }, () => {
  assert.match(String(bridge.scrapling), /\d+\.\d+/);
});

test('bridge static fetch returns readable markdown', { skip: !bridge.ok }, async () => {
  const out = await scrapeLow({ url: 'https://example.com', max_chars: 800 }, {});
  assert.match(out, /Example Domain/);
  assert.match(out, /low\/static/);
});
