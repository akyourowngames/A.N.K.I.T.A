/**
 * Client for the official MCP Registry (registry.modelcontextprotocol.io).
 *
 * The registry is the marketplace: it lists servers with structured package
 * metadata rather than a command string, which is the only reason it is safe
 * to automate. Everything here builds a command out of typed fields, and any
 * field that could steer the executable is validated or ignored.
 *
 * Nothing in this module runs a server. It produces a {command, args} the
 * store records and the approval gate later shows to the user verbatim.
 */
import { fetchWithRetry } from "../core/net.mjs";

export const REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers";

const TIMEOUT_MS = 15000;
const MAX_PAGES = 3;

/**
 * Runtimes we are willing to derive, keyed by the registry's registryType.
 * The executable is chosen from THIS table, never from the registry payload -
 * a server does not get to name the binary we run.
 */
const RUNNABLE = {
  npm: { runtime: "npx", spec: (id, version) => `${id}@${version}` },
  pypi: { runtime: "uvx", spec: (id, version) => `${id}==${version}` },
};

/** A runtimeHint we will accept for a given registryType, when one is given. */
const HINT_OK = { npm: "npx", pypi: "uvx" };

// Deliberately strict. No whitespace, no shell metacharacters, no leading dash.
const SAFE_IDENTIFIER = /^@?[A-Za-z0-9][A-Za-z0-9._/-]*$/;
// Digits and dots only, so a range like "1.x" or "^1.0.0" cannot pass as a pin.
// A prerelease/build tail is allowed because those are still exact versions.
const SAFE_VERSION = /^[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9.-]+)?$/;

function official(entry) {
  return entry?._meta?.["io.modelcontextprotocol.registry/official"] || {};
}

export function isLatest(entry) {
  return official(entry).isLatest === true;
}

export function isActive(entry) {
  const status = official(entry).status;
  return status === undefined || status === "active";
}

/** Numeric-segment version compare, tolerant of prerelease tails. */
export function compareVersions(a, b) {
  const parts = (v) => String(v ?? "").split(/[.+-]/).map((n) => parseInt(n, 10) || 0);
  const pa = parts(a);
  const pb = parts(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d;
  }
  return 0;
}

/**
 * One entry per server name: the one the registry flags as latest, or failing
 * that the highest version. A search returns every published version of every
 * match, so without this the same server fills the whole page.
 */
export function collapseToLatest(entries = []) {
  const byName = new Map();
  for (const entry of entries) {
    const name = entry?.server?.name;
    if (!name || !isActive(entry)) continue;
    const held = byName.get(name);
    if (!held) {
      byName.set(name, entry);
      continue;
    }
    const better =
      isLatest(entry) !== isLatest(held)
        ? isLatest(entry)
        : compareVersions(entry.server.version, held.server.version) > 0;
    if (better) byName.set(name, entry);
  }
  return [...byName.values()];
}

export async function searchRegistry(query, { limit = 50, pages = MAX_PAGES, signal, fetchImpl } = {}) {
  const doFetch = fetchImpl || fetchWithRetry;
  const seen = [];
  let cursor = null;

  for (let page = 0; page < pages; page++) {
    const url = new URL(REGISTRY_URL);
    url.searchParams.set("search", query);
    url.searchParams.set("limit", String(limit));
    if (cursor) url.searchParams.set("cursor", cursor);

    const res = await doFetch(url.toString(), {
      headers: { accept: "application/json" },
      // A review tool must never fire-and-forget, so cap it even if the
      // caller passed no signal of their own.
      signal: signal || AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`the MCP registry returned ${res.status} ${res.statusText}`);

    const data = await res.json();
    if (Array.isArray(data.servers)) seen.push(...data.servers);
    cursor = data?.metadata?.nextCursor;
    if (!cursor) break;
  }
  return seen;
}

function argList(list) {
  const out = [];
  for (const arg of Array.isArray(list) ? list : []) {
    if (!arg || typeof arg !== "object") continue;
    const value = arg.value === undefined || arg.value === null ? "" : String(arg.value);
    if (arg.type === "named") {
      const flag = String(arg.name || "");
      if (!SAFE_IDENTIFIER.test(flag.replace(/^-+/, ""))) continue;
      out.push(flag.startsWith("-") ? flag : `--${flag}`);
      if (value) out.push(value);
    } else if (value) {
      out.push(value);
    }
  }
  return out;
}

function packageFor(server) {
  const packages = Array.isArray(server?.packages) ? server.packages : [];
  const ranked = ["npm", "pypi"];
  for (const type of ranked) {
    const found = packages.find(
      (p) =>
        p?.registryType === type &&
        p.identifier &&
        p.version &&
        (!p.transport?.type || p.transport.type === "stdio")
    );
    if (found) return found;
  }
  return null;
}

/**
 * Turns a registry entry into the command ankita would run, or an explanation
 * of why it cannot. The version is always the pinned package version, never a
 * range - the approval hash depends on that being exact.
 */
export function commandFor(entry) {
  const server = entry?.server;
  const label = server?.name || "(unnamed)";
  if (!server) return { error: "the registry entry had no server object." };

  const pkg = packageFor(server);
  if (!pkg) {
    const remote = Array.isArray(server.remotes) && server.remotes.length ? server.remotes[0] : null;
    if (remote) {
      return {
        error:
          `"${label}" is offered as a remote ${remote.type || "http"} server, and ankita only ` +
          `launches stdio servers. It would need to run elsewhere and be pointed at by URL.`,
      };
    }
    const types = [...new Set((server.packages || []).map((p) => p?.registryType).filter(Boolean))];
    return {
      error: types.length
        ? `"${label}" only publishes ${types.join("/")} packages, and ankita can run npm or pypi.`
        : `"${label}" publishes no installable package.`,
    };
  }

  const spec = RUNNABLE[pkg.registryType];
  if (!spec) return { error: `"${label}" uses an unsupported package type.` };

  // When the registry states a runtime, it has to be the one we support for
  // that package type. This catches entries that want a different execution
  // model without us having to reason about it.
  if (pkg.runtimeHint && pkg.runtimeHint !== HINT_OK[pkg.registryType]) {
    return {
      error:
        `"${label}" asks for the "${pkg.runtimeHint}" runtime, and ankita drives ` +
        `npm packages with npx and pypi packages with uvx.`,
    };
  }

  if (!SAFE_IDENTIFIER.test(pkg.identifier)) {
    return { error: `"${label}" has a package identifier ankita will not pass to a runtime.` };
  }
  if (!SAFE_VERSION.test(pkg.version)) {
    return { error: `"${label}" is published at version "${pkg.version}", which is not a pinned version.` };
  }

  const args = [
    ...argList(pkg.runtimeArguments),
    spec.spec(pkg.identifier, pkg.version),
    ...argList(pkg.packageArguments),
  ];

  return {
    registryName: server.name,
    version: pkg.version,
    package: `${pkg.identifier}@${pkg.version}`,
    description: server.description || "",
    repository: server.repository?.url || "",
    runtime: pkg.registryType,
    command: spec.runtime,
    args,
    env: (Array.isArray(pkg.environmentVariables) ? pkg.environmentVariables : [])
      .filter((v) => v?.name)
      .map((v) => ({
        name: String(v.name),
        description: v.description || "",
        required: v.isRequired === true,
        secret: v.isSecret === true,
        hasDefault: v.default !== undefined,
      })),
  };
}

/** Resolves a registry name to an installable command, refusing ambiguity. */
export async function resolveServer(registryName, { version, signal, fetchImpl } = {}) {
  const wanted = String(registryName || "").trim();
  if (!wanted) return { error: "a registry name is required, e.g. io.github.microsoft/playwright-mcp." };

  const entries = await searchRegistry(wanted, { signal, fetchImpl });
  const named = entries.filter((e) => e?.server?.name === wanted && isActive(e));
  if (!named.length) {
    const near = collapseToLatest(entries)
      .slice(0, 5)
      .map((e) => e.server.name);
    return {
      error:
        `no active registry server is named "${wanted}".` +
        (near.length ? ` Close matches: ${near.join(", ")}` : ""),
    };
  }

  const entry = version
    ? named.find((e) => e.server.version === version)
    : named.find(isLatest) || named.sort((a, b) => compareVersions(b.server.version, a.server.version))[0];

  if (!entry) return { error: `"${wanted}" has no published version ${version}.` };
  return commandFor(entry);
}

/** The short handle to file an install under, e.g. .../playwright-mcp -> playwright-mcp. */
export function shortName(registryName) {
  return String(registryName || "").split("/").filter(Boolean).pop() || "mcp-server";
}

/** One candidate, rendered for a model to choose from. */
export function describeCandidate(entry) {
  const info = commandFor(entry);
  const server = entry.server;
  const meta = entry._meta?.["io.modelcontextprotocol.registry/publisher-provided"] || {};
  const title = meta.title || server.name;
  if (info.error) return { name: server.name, title, usable: false, line: `- ${server.name} - ${info.error}` };
  const envNote = info.env.filter((e) => e.required).map((e) => e.name);
  return {
    name: server.name,
    title,
    usable: true,
    version: info.version,
    line:
      `- ${server.name} (v${info.version})${meta.title ? ` - ${meta.title}` : ""}\n` +
      `    ${info.description.slice(0, 140)}\n` +
      `    command: ${info.command} ${info.args.join(" ")}` +
      (envNote.length ? `\n    needs env: ${envNote.join(", ")}` : ""),
  };
}
