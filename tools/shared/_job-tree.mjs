import { processIdentity, processTable, execute } from './_process.mjs';

const tracked = new WeakMap();
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
  } catch {} // The root may have exited before a lookup; PID and exit bound remain.
  return entry;
}

export async function trackedDescendants(child) {
  const entry = tracked.get(child) || { pid: child.pid, start: 0, exitedAt: Date.now() + 1000 };
  const rows = await processTable();
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
      await execute('taskkill', ['/PID', String(row.pid), '/T', '/F'], { timeout_ms: 10000 });
    } catch {} // A child that already exited needs no termination.
  }
}
