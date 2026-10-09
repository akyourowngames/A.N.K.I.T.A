import test from 'node:test';
import assert from 'node:assert/strict';
import { googleFlightEvidence } from '../../scripts/lib/browser-flight-evidence.mjs';

const DATE = '2026-10-10'; // Synthetic oracle date, independent of the machine clock.
const readBack = text => ({
  url: `https://flights.example.test/flights/search?tfs=${Buffer.from(DATE).toString('base64url')}`,
  text,
  inputs: [{ label: 'Where from?', value: 'Mumbai' }, { label: 'Where to?', value: 'New Delhi' }, { label: 'Departure', value: 'Sat, Oct 10' }],
});
const FLIGHTS = 'One way\nSearch results\n7:00 AM – 9:15 AM\nExample Air\n2 hr 15 min\n₹6,846'; // Synthetic priced flight, not a real offer.

test('a correct route and results shell still fail while flight fares are loading', () => {
  const loading = googleFlightEvidence(readBack('One way\nSearch results\nLoading prices.\nLoading...'), DATE);
  assert.equal(loading.dateVerified, true);
  assert.equal(loading.pass, false, 'results URL alone cannot certify readable flight information');
});

test('priced flights require both schedule and price evidence', () => {
  assert.equal(googleFlightEvidence(readBack(FLIGHTS), DATE).pass, true);
  assert.equal(googleFlightEvidence(readBack('One way\n7:00 AM – 9:15 AM\nLoading prices.'), DATE).pass, false);
  assert.equal(googleFlightEvidence(readBack('One way\n₹6,846'), DATE).pass, false);
});

test('priced results still fail with a reversed route or a wrong exact date', () => {
  const reversed = readBack(FLIGHTS);
  reversed.inputs[0].value = 'New Delhi'; reversed.inputs[1].value = 'Mumbai';
  assert.equal(googleFlightEvidence(reversed, DATE).pass, false);
  assert.equal(googleFlightEvidence(readBack(FLIGHTS), '2026-10-11').pass, false);
});
