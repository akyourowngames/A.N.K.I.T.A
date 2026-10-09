// Verification-only Google Flights read-back. English/INR UI evidence is not production routing truth.
export const FLIGHT_PRICE_PATTERN = /(?:₹|Rs\.?|INR|US\$|\$|€|£)\s*\d[\d,.]*/iu; // Rendered currency + amount, not the footer's currency name alone.
const FLIGHT_TIME_PATTERN = /\b\d{1,2}:\d{2}\s*(?:AM|PM)\b/giu; // English flight schedule times; at least departure and arrival are required.
const MIN_FLIGHT_TIMES = 2; // Clock times: distinguish a schedule from a lone time in page chrome.
export function flightResultContent(text) {
  const value = String(text || '');
  const times = value.match(FLIGHT_TIME_PATTERN) || [];
  return { priced: FLIGHT_PRICE_PATTERN.test(value), scheduled: times.length >= MIN_FLIGHT_TIMES };
}

export function googleFlightEvidence(readBack, departureDate) {
  const inputs = readBack?.inputs || [];
  const origin = inputs.find(input => /Where from\?/i.test(input.label || ''));
  const destination = inputs.find(input => /Where to\?/i.test(input.label || ''));
  const date = inputs.find(input => /Departure/i.test(input.label || ''));
  const encoded = readBack?.url ? new URL(readBack.url).searchParams.get('tfs') : null;
  const departureDates = encoded ? Buffer.from(encoded, 'base64url').toString('latin1').match(/\d{4}-\d{2}-\d{2}/g) || [] : [];
  const checks = { originMumbai: /Mumbai|BOM/i.test(origin?.value || ''), destinationDelhi: /Delhi|DEL/i.test(destination?.value || ''),
    oneWay: /One way/i.test(readBack?.text || ''), departure: date?.value || '', departureDates,
    resultsUrl: /\/flights\/search/.test(readBack?.url || '') };
  const dateVerified = departureDates.length === 1 && departureDates[0] === departureDate;
  const content = flightResultContent(readBack?.text);
  Object.assign(checks, content);
  return { checks, dateVerified, pass: checks.originMumbai && checks.destinationDelhi && checks.oneWay && checks.resultsUrl && dateVerified && content.priced && content.scheduled };
}
