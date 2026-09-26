import { processIdentity, processTable, execute } from './_process.mjs';
import { spawn } from 'node:child_process';

// Milliseconds: bound taskkill itself before checking tracked descendants.
const TREE_TERMINATION_TIMEOUT_MS = 5000;
const TRACKED_DESCENDANT_TIMEOUT_MS = 10000; // Milliseconds: retain the existing per-descendant taskkill budget.
const WINDOWS_TREE_KILL_COMMAND = 'taskkill'; // Runtime Windows executable discovery remains on PATH.
const treeKillArgs = pid => ['/PID', String(pid), '/T', '/F']; // taskkill protocol: force the named process and its tree.
const ROOT_IDENTITY_CHANGED_ERROR = 'Refusing cleanup: the root PID identity changed.';

/** Terminate descendants before their parent; every POSIX command owns a group. */
export async function killTree(child) {
  if (child?.terminateTree) return child.terminateTree();
  if (!child?.pid) return;
  if (process.platform === 'win32') {
    if (child.exitCode !== null || child.signalCode !== null) {
      await terminateTrackedDescendants(child);
      return;
    }
    const killedTree = await new Promise(resolve => {
      const killer = spawn(WINDOWS_TREE_KILL_COMMAND, treeKillArgs(child.pid), { windowsHide: true, stdio: 'ignore' });
      const timer = setTimeout(() => { killer.kill(); resolve(false); }, TREE_TERMINATION_TIMEOUT_MS);
      const done = code => { clearTimeout(timer); resolve(code === 0); };
      killer.once('error', () => done(null));
      killer.once('close', done);
    });
    if (!killedTree) await terminateTrackedDescendants(child);
  } else { try { process.kill(-child.pid, 'SIGKILL'); } catch {} }
  try { child.kill('SIGKILL'); } catch {}
}

const tracked = new WeakMap();

/** Recover a dead launcher's tracked tree without trusting a potentially reused PID. */
export async function cleanupFailedLauncher(child, snapshot) {
  if (!snapshot?.identity || snapshot.pid !== child.pid) throw new Error('Cannot safely clean up launcher failure without the native process identity.');
  const entry = { ...snapshot };
  // A lost worker is the latest possible root-exit observation. Preserve any
  // earlier native exit bound so a reused PID cannot extend descendant search.
  entry.exitedAt = Math.min(entry.exitedAt, Date.now());
  tracked.set(child, entry);
  const root = (await processTable()).find(row => row.pid === child.pid);
  if (root) {
    if (root.identity !== entry.identity || root.name !== entry.name) throw new Error(ROOT_IDENTITY_CHANGED_ERROR);
    await killTree(child);
  } else await terminateTrackedDescendants(child);
}

const createdAt = identity => {
  const match = String(identity).match(/^\/Date\((\d+)/);
  return match ? Number(match[1]) : Date.parse(identity);
};

/** Capture the shell's creation identity while it is alive for safe later cleanup. */
export async function trackJobTree(child) {
  if (!child?.pid) return;
  let entry = tracked.get(child);
  if (!entry) {
    entry = { pid: child.pid, start: Date.now() - 10000, exitedAt: Infinity };
    tracked.set(child, entry);
    child.once('exit', () => { entry.exitedAt = Date.now() + 1000; });
  }
  try {
    const identity = await processIdentity(child.pid);
    entry.start = createdAt(identity.identity) || entry.start;
    entry.identity = identity.identity;
    entry.name = identity.name;
  } catch {} // The root may have exited before a lookup; PID and exit bound remain.
  return entry;
}

export async function trackedDescendants(child) {
  const entry = tracked.get(child) || { pid: child.pid, start: 0, exitedAt: Date.now() + 1000 };
  const rows = await processTable();
  const root = rows.find(row => row.pid === entry.pid);
  if (entry.identity && root && (root.identity !== entry.identity || root.name !== entry.name)) throw new Error(ROOT_IDENTITY_CHANGED_ERROR);
  const byParent = new Map();
  for (const row of rows) {
    if (!byParent.has(row.parent)) byParent.set(row.parent, []);
    byParent.get(row.parent).push(row);
  }
  const discovered = [];
  const walk = (parent, start, latest) => {
    for (const row of byParent.get(parent) || []) {
      const born = createdAt(row.identity);
      if (!Number.isFinite(born) || born < start || born > latest) continue;
      discovered.push(row);
      walk(row.pid, born, Infinity);
    }
  };
  walk(entry.pid, entry.start, entry.exitedAt);
  return discovered.reverse();
}

export async function terminateTrackedDescendants(child) {
  if (process.platform !== 'win32') return;
  for (const row of await trackedDescendants(child)) {
    try {
      const identity = await processIdentity(row.pid);
      if (identity.identity !== row.identity || identity.name !== row.name) continue;
      await execute(WINDOWS_TREE_KILL_COMMAND, treeKillArgs(row.pid), { timeout_ms: TRACKED_DESCENDANT_TIMEOUT_MS });
    } catch {} // A child that already exited needs no termination.
  }
}
