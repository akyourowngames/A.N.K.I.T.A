import { useEffect, useRef } from 'react';
import type { VoiceState } from '../../../../shared/voice.mjs';
import { VOICE_PHASE_LABELS } from '../../../../shared/voice.mjs';
import { VoiceOrb } from './VoiceOrb';
import { VoiceCaptions } from './VoiceCaptions';
import { Icon } from '../Icons';
import './voice.css';

const ACTIVE_TASK = new Set(['queued', 'running', 'waiting_for_approval']);
const PLACEHOLDERS = { idle: 'A little space to think out loud.', starting: 'Getting your voice ready.', listening: 'Go ahead. I’m listening.',
  transcribing: 'Catching your words.', working: 'I’m on it.', speaking: '', approval: 'Your permission is needed.', paused: 'Take your time.', error: 'Let’s get voice ready.' };

export function VoicePanel({ voice, error = '', busy = false, compact = false, onEnd, onPause, onResume, onCancel, onIsland, onSettings, onStart, onFocus }: {
  voice: VoiceState; error?: string; busy?: boolean; compact?: boolean;
  onEnd: () => unknown; onPause: () => unknown; onResume: () => unknown; onCancel: () => unknown;
  onIsland?: () => unknown; onSettings?: () => unknown; onStart?: () => unknown; onFocus?: () => unknown;
}) {
  const end = useRef<HTMLButtonElement>(null);
  const phase = error ? 'error' : voice.phase;
  const working = Boolean(voice.task && ACTIVE_TASK.has(voice.task.status));
  const issue = error || voice.error;
  useEffect(() => { if (!compact) end.current?.focus({ preventScroll: true }); }, [compact]);
  useEffect(() => {
    if (compact) return;
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape' && !document.querySelector('[aria-modal="true"]')) { event.preventDefault(); onEnd(); } };
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key);
  }, [compact, onEnd]);
  return <section className={`voice-panel ${compact ? 'voice-panel-compact' : ''}`} aria-label="Voice conversation" data-phase={phase}>
    {!compact && <div className="voice-panel-top"><span className="voice-eyebrow"><i /> ANKITA <b>/</b> VOICE</span>
      <button className="voice-text-button" onClick={onSettings}><Icon name="settings" size={15} /> Voice settings</button></div>}
    <div className="voice-stage">
      <VoiceOrb phase={phase} inputLevel={voice.inputLevel} compact={compact} />
      <div className="voice-phase" data-phase={phase}><i />{VOICE_PHASE_LABELS[phase]}</div>
      <VoiceCaptions text={voice.caption || PLACEHOLDERS[phase]} role={voice.captionRole} />
      <div className="voice-work-line" role="status" aria-live="polite" aria-atomic="true">
        {issue ? <span className="voice-error">{issue}</span> : voice.phase === 'approval' ? 'Review the permission request to continue.' : voice.update || (working ? 'Work is continuing in this conversation.' : voice.task?.status === 'done' ? 'Done · saved in this conversation' : voice.task?.status === 'failed' ? 'Work needs attention · see the conversation' : voice.task?.status === 'cancelled' ? 'Work stopped' : voice.paused ? 'Microphone is off' : 'Speak naturally. Pause to send.')}
      </div>
    </div>
    <div className="voice-controls">
      {voice.active ? <>
        <button className={`voice-control ${voice.paused ? 'is-muted' : ''}`} disabled={busy} onClick={voice.paused ? onResume : onPause} aria-label={voice.paused ? 'Resume microphone' : 'Pause microphone'} aria-pressed={voice.paused} title={voice.paused ? 'Resume microphone' : 'Pause microphone'}><Icon name={voice.paused ? 'micOff' : 'mic'} size={20} /></button>
        <button ref={end} className="voice-control voice-end" onClick={onEnd} aria-label="End voice" title="End voice · work keeps running"><Icon name="phoneEnd" size={21} /><span>End voice</span></button>
      </> : <button ref={end} className="voice-start" onClick={onStart} disabled={busy || !onStart}><Icon name="mic" size={18} />{busy ? 'Getting ready…' : 'Try voice again'}</button>}
      {working && <button className="voice-control voice-stop" onClick={onCancel} disabled={busy} aria-label="Stop work" title="Cancel this task"><Icon name="stop" size={14} /><span>Stop work</span></button>}
    </div>
    <div className="voice-panel-foot">{compact ? <button className="voice-text-button" onClick={onFocus}>Open conversation <Icon name="external" size={13} /></button>
      : <><span>{working ? 'End voice keeps your work running.' : voice.active ? 'Your words. A little momentum.' : 'Your conversation stays right here.'}</span><button className="voice-text-button" onClick={onIsland}><Icon name="panel" size={14} /> Continue in island</button></>}
    </div>
  </section>;
}
