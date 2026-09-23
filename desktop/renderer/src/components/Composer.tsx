import { useEffect, useRef, useState } from 'react';
import type { Model } from '../../../shared/wire';
import { Icon } from './Icons';
import { ModelPicker } from './ModelPicker';

const prompts = [
  { label: 'Make a plan', text: 'Help me make a clear plan for what I’m working on.' },
  { label: 'Review my project', text: 'Review my current project and suggest the next step.' },
  { label: 'Explain a problem', text: 'Help me understand this problem and the best way to solve it.' },
];

export function Composer({ threadId, name, running, models, model, onModel, onSend, onStop }: {
  threadId: string; name: string; running: boolean; models: Model[]; model: string;
  onModel: (id: string) => void; onSend: (text: string) => void; onStop: () => void;
}) {
  const [text, setText] = useState('');
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const suggestions = useRef<HTMLDivElement>(null);

  useEffect(() => { if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 170)}px`; } }, [text]);
  useEffect(() => { setText(''); setSuggestionsOpen(false); }, [threadId]);
  useEffect(() => {
    if (!suggestionsOpen) return;
    const outside = (event: MouseEvent) => { if (!suggestions.current?.contains(event.target as Node)) setSuggestionsOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setSuggestionsOpen(false); };
    window.addEventListener('mousedown', outside);
    window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('mousedown', outside); window.removeEventListener('keydown', escape); };
  }, [suggestionsOpen]);

  const submit = () => { if (!text.trim() || running) return; setSuggestionsOpen(false); onSend(text.trim()); setText(''); input.current?.focus(); };
  const choosePrompt = (prompt: string) => { setText(prompt); setSuggestionsOpen(false); input.current?.focus(); };

  return <div className="composer-area"><div className="composer-shell">
    <textarea ref={input} rows={1} value={text} onChange={event => setText(event.target.value)} onKeyDown={event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
    }} placeholder={`Ask ${name} anything…`} aria-label={`Message ${name}`} disabled={running} />
    <div className="composer-bottom">
      <div className="composer-tools">
        <div className="composer-suggestions" ref={suggestions}>
          <button type="button" className="composer-icon" onClick={() => setSuggestionsOpen(!suggestionsOpen)} disabled={running} title="Prompt ideas" aria-label="Prompt ideas" aria-haspopup="menu" aria-expanded={suggestionsOpen}><Icon name="plus" size={18} /></button>
          {suggestionsOpen && <div className="suggestions-menu" role="menu" aria-label="Prompt ideas">
            <span className="suggestions-heading">Start with an idea</span>
            {prompts.map(prompt => <button type="button" role="menuitem" key={prompt.label} onClick={() => choosePrompt(prompt.text)}><Icon name="sparkle" size={15} /><span>{prompt.label}</span></button>)}
          </div>}
        </div>
        <span className="composer-key-hint">Enter to send <span aria-hidden="true">·</span> Shift + Enter for a new line</span>
      </div>
      <div className="composer-controls">
        <ModelPicker models={models} value={model} onChange={onModel} openUp />
        {running ? <button type="button" className="composer-action stop" onClick={onStop} title="Stop response" aria-label="Stop response"><Icon name="stop" size={17} /></button>
          : <button type="button" className="composer-action send" onClick={submit} disabled={!text.trim()} title="Send message" aria-label="Send message"><Icon name="send" size={19} stroke={2.1} /></button>}
      </div>
    </div>
  </div></div>;
}
