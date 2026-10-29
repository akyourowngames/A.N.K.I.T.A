import { memo, type CSSProperties } from 'react';
const WORD_DELAY_MS = 24; // Milliseconds: small stagger without making a short reply wait to appear.
const MAX_STAGGER_WORDS = 8; // Bound entrance time for long finalized transcripts.
export const VoiceCaptions = memo(function VoiceCaptions({ text, role }: { text: string; role: 'user' | 'assistant' }) {
  return <div className="voice-caption-wrap" data-role={role}>
    <p key={`${role}:${text}`} className="voice-caption" aria-label={text}>
      {text.split(/(\s+)/u).map((word, index) => <span key={index} style={{ '--word-delay': `${Math.min(index, MAX_STAGGER_WORDS) * WORD_DELAY_MS}ms` } as CSSProperties}>{word}</span>)}
    </p>
  </div>;
});
