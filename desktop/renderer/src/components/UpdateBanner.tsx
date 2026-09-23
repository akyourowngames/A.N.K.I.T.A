import type { UpdateEvent } from '../../../shared/wire';
import { Icon } from './Icons';

export function UpdateBanner({ update, onInstall, onOpenRelease, onDismiss }: { update: UpdateEvent; onInstall: () => void; onOpenRelease: () => void; onDismiss: () => void }) {
  const version = 'version' in update && update.version ? `v${update.version}` : 'A new version';
  let text = '';
  let tone = 'info';
  let action: React.ReactNode = null;

  if (update.type === 'checking') text = 'Checking for updates…';
  else if (update.type === 'available') text = `Downloading ${version}…`;
  else if (update.type === 'progress') text = `Downloading update… ${update.percent}%`;
  else if (update.type === 'stalled') {
    text = `No download progress at ${update.percent}%. Check your connection.`;
    tone = 'error';
    action = <button className="update-release" onClick={onOpenRelease}>Open release</button>;
  }
  else if (update.type === 'downloaded') {
    text = `${version} is ready to install.`;
    tone = 'ready';
    action = <button className="button-primary update-action" onClick={onInstall}>Restart &amp; update</button>;
  } else if (update.type === 'current') text = "You're on the latest version.";
  else if (update.type === 'unsupported') text = 'This build updates through its installer, not in-app.';
  else if (update.type === 'error') {
    text = "Update failed. You can install it from the release page.";
    tone = 'error';
    action = <button className="update-release" onClick={onOpenRelease}>Open release</button>;
  }

  return <div className={`update-banner ${tone}`} role="status">
    <span className="update-glyph"><Icon name={tone === 'error' ? 'alert' : 'sparkle'} size={15} /></span>
    <span className="update-text">{text}</span>
    {action}
    <button className="icon-button update-close" onClick={onDismiss} aria-label="Dismiss"><Icon name="close" size={15} /></button>
  </div>;
}
