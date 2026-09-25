#!/usr/bin/env node
/**
 * A live dashboard to point watches at.
 *
 * Serves a small HTML page whose numbers move on their own:
 *   - Active users   random-walks up AND down (so a watch sees it increase and
 *                    decrease, not just climb)
 *   - Signups today  only ever increases
 *   - Error rate     fluctuates and occasionally spikes
 *
 * Usage:
 *   node scripts/demo/demo-dashboard.mjs [port]
 *
 * Then watch it (needs ALLOW_PRIVATE_HOSTS=1 in .env, because loopback is
 * blocked by default):
 *   ankita › watch http://127.0.0.1:4173 and grab "Active users: ([\d,]+)"
 */

import http from "node:http";

const PORT = Number(process.argv[2]) || 4173;
const TICK_MS = 3000;

const state = {
  activeUsers: 1204,
  signups: 87,
  errorRate: 0.4,
  peak: 1204,
  started: Date.now(),
  ticks: 0,
};

function step() {
  state.ticks++;

  // Random walk with a gentle pull toward the middle, so it wanders both ways.
  const drift = (1200 - state.activeUsers) * 0.02;
  const jump = Math.round((Math.random() - 0.48) * 40);
  state.activeUsers = Math.max(830, Math.min(1460, state.activeUsers + jump + Math.round(drift)));
  if (state.activeUsers > state.peak) state.peak = state.activeUsers;

  // Signups only ever go up.
  state.signups += Math.random() < 0.65 ? 1 + Math.floor(Math.random() * 3) : 0;

  // Occasionally something goes wrong.
  const spike = Math.random() < 0.12;
  state.errorRate = spike
    ? Math.round((1.5 + Math.random() * 3) * 100) / 100
    : Math.round((0.2 + Math.random() * 0.6) * 100) / 100;
}
setInterval(step, TICK_MS).unref();

const fmt = (n) => n.toLocaleString("en-US");

function page() {
  const uptime = Math.floor((Date.now() - state.started) / 1000);
  return `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>ankita demo dashboard</title></head>
<body>
  <h1>Service overview</h1>
  <p>Active users: ${fmt(state.activeUsers)}</p>
  <p>Signups today: ${fmt(state.signups)}</p>
  <p>Peak users today: ${fmt(state.peak)}</p>
  <p>Error rate: ${state.errorRate}%</p>
  <p>Uptime: ${uptime}s</p>
  <p>Ticks: ${state.ticks}</p>
  <p>Updated: ${new Date().toISOString()}</p>
</body>
</html>`;
}

const server = http.createServer((req, res) => {
  if (req.url.startsWith("/stats")) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(state, null, 2));
    return;
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
  res.end(page());
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`dashboard on http://127.0.0.1:${PORT}  (numbers move every ${TICK_MS / 1000}s)`);
  console.log(`active users start at ${fmt(state.activeUsers)}, signups at ${fmt(state.signups)}`);
});
