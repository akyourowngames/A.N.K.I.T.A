import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import { PlaywrightBrowserAdapter } from '../tools/browser/playwright.mjs';

// Read-only diagnostics: disposable profiles, URLs supplied by the caller, no clicks.
const urls = process.argv.slice(2).filter(value => /^https?:\/\//.test(value));
if (!urls.length) throw new Error('Supply at least one HTTP(S) URL to probe.');
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-navigation-probe-'));
const TIMEOUT_MS = 20_000; // Milliseconds: bound each public navigation attempt.
try {
  for (const url of urls) {
    for (const transport of ['adapter', 'http1', 'full-headless', 'headed']) {
      let close;
      try {
        if (transport === 'adapter') {
          const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, transport) });
          close = () => adapter.close();
          const receipt = await adapter.run({ action: 'open', url }, { settings: { headless: true } });
          console.log(JSON.stringify({ transport, url, opened: true, receipt: receipt.split('\n').slice(0, 2).join('\n') }));
        } else {
          const context = await chromium.launchPersistentContext(path.join(directory, transport), { headless: transport !== 'headed', ...(transport === 'full-headless' ? { channel: 'chromium' } : {}), args: transport === 'http1' ? ['--disable-http2'] : [] });
          close = () => context.close();
          const page = context.pages()[0];
          const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
          console.log(JSON.stringify({ transport, url, opened: true, status: response?.status(), title: await page.title() }));
        }
      } catch (error) { console.log(JSON.stringify({ transport, url, opened: false, error: error.message })); }
      finally { await close?.(); }
    }
  }
} finally { fs.rmSync(directory, { recursive: true, force: true }); }
