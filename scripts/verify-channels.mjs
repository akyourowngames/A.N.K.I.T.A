import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../', import.meta.url)); // Resolve from this script, independent of the caller's directory or OS.
const TESTS = Object.freeze([
  'test/channels/telegram-adapter.test.mjs',
  'test/channels/discord.test.mjs',
  'test/channels/slack.test.mjs',
  'test/channels/transport-roundtrip.test.mjs',
]); // Local HTTP/native WebSocket servers and protocol fixtures; no account credentials or external sends.

const child = spawn(process.execPath, ['--test', '--test-concurrency=1', ...TESTS], { cwd: ROOT, stdio: 'inherit', windowsHide: true });
child.on('error', () => { console.error('Channel verification could not start the local Node runner.'); process.exitCode = 1; });
child.on('exit', code => {
  process.exitCode = code ?? 1;
  if (code === 0) console.log('CHANNEL_TRANSPORT_CHECKS_OK: local Telegram HTTP; native Discord/Slack sockets and HTTP; real account acceptance remains separate.');
});
