import test from 'node:test';
import assert from 'node:assert/strict';
import { voiceCommand, VOICE_WAKE_PHRASE, VOICE_PHASE_LABELS } from '../../desktop/shared/voice.mjs';

const awake = { listening: true };
const asleep = { listening: false };

test('standby is a real phase with its own label', () => {
  assert.equal(VOICE_PHASE_LABELS.standby, 'Say Ankita');
  assert.equal(VOICE_WAKE_PHRASE, 'ankita');
});

test('the wake word alone wakes from standby', () => {
  assert.deepEqual(voiceCommand('Ankita', asleep), { kind: 'wake', text: '' });
  assert.deepEqual(voiceCommand('Ankita!', asleep), { kind: 'wake', text: '' });
  assert.deepEqual(voiceCommand('  ankita.  ', asleep), { kind: 'wake', text: '' });
});

test('a wake word plus a request delegates only the remainder in the user’s own wording', () => {
  assert.deepEqual(voiceCommand('Ankita, write a note', asleep), { kind: 'command', text: 'write a note' });
  assert.deepEqual(voiceCommand('Ankita what is on my screen?', asleep), { kind: 'command', text: 'what is on my screen?' });
  assert.deepEqual(voiceCommand('Ankita: check the build', asleep), { kind: 'command', text: 'check the build' });
});

test('while awake, any unmatched speech is a normal command', () => {
  assert.deepEqual(voiceCommand('write a note', awake), { kind: 'command', text: 'write a note' });
  assert.deepEqual(voiceCommand('Ankita, write a note', awake), { kind: 'command', text: 'write a note' }, 'an awake wake-prefix is stripped too');
});

test('a greeting before the wake word still wakes, as people actually speak', () => {
  for (const phrase of ['Hi Ankita', 'Hi Ankita.', 'Hey Ankita', 'hello ankita!', 'Ok Ankita']) {
    assert.deepEqual(voiceCommand(phrase, asleep), { kind: 'wake', text: '' }, phrase);
  }
  assert.deepEqual(voiceCommand('Hi Ankita, write a note', asleep), { kind: 'command', text: 'write a note' });
});

test('exit phrases tolerate "mode"/"session" and articles, as observed in real transcripts', () => {
  for (const phrase of ['exit voice mode.', 'Exit voice mode', 'end the session', 'end my session', 'end voice', 'leave', 'quit', 'bye']) {
    assert.deepEqual(voiceCommand(phrase, awake), { kind: 'end', text: '' }, phrase);
  }
  // Ordinary sentences that merely start with an exit word stay requests.
  assert.deepEqual(voiceCommand('exit the folder and rerun', awake), { kind: 'command', text: 'exit the folder and rerun' });
  assert.deepEqual(voiceCommand('end the meeting notes', awake), { kind: 'command', text: 'end the meeting notes' });
  assert.deepEqual(voiceCommand('bye for now, schedule a reminder', awake), { kind: 'command', text: 'bye for now, schedule a reminder' });
});

test('while asleep, speech without the wake word is ignored and never becomes a command', () => {
  assert.deepEqual(voiceCommand('write a note', asleep), { kind: 'ignored', text: '' });
  assert.deepEqual(voiceCommand('what time is it', asleep), { kind: 'ignored', text: '' });
  // Contains the letters but is not the wake word as its own word.
  assert.deepEqual(voiceCommand("Ankita's notes app", asleep), { kind: 'ignored', text: '' });
  assert.deepEqual(voiceCommand('hey ankita', asleep), { kind: 'wake', text: '' }, 'a greeting-led wake word wakes');
  assert.deepEqual(voiceCommand('so anyway ankita was here', asleep), { kind: 'ignored', text: '' }, 'the wake word must lead the utterance');
});

test('stop phrases interrupt, but a command that merely contains "stop" does not', () => {
  for (const phrase of ['stop', 'Stop!', 'stop it', 'stop that', 'cancel', 'cancel that', 'never mind', 'nevermind']) {
    assert.deepEqual(voiceCommand(phrase, awake), { kind: 'stop', text: '' }, phrase);
  }
  assert.deepEqual(voiceCommand('stop by the store on the way home', awake), { kind: 'command', text: 'stop by the store on the way home' });
  assert.deepEqual(voiceCommand('please cancel my meeting', awake), { kind: 'command', text: 'please cancel my meeting' });
});

test('exit phrases still end the session and are not confused with stop', () => {
  for (const phrase of ['exit', 'quit', 'end voice', 'goodbye', 'bye']) {
    assert.deepEqual(voiceCommand(phrase, awake), { kind: 'end', text: '' }, phrase);
  }
});

test('the stop word can be switched off without disabling exit', () => {
  assert.deepEqual(voiceCommand('stop', { listening: true, stop: false }), { kind: 'command', text: 'stop' }, 'with stop off, "stop" is ordinary speech');
  assert.deepEqual(voiceCommand('exit', { listening: true, stop: false }), { kind: 'end', text: '' }, 'exit is never gated by the stop setting');
});

test('the wake word can be switched off, which makes standby unnecessary', () => {
  assert.deepEqual(voiceCommand('write a note', { listening: true, wake: false }), { kind: 'command', text: 'write a note' });
  assert.deepEqual(voiceCommand('Ankita', { listening: true, wake: false }), { kind: 'command', text: 'Ankita' }, 'without a wake word it is just a word');
});

test('blank or whitespace transcripts are ignored in every mode', () => {
  for (const value of ['', '   ', '\n\t', null, undefined]) {
    assert.deepEqual(voiceCommand(value, awake), { kind: 'ignored', text: '' });
  }
});
