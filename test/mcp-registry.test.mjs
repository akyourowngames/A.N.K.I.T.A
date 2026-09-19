import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Before anything that reads config.mjs. Without this the store tests below
// operate on the user's real ~/.copilot-chat-cli and delete their servers.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-registry-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const {
  compareVersions,
  collapseToLatest,
  commandFor,
  describeCandidate,
  resolveServer,
  searchRegistry,
  shortName,
  isLatest,
} = await import('../src/mcp-registry.mjs');

/* Fixtures copied from real registry responses, including the awkward ones. */

const microsoft = (version = '0.0.72', latest = false) => ({
  server: {
    name: 'io.github.microsoft/playwright-mcp',
    description: 'Playwright Tools for MCP',
    repository: { url: 'https://github.com/microsoft/playwright-mcp', source: 'github' },
    version,
    packages: [
      { registryType: 'npm', identifier: '@playwright/mcp', version, transport: { type: 'stdio' } },
    ],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: latest } },
});

// Has runtimeHint, runtimeArguments and a pile of environment variables.
const stealth = (version = '0.2.3', latest = true) => ({
  server: {
    name: 'com.pulsemcp/playwright-stealth',
    description: 'Browser automation using Playwright with optional stealth mode.',
    repository: { url: 'https://github.com/pulsemcp/mcp-servers', source: 'github' },
    version,
    packages: [
      {
        registryType: 'npm',
        identifier: 'playwright-stealth-mcp-server',
        version,
        runtimeHint: 'npx',
        transport: { type: 'stdio' },
        runtimeArguments: [{ value: '-y', type: 'positional' }],
        environmentVariables: [
          { name: 'STEALTH_MODE', description: 'Enable stealth.', default: 'false' },
          { name: 'PROXY_PASSWORD', description: 'Proxy password.', isSecret: true, isRequired: true },
        ],
      },
    ],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: latest } },
});

// Remote-only: no packages at all.
const remoteOnly = {
  server: {
    name: 'com.clauxel/playwrightselectorguard-mcp',
    description: 'Playwright selector risk checks.',
    version: '1.0.0',
    remotes: [{ type: 'streamable-http', url: 'https://example.com/mcp' }],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: true } },
};

// npm AND oci, like a real registry entry.
const dualPackage = {
  server: {
    name: 'io.github.dinesh-nalla-se/playwright-mcp',
    description: 'Playwright Tools for MCP',
    version: '1.0.0',
    packages: [
      { registryType: 'npm', identifier: '@dinesh-nalla-se/playwright-mcp', version: '0.0.47', transport: { type: 'stdio' } },
      { registryType: 'oci', identifier: 'docker.io/dx/playwright-mcp:1.0.0', transport: { type: 'stdio' } },
    ],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: true } },
};

const pypiServer = {
  server: {
    name: 'io.github.modelcontextprotocol/time',
    description: 'Time and timezone conversion.',
    version: '0.6.2',
    packages: [{ registryType: 'pypi', identifier: 'mcp-server-time', version: '0.6.2' }],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: true } },
};

/* ------------------------------ version math ---------------------------- */

test('versions compare numerically, not as strings', () => {
  assert.ok(compareVersions('0.0.9', '0.0.10') < 0, '9 is below 10');
  assert.ok(compareVersions('1.10.0', '1.9.0') > 0);
  assert.equal(compareVersions('0.2.3', '0.2.3'), 0);
  assert.equal(compareVersions('1.0', '1.0.0'), 0, 'missing segments are zero');
});

test('a search result collapses to one entry per server', () => {
  const page = [
    stealth('0.2.2', false),
    stealth('0.2.3', true),
    microsoft('0.0.72', false),
    { ...microsoft('0.0.99', false), _meta: { 'io.modelcontextprotocol.registry/official': { status: 'deleted', isLatest: false } } },
  ];
  const latest = collapseToLatest(page);
  assert.equal(latest.length, 2, 'one row per server, not per version');
  const names = latest.map((e) => e.server.name).sort();
  assert.deepEqual(names, ['com.pulsemcp/playwright-stealth', 'io.github.microsoft/playwright-mcp']);
  assert.equal(latest.find((e) => e.server.name === 'com.pulsemcp/playwright-stealth').server.version, '0.2.3');
  assert.equal(latest.find((e) => e.server.name === 'io.github.microsoft/playwright-mcp').server.version, '0.0.72');
});

test('without a latest flag the highest version wins', () => {
  const picked = collapseToLatest([stealth('0.2.3', false), stealth('0.2.10', false), stealth('0.2.2', false)]);
  assert.equal(picked.length, 1);
  assert.equal(picked[0].server.version, '0.2.10');
});

/* --------------------------- building commands -------------------------- */

test('an npm package becomes a pinned npx command', () => {
  const info = commandFor(microsoft());
  assert.equal(info.error, undefined);
  assert.equal(info.command, 'npx');
  assert.deepEqual(info.args, ['@playwright/mcp@0.0.72']);
  assert.equal(info.registryName, 'io.github.microsoft/playwright-mcp');
  assert.equal(info.version, '0.0.72');
});

test('runtimeArguments land before the package and are pinned with it', () => {
  const info = commandFor(stealth());
  assert.deepEqual(info.args, ['-y', 'playwright-stealth-mcp-server@0.2.3']);
  assert.equal(info.env.find((e) => e.name === 'PROXY_PASSWORD').required, true);
  assert.equal(info.env.find((e) => e.name === 'PROXY_PASSWORD').secret, true);
  assert.equal(info.env.find((e) => e.name === 'STEALTH_MODE').required, false);
});

test('a pypi package becomes uvx with a PEP 508 pin', () => {
  const info = commandFor(pypiServer);
  assert.equal(info.command, 'uvx');
  assert.deepEqual(info.args, ['mcp-server-time==0.6.2']);
  assert.equal(info.runtime, 'pypi');
});

test('npm is preferred when a server publishes npm and oci', () => {
  const info = commandFor(dualPackage);
  assert.equal(info.command, 'npx');
  assert.deepEqual(info.args, ['@dinesh-nalla-se/playwright-mcp@0.0.47']);
});

test('the pinned version is the package version, not the server version', () => {
  // dualPackage advertises server 1.0.0 but its npm package is 0.0.47.
  assert.equal(commandFor(dualPackage).version, '0.0.47');
});

/* ------------------------- what must be refused ------------------------- */

test('a remote-only server is refused with the reason, not a broken command', () => {
  const info = commandFor(remoteOnly);
  assert.match(info.error, /remote streamable-http server/);
  assert.match(info.error, /only\s+launches stdio/);
});

test('a server that cannot name our executable cannot install', () => {
  // The registry payload must never choose the binary we run.
  const evil = stealth();
  evil.server.packages[0].runtimeHint = 'curl';
  assert.match(commandFor(evil).error, /asks for the "curl" runtime/);

  const piped = stealth();
  piped.server.packages[0].runtimeHint = 'sh -c';
  assert.match(commandFor(piped).error, /"sh -c" runtime/);
});

test('shell metacharacters in an identifier are refused', () => {
  for (const identifier of ['pkg; rm -rf /', 'pkg && curl evil.sh', 'pkg`whoami`', '$(id)', '--flag']) {
    const bad = stealth();
    bad.server.packages[0].identifier = identifier;
    const info = commandFor(bad);
    assert.ok(info.error, `refused: ${identifier}`);
  }
});

test('a non-pinned version is refused', () => {
  for (const version of ['^1.0.0', 'latest', '1.x', '*']) {
    const bad = stealth();
    bad.server.packages[0].version = version;
    assert.ok(commandFor(bad).error, `refused version ${version}`);
  }
});

test('an unknown package type is refused', () => {
  const nuget = {
    server: {
      name: 'io.github.x/nuget-thing',
      version: '1.0.0',
      packages: [{ registryType: 'nuget', identifier: 'Thing', version: '1.0.0' }],
    },
    _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: true } },
  };
  assert.match(commandFor(nuget).error, /only publishes nuget packages/);
});

/* ------------------------------ resolving ------------------------------- */

function stubFetch(pages) {
  const calls = [];
  const impl = async (url) => {
    calls.push(String(url));
    const body = pages[Math.min(calls.length - 1, pages.length - 1)];
    return { ok: true, status: 200, statusText: 'OK', json: async () => body };
  };
  impl.calls = calls;
  return impl;
}

test('search sets the query and follows the cursor', async () => {
  const impl = stubFetch([
    { servers: [stealth('0.2.2', false)], metadata: { nextCursor: 'page2' } },
    { servers: [stealth('0.2.3', true)], metadata: {} },
  ]);
  const found = await searchRegistry('playwright', { fetchImpl: impl });
  assert.equal(found.length, 2, 'both pages were read');
  assert.equal(impl.calls.length, 2);
  assert.match(impl.calls[0], /search=playwright/);
  assert.match(impl.calls[1], /cursor=page2/);
});

test('resolving picks the latest even when it is on a later page', async () => {
  // Real searches paginate, and the newest version is not always first.
  const impl = stubFetch([
    { servers: [microsoft('0.0.72', false)], metadata: { nextCursor: 'more' } },
    { servers: [microsoft('0.0.92', true)], metadata: {} },
  ]);
  const info = await resolveServer('io.github.microsoft/playwright-mcp', { fetchImpl: impl });
  assert.equal(info.error, undefined);
  assert.deepEqual(info.args, ['@playwright/mcp@0.0.92'], 'took the latest, not the first page');
});

test('resolving an exact version honours it', async () => {
  const impl = stubFetch([{ servers: [microsoft('0.0.72', false), microsoft('0.0.92', true)], metadata: {} }]);
  const info = await resolveServer('io.github.microsoft/playwright-mcp', { version: '0.0.72', fetchImpl: impl });
  assert.equal(info.version, '0.0.72');
});

test('a name that is not in the registry says so and suggests near misses', async () => {
  const impl = stubFetch([{ servers: [stealth('0.2.3', true)], metadata: {} }]);
  const info = await resolveServer('io.github.microsoft/playwright', { fetchImpl: impl });
  assert.match(info.error, /no active registry server is named/);
  assert.match(info.error, /com.pulsemcp\/playwright-stealth/, 'offers what did match');
});

test('a non-exact name is never silently substituted', async () => {
  // "playwright-stealth" is a prefix-ish match for a real server, but not its
  // name. Installing the wrong server because it ranked first would be worse
  // than installing nothing.
  const impl = stubFetch([{ servers: [stealth('0.2.3', true)], metadata: {} }]);
  const info = await resolveServer('playwright-stealth', { fetchImpl: impl });
  assert.match(info.error, /no active registry server is named/);
});

test('a registry failure rejects rather than resolving to nothing', async () => {
  const impl = async () => ({ ok: false, status: 503, statusText: 'Service Unavailable', json: async () => ({}) });
  await assert.rejects(() => searchRegistry('x', { fetchImpl: impl }), /returned 503/);
  // Must not resolve: a silent empty result would read as "no such server".
  await assert.rejects(
    () => resolveServer('io.github.microsoft/playwright-mcp', { fetchImpl: impl }),
    /returned 503/
  );
});

test('an outage reaches the user as a sentence, not a stack trace', async () => {
  const manage = await import('../tools/mcp-manage.mjs');
  const impl = async () => ({ ok: false, status: 503, statusText: 'Service Unavailable', json: async () => ({}) });

  const searched = await manage.run({ action: 'search', query: 'playwright' }, { fetchImpl: impl });
  assert.match(searched, /^Error: could not reach the MCP registry:/);

  const installed = await manage.run(
    { action: 'install', server: 'io.github.microsoft/playwright-mcp' },
    { fetchImpl: impl }
  );
  assert.match(installed, /^Error: could not reach the MCP registry:/);
});

test('install records the server and refuses to run it', async () => {
  const manage = await import('../tools/mcp-manage.mjs');
  const { McpStore } = await import('../src/mcp-store.mjs');
  const { MCP_FILE } = await import('../src/config.mjs');

  const store = new McpStore(MCP_FILE).load();
  for (const s of [...store.servers]) store.remove(s.id);

  const impl = stubFetch([{ servers: [microsoft('0.0.92', true)], metadata: {} }]);
  const out = await manage.run(
    { action: 'install', server: 'io.github.microsoft/playwright-mcp' },
    { fetchImpl: impl }
  );
  assert.match(out, /Installed "playwright-mcp" from io\.github\.microsoft\/playwright-mcp @ 0\.0\.92/);
  assert.match(out, /command: npx @playwright\/mcp@0\.0\.92/);
  assert.match(out, /has NOT been started/, 'installing must not start anything');

  const record = new McpStore(MCP_FILE).load().find('playwright-mcp');
  assert.ok(record, 'it is in the store');
  assert.equal(record.approvedAt, null, 'and it is unapproved');
  assert.equal(record.source.registryName, 'io.github.microsoft/playwright-mcp');
  assert.equal(record.source.version, '0.0.92', 'provenance is kept for later upgrades');

  // The approval hash has to be over what would actually run.
  const { commandHash } = await import('../src/mcp-store.mjs');
  assert.equal(record.commandHash, commandHash('npx', ['@playwright/mcp@0.0.92']));

  for (const s of [...new McpStore(MCP_FILE).load().servers]) new McpStore(MCP_FILE).load().remove(s.id);
});

/* ------------------------------- display -------------------------------- */

test('a candidate line carries what a user needs to say yes', () => {
  const { line, usable } = describeCandidate(stealth());
  assert.equal(usable, true);
  assert.match(line, /com\.pulsemcp\/playwright-stealth \(v0\.2\.3\)/);
  assert.match(line, /command: npx -y playwright-stealth-mcp-server@0\.2\.3/);
  assert.match(line, /needs env: PROXY_PASSWORD/);
});

test('an unusable candidate says why instead of showing a command', () => {
  const { usable, line } = describeCandidate(remoteOnly);
  assert.equal(usable, false);
  assert.match(line, /remote/);
  assert.doesNotMatch(line, /command:/);
});

test('shortName is the last path segment', () => {
  assert.equal(shortName('io.github.microsoft/playwright-mcp'), 'playwright-mcp');
  assert.equal(shortName('bare-name'), 'bare-name');
  assert.equal(shortName(''), 'mcp-server');
});
