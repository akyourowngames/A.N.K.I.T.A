import type { Compat } from '../../../shared/version.mjs';
import { Icon } from './Icons';

/**
 * Shown when the window and the background service are different builds.
 *
 * It is deliberately advisory, not a lockout: the app stays usable and the user
 * gets one click to recover. A contract mismatch means the two halves cannot
 * understand each other, so restarting is the only real fix; a version-only
 * mismatch is usually a half-applied update and restarting finishes it.
 */
export function VersionMismatchNotice({ compat, hasUpdate, onRestart, onDismiss }: {
  compat: Compat; hasUpdate: boolean; onRestart: () => void; onDismiss: () => void;
}) {
  return <div className="version-mismatch" role="alert">
    <span className="version-mismatch-glyph"><Icon name="alert" size={17} /></span>
    <div className="version-mismatch-copy">
      <strong>Ankita is out of sync</strong>
      <small>{compat.detail}</small>
    </div>
    <button className="button-primary version-mismatch-action" onClick={onRestart}>{hasUpdate ? 'Restart & update' : 'Restart Ankita'}</button>
    <button className="icon-button version-mismatch-close" onClick={onDismiss} aria-label="Continue anyway" title="Continue anyway"><Icon name="close" size={15} /></button>
  </div>;
}
