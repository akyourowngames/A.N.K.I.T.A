import test from 'node:test';
import assert from 'node:assert/strict';
import { LiveRenderer, renderMarkdown } from '../../src/core/markdown.mjs';
import { colorEnabled, setColorEnabled } from '../../src/core/ui.mjs';

// Keep these timer tests compatible with the project's Node 18 minimum.
function clock(t) {
  let now = 0;
  let nextId = 0;
  const pending = new Map();
  const originalTimeout = globalThis.setTimeout;
  const originalClear = globalThis.clearTimeout;
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextId;
    pending.set(id, { callback, due: now + delay });
    return id;
  };
  globalThis.clearTimeout = id => pending.delete(id);
  t.after(() => {
    globalThis.setTimeout = originalTimeout;
    globalThis.clearTimeout = originalClear;
  });
  return {
    pending,
    tick(ms) {
      now += ms;
      for (const [id, timer] of pending) {
        if (timer.due <= now) {
          pending.delete(id);
          timer.callback();
        }
      }
    },
  };
}

function terminal(t, tty = true) {
  for (const [key, value] of Object.entries({ isTTY: tty, rows: 40, columns: 80 })) {
    const descriptor = Object.getOwnPropertyDescriptor(process.stdout, key);
    Object.defineProperty(process.stdout, key, { configurable: true, value });
    t.after(() => {
      if (descriptor) Object.defineProperty(process.stdout, key, descriptor);
      else delete process.stdout[key];
    });
  }
  const originalColor = colorEnabled;
  setColorEnabled(false);
  t.after(() => setColorEnabled(originalColor));
  const frames = [];
  const renderer = new LiveRenderer({ write: frame => frames.push(frame), width: 80 });
  t.after(() => renderer.finish());
  return { renderer, frames };
}

test('TTY token bursts redraw once per frame with all accumulated text', t => {
  const timers = clock(t);
  const { renderer, frames } = terminal(t);
  renderer.push('Hello');
  timers.tick(10);
  for (const token of [' ', 'stream', 'ing', ' world']) renderer.push(token);
  assert.equal(frames.length, 0);
  timers.tick(9);
  assert.equal(frames.length, 0);
  timers.tick(1);
  assert.equal(frames.length, 1);
  assert.equal(frames[0], '\x1b[J  │ Hello streaming world\n');

  renderer.push('!');
  timers.tick(20);
  assert.equal(frames.length, 2);
  assert.equal(frames[1], '\x1b[1A\x1b[J  │ Hello streaming world!\n');
  timers.tick(100);
  assert.equal(frames.length, 2, 'idle renderers must not redraw');
});

test('finish flushes the last tokens immediately and closes pending redraws', t => {
  const timers = clock(t);
  const listenersBefore = process.stdout.listenerCount('resize');
  const { renderer, frames } = terminal(t);
  renderer.push('Partial');
  timers.tick(20);
  renderer.push(' answer.');
  assert.equal(renderer.finish(), 'Partial answer.');
  assert.equal(frames.at(-1), '\x1b[1A\x1b[J  │ Partial answer.\n');
  assert.equal(process.stdout.listenerCount('resize'), listenersBefore);
  assert.equal(timers.pending.size, 0, 'finish must cancel the scheduled frame');
  const closedFrames = frames.length;
  renderer.finish();
  renderer.push(' late token');
  renderer.onResize();
  renderer.draw();
  timers.tick(100);
  assert.equal(frames.length, closedFrames);
  assert.equal(renderer.buf, 'Partial answer.');
});

test('an interrupted stream can flush its partial text in finally', t => {
  const timers = clock(t);
  const { renderer, frames } = terminal(t);
  assert.throws(() => {
    try {
      renderer.push('Received before failure');
      throw new Error('stream failed');
    } finally {
      renderer.finish();
    }
  }, /stream failed/);
  assert.deepEqual(frames, ['\x1b[J  │ Received before failure\n']);
  timers.tick(100);
  assert.equal(frames.length, 1);
});

test('nonTTY output stays buffered until finish without scheduling redraws', t => {
  const timers = clock(t);
  const { renderer, frames } = terminal(t, false);
  renderer.push('Hello ');
  renderer.push('pipe.');
  timers.tick(100);
  assert.equal(timers.pending.size, 0);
  assert.deepEqual(frames, []);
  assert.equal(renderer.finish(), 'Hello pipe.');
  assert.deepEqual(frames, ['  │ Hello pipe.\n']);
});

test('language lookup Sets are reused across code lines, aliases, and redraws', t => {
  const originalColor = colorEnabled;
  setColorEnabled(true);
  t.after(() => setColorEnabled(originalColor));
  const originalSet = globalThis.Set;
  let allocations = 0;
  globalThis.Set = class extends originalSet {
    constructor(...args) {
      super(...args);
      allocations++;
    }
  };
  try {
    const code = '```javascript\nconst value = new Map();\nreturn value;\n```';
    const first = renderMarkdown(code);
    assert.match(first[1], /\x1b\[38;5;170mconst\x1b\[0m/);
    assert.match(first[1], /\x1b\[38;5;222mMap\x1b\[0m/);
    assert.ok(allocations <= 2, `one spec created ${allocations} lookup Sets`);
    const warmedAllocations = allocations;
    const alias = renderMarkdown(code.replace('javascript', 'js'));
    assert.equal(alias[1], first[1]);
    renderMarkdown('```js\n' + 'const value = new Map();\n'.repeat(100) + '```');
    assert.equal(allocations, warmedAllocations, 'additional lines/redraws must reuse lookup Sets');
  } finally {
    globalThis.Set = originalSet;
  }
});
