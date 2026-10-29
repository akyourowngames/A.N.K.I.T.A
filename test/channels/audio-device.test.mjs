import test from 'node:test';
import assert from 'node:assert/strict';
import { usePlaybackDevice } from '../../src/channels/audio-device.mjs';

function devices() {
  let selected = { console: 'original', multimedia: 'music-output', communications: 'call-output' };
  const changes = [];
  const io = { list: () => [{ flow: 'render', id: 'speakers', name: 'Fixture speakers' }],
    current: () => ({ ...selected }), set: patch => { changes.push(patch); selected = { ...selected, ...patch }; return true; } };
  return { io, changes, select: id => { selected = { console: id, multimedia: id, communications: id }; }, current: () => ({ ...selected }) };
}
test('explicit voice output accepts discovered render endpoints and restores once', () => {
  const h = devices(), route = usePlaybackDevice('speakers', h.io);
  assert.equal(h.current().console, 'speakers'); assert.equal(route.device.name, 'Fixture speakers');
  route.restore(); route.restore();
  assert.deepEqual(h.current(), { console: 'original', multimedia: 'music-output', communications: 'call-output' });
  assert.equal(h.changes.length, 2);
});
test('ending voice respects a speaker change made by the user during playback', () => {
  const h = devices(), route = usePlaybackDevice('speakers', h.io);
  h.select('user-choice'); route.restore();
  assert.equal(h.current().console, 'user-choice'); assert.equal(h.changes.length, 1);
});

test('a manual change to just the call output survives while other roles restore', () => {
  const h = devices(), route = usePlaybackDevice('speakers', h.io);
  h.io.set({ communications: 'new-call-output' }); route.restore();
  assert.deepEqual(h.current(), { console: 'original', multimedia: 'music-output', communications: 'new-call-output' });
});

test('a partially failed speaker switch rolls back only roles it changed', () => {
  const h = devices(), apply = h.io.set;
  let fail = true;
  h.io.set = patch => {
    if (fail) { fail = false; apply({ console: patch.console }); throw new Error('Switch failed'); }
    return apply(patch);
  };
  assert.throws(() => usePlaybackDevice('speakers', h.io), /Switch failed/);
  assert.deepEqual(h.current(), { console: 'original', multimedia: 'music-output', communications: 'call-output' });
});
test('an unavailable or rejected output fails before claiming a successful route', () => {
  const h = devices();
  assert.throws(() => usePlaybackDevice('unknown', h.io), /unavailable/);
  assert.deepEqual(h.changes, []);
  h.io.set = () => false;
  assert.throws(() => usePlaybackDevice('speakers', h.io), /unavailable/);
});

test('an already selected output needs no switch and an unplugged previous device does not break End voice', () => {
  const h = devices(); h.select('speakers');
  usePlaybackDevice('speakers', h.io).restore();
  assert.deepEqual(h.changes, []);
  h.select('original'); const route = usePlaybackDevice('speakers', h.io);
  h.io.set = () => { throw new Error('Previous speaker disconnected'); };
  assert.doesNotThrow(() => route.restore());
});
