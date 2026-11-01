import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadConfig } from '../../src/core/config.mjs';
import { ChannelRegistry, defaultRegistry, environmentForConfig } from '../../src/channels/core/registry.mjs';

test('configuration discovers new channel env fields from a registered descriptor', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'channel-env-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, '.env'), globalEnvFile = path.join(root, 'global.env');
  fs.writeFileSync(file, 'FIXTURE_CHANNEL_SECRET=private-test-value\nTELEGRAM_CHAT_ID=42\nTELEGRAM_CONFIRM_TIMEOUT=120\n');
  const registry = new ChannelRegistry([...defaultRegistry.list(), { id: 'fixture', label: 'Fixture', capabilities: [], required: ['secret'], fields: { secret: { kind: 'secret', env: 'FIXTURE_CHANNEL_SECRET', default: '' } } }]);
  const config = loadConfig(file, { globalEnvFile, channelRegistry: registry });
  assert.equal(config.channels.fixture.secret, 'private-test-value');
  assert.equal(config.telegramChatId, '42');
  assert.equal(config.telegramAllowedChatIds, '42');
  assert.equal(config.telegramConfirmTimeout, 120);
});

test('invalid channel env settings fail closed with a diagnostic instead of breaking unrelated startup', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'channel-env-bad-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, '.env');
  fs.writeFileSync(file, 'TELEGRAM_CONFIRM_TIMEOUT=invalid\n');
  const config = loadConfig(file, { globalEnvFile: path.join(root, 'missing') });
  assert.equal(config.channels.telegram.enabled, false);
  assert.equal(config.telegramConfirmTimeout, 300);
  assert.equal(config.channelErrors.some(error => error.channel === 'telegram' && error.field === 'confirmTimeout'), true);
});

test('channel environment accepts configuration that has not loaded yet', () => {
  for (const config of [null, undefined]) {
    const env = environmentForConfig(config);
    assert.equal(env('TELEGRAM_BOT_TOKEN'), undefined);
    assert.equal(env('SLACK_BOT_TOKEN'), undefined);
  }
});

test('channel environment reads late-loaded settings and later provider changes without rebuilding the store', () => {
  let config = null;
  const env = environmentForConfig(() => config);
  assert.equal(env('TELEGRAM_BOT_TOKEN'), undefined);
  config = { telegramBotToken: 'legacy-fixture', channels: { slack: { botToken: 'loaded-fixture' } } };
  assert.equal(env('TELEGRAM_BOT_TOKEN'), 'legacy-fixture'); assert.equal(env('SLACK_BOT_TOKEN'), 'loaded-fixture');
  config = { channels: { telegram: { token: '' }, slack: { botToken: 'updated-fixture' } }, telegramBotToken: 'legacy-fixture' };
  assert.equal(env('TELEGRAM_BOT_TOKEN'), ''); assert.equal(env('SLACK_BOT_TOKEN'), 'updated-fixture');
});
