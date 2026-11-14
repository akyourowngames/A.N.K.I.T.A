import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('reference workflows save at least 25% calls against individual actions with equal results and recovery', async () => {
  const url = new URL('../../scripts/bench/skill-workflows.mjs', import.meta.url);
  assert.ok(fs.existsSync(url), 'executable skill workflow benchmark exists');
  const { runSkillWorkflowBench } = await import(url.href);
  const report = await runSkillWorkflowBench();
  assert.equal(report.workloads.length, 4);
  assert.ok(report.workloads.every(item => item.equalOutcome));
  assert.ok(report.savingsPercent >= 25);
  assert.equal(report.workloads.find(item => item.name === 'mobile-recovery').duplicateWrites, 0);
  assert.ok(report.workloads.find(item => item.name === 'research').optimizedCalls >= report.workloads.find(item => item.name === 'research').baselineCalls, 'parallel fetches must not be counted as fewer calls');
  assert.equal(report.scope, 'scripted reference workflows; not model or physical-device performance');
});
