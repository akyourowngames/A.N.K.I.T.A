import { COMPOSIO_FILE } from '../../src/config.mjs';
import { ComposioStore } from '../../src/composio-store.mjs';
import { authorize, canonicalSlug, connectedServices, connectionMode, listToolkits, removeAccount, removeService } from '../../src/composio.mjs';

const cleanText = (value, max = 200) => String(value || '').slice(0, max);

/** The desktop's small, secret-free boundary around Composio management. */
export class DesktopPlugins {
  constructor({ getConfig, storeFile = COMPOSIO_FILE, fetchImpl = fetch, isLive = () => false } = {}) {
    this.getConfig = getConfig;
    this.storeFile = storeFile;
    this.fetchImpl = fetchImpl;
    this.isLive = isLive;
  }

  context() { return { ...this.getConfig(), composioStore: new ComposioStore(this.storeFile).load() }; }

  requireConfigured() {
    const config = this.context();
    if (connectionMode(config) === 'unavailable') throw new Error('Add a Composio project key in Settings → Providers first');
    return config;
  }

  async overview() {
    const config = this.context();
    const mode = connectionMode(config);
    if (mode === 'unavailable') return { mode, live: false, services: {} };
    const raw = await connectedServices(config, this.fetchImpl);
    const services = {};
    for (const [name, value] of Object.entries(raw)) {
      let slug;
      try { slug = canonicalSlug(name); } catch { continue; }
      services[slug] = {
        connected: Boolean(value?.connected), pending: Boolean(value?.pending), status: cleanText(value?.status, 40),
        accounts: (Array.isArray(value?.accounts) ? value.accounts : []).slice(0, 30).map(account => ({
          id: cleanText(account?.id, 128), alias: cleanText(account?.alias, 64), status: cleanText(account?.status, 40),
        })).filter(account => account.id),
      };
    }
    return { mode, live: Boolean(this.isLive()), services };
  }

  async catalog({ query = '', cursor = '' } = {}) {
    const config = this.requireConfigured();
    if (typeof query !== 'string' || query.length > 100 || typeof cursor !== 'string' || cursor.length > 1000) throw new Error('Invalid plugin search');
    // Composio sorts by usage. Its API does not search on this route, so scan
    // consecutive pages until a search finds matches or the catalog ends.
    let next = cursor;
    const cards = [];
    for (let page = 0; page < (query ? 5 : 1); page++) {
      const result = await listToolkits(config, { query: query.trim(), cursor: next }, this.fetchImpl);
      for (const item of result.cards) {
        let slug;
        try { slug = canonicalSlug(item.slug); } catch { continue; }
        cards.push({ slug, label: cleanText(item.label || slug, 90), blurb: cleanText(item.blurb, 160), noAuth: Boolean(item.noAuth) });
      }
      next = typeof result.nextCursor === 'string' && result.nextCursor.length <= 1000 && result.nextCursor !== next ? result.nextCursor : '';
      if (cards.length || !next) break;
    }
    return { cards, nextCursor: next || null };
  }

  connect({ slug, alias } = {}) {
    return authorize(this.requireConfigured(), slug, alias, this.fetchImpl);
  }

  disconnectAccount({ slug, accountId } = {}) {
    return removeAccount(this.requireConfigured(), slug, accountId, this.fetchImpl);
  }

  disconnectService({ slug } = {}) {
    return removeService(this.requireConfigured(), slug, this.fetchImpl);
  }
}
