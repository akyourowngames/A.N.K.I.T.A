import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * Deprecation notice for the REST (API-key / broker) Composio path.
 *
 * The plan removes that code one minor version after deprecation, not in the
 * same release, so users get a full release to switch to OAuth. The removal
 * version is derived from package.json rather than written down here - a
 * hardcoded number would be wrong the moment the package version moves.
 */

function packageVersion() {
  try {
    const pkg = JSON.parse(readFileSync(fileURLToPath(new URL("../../package.json", import.meta.url)), "utf8"));
    return String(pkg.version || "").trim();
  } catch {
    return "";
  }
}

/** "2.4.4" -> "2.5.0". Returns null when the version is unusable. */
export function nextMinor(version) {
  const match = /^(\d+)\.(\d+)\.\d+/.exec(String(version || "").trim());
  return match ? `${match[1]}.${Number(match[2]) + 1}.0` : null;
}

export const CURRENT_VERSION = packageVersion();
export const DEPRECATION_REMOVAL_VERSION = nextMinor(CURRENT_VERSION);

/** The two REST modes that are going away. OAuth 'unavailable' has nothing to warn about. */
export const DEPRECATED_MODES = new Set(["direct", "broker"]);

/**
 * One line the user can act on, or null when there is nothing to say.
 * `mode` is the `connectionMode()` result.
 *
 * The wording deliberately does NOT tell the user to run `action=connect` to
 * escape: connect still goes through the REST `authorize()` path, which requires
 * the `ak_` project key. The keyless OAuth flow is the P1 build and is not
 * available here, so promising it would send users to a dead end.
 */
export function deprecationNotice(mode) {
  if (!DEPRECATED_MODES.has(String(mode))) return null;
  const label = mode === "direct" ? "COMPOSIO_API_KEY" : "COMPOSIO_BROKER_URL";
  const removal = DEPRECATION_REMOVAL_VERSION ? ` in v${DEPRECATION_REMOVAL_VERSION}` : " in the next minor release";
  return `${label} mode is deprecated and will be removed${removal}. Sign-in without a key is not available in this build yet, so keep your key until it ships.`;
}
