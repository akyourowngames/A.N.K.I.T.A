import test from 'node:test';
import assert from 'node:assert/strict';
import { IPC_CONTRACT, checkCompat } from '../desktop/shared/version.mjs';

const identity = (version, contract = IPC_CONTRACT) => ({ version, contract });

test('the contract version is a number the two halves can compare', () => {
  assert.equal(typeof IPC_CONTRACT, 'number');
});

test('matching version and contract is in sync', () => {
  const result = checkCompat(identity('2.1.1'), identity('2.1.1'));
  assert.equal(result.ok, true);
  assert.equal(result.code, 'ok');
});

test('a different contract is incompatible even if the versions match', () => {
  // The exact case that produced "Unknown desktop setting": a partial rebuild
  // where both halves report the same package.json version but their code differs.
  const result = checkCompat(identity('2.1.1', IPC_CONTRACT - 1), identity('2.1.1'));
  assert.equal(result.ok, false);
  assert.equal(result.code, 'contract');
  assert.match(result.detail, /Restart/);
});

test('an old main process that reports no contract is treated as a mismatch', () => {
  const result = checkCompat({ version: '2.0.0' }, identity('2.1.1'));
  assert.equal(result.ok, false);
  assert.equal(result.code, 'contract');
});

test('same contract but different versions is a version mismatch', () => {
  const result = checkCompat(identity('2.0.0'), identity('2.1.1'));
  assert.equal(result.ok, false);
  assert.equal(result.code, 'version');
  assert.equal(result.rendererVersion, '2.1.1');
  assert.equal(result.mainVersion, '2.0.0');
  assert.match(result.detail, /2\.1\.1/);
  assert.match(result.detail, /2\.0\.0/);
});
