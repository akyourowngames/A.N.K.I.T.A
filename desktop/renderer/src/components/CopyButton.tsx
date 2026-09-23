import { useCopy } from '../lib/clipboard';
import { Icon } from './Icons';

export function CopyButton({ text, label = 'Copy', compact = false }: { text: string; label?: string; compact?: boolean }) {
  const { copied, copy } = useCopy();
  return <button
    type="button"
    className={`copy-button ${compact ? 'compact' : ''} ${copied ? 'copied' : ''}`}
    onClick={() => void copy(text)}
    title={copied ? 'Copied' : label}
    aria-label={label}
  >
    <Icon name={copied ? 'check' : 'copy'} size={14} />
    {!compact && <span>{copied ? 'Copied' : label}</span>}
  </button>;
}
