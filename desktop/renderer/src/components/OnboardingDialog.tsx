import { useState } from 'react';
import { Icon } from './Icons';
import { detectTimezone, timezoneSuggestions } from '../lib/timezones';

/**
 * First-launch profile step, shown once after the provider connects.
 *
 * Name feeds the system prompt ("address them by name"); timezone drives
 * journaling, quiet hours and routine scheduling. Skippable - everything
 * falls back to current defaults and lives on in Settings → Profile.
 */
export function OnboardingDialog({ initialName, initialTimeZone, onSave, onSkip }: {
  initialName: string; initialTimeZone: string;
  onSave: (patch: { username: string; timeZone: string }) => Promise<void>;
  onSkip: () => Promise<void>;
}) {
  const detected = detectTimezone();
  const [name, setName] = useState(initialName && initialName !== 'user' ? initialName : '');
  const [timeZone, setTimeZone] = useState(initialTimeZone || detected);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await fn(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  return <div className="modal-backdrop"><div className="onboarding-dialog" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
    <div className="modal-symbol"><Icon name="user" size={21} /></div>
    <h2 id="onboarding-title">You&apos;re connected. Who are you?</h2>
    <p>Ankita addresses you by name, and your timezone keeps journaling, reminders and quiet hours on local time. You can change both anytime in Settings → Profile.</p>
    <div className="settings-field"><label htmlFor="onboarding-name">Display name</label>
      <input id="onboarding-name" value={name} onChange={event => setName(event.target.value)}
        placeholder="e.g. Krish" maxLength={100} autoComplete="off" spellCheck={false} autoFocus />
    </div>
    <div className="settings-field"><label htmlFor="onboarding-timezone">Timezone</label>
      <input id="onboarding-timezone" value={timeZone} onChange={event => setTimeZone(event.target.value)}
        list="onboarding-timezones" placeholder={detected || 'e.g. Asia/Kolkata'} autoComplete="off" spellCheck={false} />
      <datalist id="onboarding-timezones">{timezoneSuggestions(detected).map(zone => <option key={zone} value={zone} />)}</datalist>
      <small>Blank means system local time. Any valid IANA zone works.</small>
    </div>
    {error && <div className="settings-note error" role="alert"><Icon name="alert" size={15} />{error}</div>}
    <div className="onboarding-actions">
      <button type="button" className="button-quiet" onClick={() => void run(onSkip)} disabled={busy}>Skip for now</button>
      <button type="button" className="button-primary" onClick={() => void run(() => onSave({ username: name.trim(), timeZone: timeZone.trim() }))} disabled={busy}>{busy ? 'Saving…' : 'Save and start'}</button>
    </div>
  </div></div>;
}
