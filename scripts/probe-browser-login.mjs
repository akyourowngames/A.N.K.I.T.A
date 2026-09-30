import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PlaywrightBrowserAdapter } from '../tools/browser/playwright.mjs';
import { chromium } from 'playwright';

// Public-site diagnostics only: caller supplies URLs, disposable profile, no credentials.
const urls = process.argv.slice(2);
const OBSERVE_MS = 15_000; // Milliseconds: observe delayed public SPA rendering without submitting anything.
if (!urls.length) throw new Error('Supply public login URLs');
const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-login-probe-'));
const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
const ctx = { settings: { headless: true } };
try {
  for (const url of urls) {
    try {
      const responsesBeforeOpen = [];
      adapter.context?.on('response', response => { if (response.request().isNavigationRequest()) responsesBeforeOpen.push({ status: response.status(), url: response.url() }); });
      const result = await adapter.run({ action: 'open', url }, ctx);
      const page = adapter.page;
      const failures = [], errors = [], responses = [];
      page.on('requestfailed', request => failures.push({ type: request.resourceType(), host: new URL(request.url()).hostname, error: request.failure()?.errorText }));
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => { if (response.status() >= 400) responses.push({ status: response.status(), host: new URL(response.url()).hostname }); });
      const inspect = () => page.evaluate(() => ({ title: document.title, text: document.body?.innerText.slice(0, 250), forms: document.forms.length, passwords: document.querySelectorAll('input[type=password]').length, scripts: document.scripts.length, controls: [...document.querySelectorAll('input,button')].slice(0, 10).map(node => ({ tag: node.tagName, type: node.type, label: node.innerText || node.getAttribute('aria-label') || node.name, form: Boolean(node.form) })) }));
      console.log(JSON.stringify({ url, phase: 'opened', result, state: await inspect(), responsesBeforeOpen }));
      try { await adapter.prepareCredentials({ website: url }, ctx); console.log(JSON.stringify({ url, phase: 'prepare', accepted: true, formDetection: false })); }
      catch (error) { console.log(JSON.stringify({ url, phase: 'prepare', accepted: false, error: error.message })); }
      await page.waitForFunction(() => document.body?.innerText.trim().length > 0, null, { timeout: OBSERVE_MS }).catch(() => {});
      console.log(JSON.stringify({ url, phase: 'observed', state: await inspect(), failures, errors, responses }));
      await page.screenshot({ path: path.join(directory, `site-${urls.indexOf(url)}.png`) });
    } catch (error) { console.log(JSON.stringify({ url, error: error.message })); }
  }
} finally { await adapter.close(); }
for (const url of urls.filter(value => new URL(value).hostname === 'x.com')) {
  for (const headless of [true, false]) {
    const context = await chromium.launchPersistentContext(path.join(directory, `direct-${headless}`), { headless, viewport: { width: 1280, height: 800 } });
    try {
      const page = context.pages()[0];
      const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: OBSERVE_MS });
      await page.waitForFunction(() => document.body?.innerText.trim().length > 0, null, { timeout: OBSERVE_MS }).catch(() => {});
      console.log(JSON.stringify({ url, phase: 'direct', headless, status: response?.status(), length: (await response?.body())?.length, text: (await page.locator('body').innerText()).slice(0, 500), scripts: await page.locator('script').count() }));
    } catch (error) { console.log(JSON.stringify({ url, headless, error: error.message })); }
    finally { await context.close(); }
  }
}
console.log(`LOGIN_PROBE_ARTIFACTS=${directory}`);
