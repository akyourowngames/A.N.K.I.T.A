import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { chromium } from 'playwright';

test('explicit browser capture prefers the real visible selection and keeps private controls out', async t => {
  const browser = await chromium.launch({ headless: true }); t.after(() => browser.close());
  const page = await browser.newPage();
  await page.setContent('<main><p id="chosen">The selected public paragraph.</p><p>Unselected page content.</p><input id="secret" type="password" value="private value"><span hidden>Hidden text.</span></main>');
  const source = await fs.readFile(new URL('../../desktop/browser-helper/context-extraction.mjs', import.meta.url), 'utf8').catch(() => '');
  assert.ok(source, 'shared context extraction is implemented');
  // Serve the shared pure module with its real protocol import, without an extension runtime.
  const protocol = await fs.readFile(new URL('../../desktop/browser-helper/protocol.mjs', import.meta.url), 'utf8');
  const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(source.replace("'./protocol.mjs'", JSON.stringify('data:text/javascript;base64,' + Buffer.from(protocol).toString('base64')))).toString('base64');
  const selection = await page.evaluate(async url => {
    const module = await import(url), node = document.getElementById('chosen'), range = document.createRange();
    range.selectNodeContents(node); getSelection().removeAllRanges(); getSelection().addRange(range);
    return module.extractContext(document);
  }, moduleUrl);
  assert.equal(selection.scope, 'selection'); assert.equal(selection.text, 'The selected public paragraph.');
  const fallback = await page.evaluate(async url => { getSelection().removeAllRanges(); return (await import(url)).extractContext(document); }, moduleUrl);
  assert.equal(fallback.scope, 'page'); assert.match(fallback.text, /Unselected page content/); assert.doesNotMatch(fallback.text, /private value|Hidden text/);
});
