/** Common IANA timezones for the profile/timezone pickers. */
export const COMMON_TIMEZONES = [
  'UTC',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Anchorage', 'Pacific/Honolulu', 'America/Toronto', 'America/Vancouver',
  'America/Mexico_City', 'America/Sao_Paulo', 'America/Buenos_Aires',
  'Atlantic/Azores', 'Europe/London', 'Europe/Lisbon', 'Europe/Paris',
  'Europe/Berlin', 'Europe/Rome', 'Europe/Madrid', 'Europe/Amsterdam',
  'Europe/Zurich', 'Europe/Stockholm', 'Europe/Athens', 'Europe/Istanbul',
  'Europe/Moscow', 'Africa/Cairo', 'Africa/Lagos', 'Africa/Johannesburg',
  'Asia/Dubai', 'Asia/Karachi', 'Asia/Kolkata', 'Asia/Dhaka', 'Asia/Bangkok',
  'Asia/Singapore', 'Asia/Hong_Kong', 'Asia/Shanghai', 'Asia/Taipei',
  'Asia/Tokyo', 'Asia/Seoul', 'Australia/Perth', 'Australia/Sydney',
  'Australia/Melbourne', 'Pacific/Auckland',
];

/** The machine's own IANA zone, or '' when it cannot be determined. */
export function detectTimezone(): string {
  try {
    return new Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
}

/** Suggestions with the detected zone first; anything valid can still be typed. */
export function timezoneSuggestions(detected: string): string[] {
  const zones = detected && !COMMON_TIMEZONES.includes(detected) ? [detected, ...COMMON_TIMEZONES] : [...COMMON_TIMEZONES];
  return zones;
}
