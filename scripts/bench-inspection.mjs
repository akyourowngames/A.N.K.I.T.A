import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { run as search } from '../tools/search-files.mjs';
import { runFileToolInWorker } from '../src/tool-worker.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-inspection-bench-'));
try {
  for (let i = 0; i < 200; i++) fs.writeFileSync(path.join(root, `file-${i}.txt`), 'ordinary text\n'.repeat(1200));
  const args = { pattern: 'not-present-in-this-fixture', path: root };
  const ctx = { cwd: root };
  const modes = [
    ['synchronous', () => search(args, ctx)],
    ['worker', () => runFileToolInWorker('search_files', args, ctx)],
  ];
  for (const [, run] of modes) await run(); // Warm filesystem cache and worker startup.
  const samples = { synchronous: [], worker: [] };
  for (let round = 0; round < 3; round++) {
    for (const [label, run] of round % 2 ? modes.slice().reverse() : modes) {
      const due = performance.now() + 10;
      let lag;
      const timer = new Promise(resolve => setTimeout(() => { lag = Math.max(0, performance.now() - due); resolve(); }, 10));
      const started = performance.now();
      const cpu = process.cpuUsage();
      const result = await run();
      await timer;
      const used = process.cpuUsage(cpu);
      samples[label].push({ latency_ms: performance.now() - started, ui_timer_lag_ms: lag, cpu_ms: (used.user + used.system) / 1000, rss_mb: process.memoryUsage().rss / 1048576, files: 200, complete: !result.includes('inspection incomplete') });
    }
  }
  const median = values => Math.round(values.sort((a, b) => a - b)[1]);
  for (const [label] of modes) {
    const rows = samples[label];
    console.log(JSON.stringify({ mode: label, runs: rows.length, latency_ms: median(rows.map(row => row.latency_ms)), ui_timer_lag_ms: median(rows.map(row => row.ui_timer_lag_ms)), cpu_ms: median(rows.map(row => row.cpu_ms)), rss_mb: median(rows.map(row => row.rss_mb)), files: 200, complete: rows.every(row => row.complete) }));
  }
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
