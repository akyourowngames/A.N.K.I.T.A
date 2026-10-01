import test from 'node:test';
import assert from 'node:assert/strict';
import * as composioTool from '../../tools/connectors/composio.mjs';
import { deprecationNotice, nextMinor, DEPRECATION_REMOVAL_VERSION, CURRENT_VERSION } from '../../src/integrations/composio-deprecation.mjs';

test('the removal version is derived from package.json, never hardcoded', () => {
  assert.equal(nextMinor('2.4.4'), '2.5.0');
  assert.equal(nextMinor('1.9.0'), '1.10.0', 'the minor must carry, not roll the major');
  assert.equal(nextMinor('nonsense'), null);
  assert.match(CURRENT_VERSION, /^\d+\.\d+\.\d+$/);
  assert.equal(DEPRECATION_REMOVAL_VERSION, nextMinor(CURRENT_VERSION));
});

test('each deprecated REST mode names the exact variable to replace', () => {
  const direct = deprecationNotice('direct');
  assert.match(direct, /COMPOSIO_API_KEY/);
  assert.match(direct, /deprecated/);
  assert.ok(direct.includes(DEPRECATION_REMOVAL_VERSION), 'the user is told when it disappears');
  // The keyless OAuth flow is not built yet, so the notice must not send the
  // user to `action=connect`: that path still needs the ak_ project key.
  assert.equal(direct.includes('action=connect'), false, 'never promise a switch that does not exist yet');
  assert.match(direct, /keep your key/i);

  const broker = deprecationNotice('broker');
  assert.match(broker, /COMPOSIO_BROKER_URL/);
  assert.equal(broker.includes('COMPOSIO_API_KEY'), false);
});

test('nothing is announced when there is no REST mode to deprecate', () => {
  // 'unavailable' means no key and no broker, and OAuth (the target) is not
  // implemented yet, so it must not warn about anything.
  assert.equal(deprecationNotice('unavailable'), null);
  assert.equal(deprecationNotice(undefined), null);
  assert.equal(deprecationNotice('oauth'), null);
});

test('management stays auto-approvable but tier changes never are', () => {
  for (const action of ['status', 'list', 'accounts', 'search', 'connect', 'disconnect', 'reload', 'tiers']) {
    assert.equal(composioTool.needsApproval({ action }), false, `${action} is management`);
    assert.equal(composioTool.neverAutoApprove({ action }), false, `${action} may be auto-approved`);
  }
  for (const action of ['allow', 'always', 'deny']) {
    assert.equal(composioTool.needsApproval({ action }), true, `${action} must ask`);
    assert.equal(composioTool.neverAutoApprove({ action }), true, `${action} must never be auto-approved`);
  }
  assert.equal(composioTool.needsApproval({}), false, 'a missing action defaults to status');
});
