// Island header tabs — React port of buildHeader in Coucou's
// windows/src/views/views.ts (MIT License, (c) Louis Raille).

import { Icon } from './icons';
import type { IslandHomeView } from './views';

export function Header({
  view, soundOn, onNavigate, onDrop, onToggleSound,
}: {
  view: IslandHomeView;
  soundOn: boolean;
  onNavigate: (view: IslandHomeView) => void;
  onDrop: () => void;
  onToggleSound: () => void;
}) {
  const tab = (target: IslandHomeView, title: string, icon: 'house' | 'bubble' | 'plus', on: boolean) => (
    <button
      key={target}
      className={`island-tab${on ? ' on' : ''}`}
      title={title}
      aria-label={title}
      role="tab"
      aria-selected={on}
      onClick={event => { event.stopPropagation(); onNavigate(target); }}
    >
      <Icon name={icon} size={13} />
    </button>
  );
  return (
    <div className="island-tabs" role="tablist" aria-label="Island views">
      <div className="island-tabs-group">
        {tab('overview', 'Overview', 'house', view === 'overview' || view === 'empty')}
        {tab('prompt', 'Ask', 'bubble', view === 'prompt')}
        <button
          key="drop"
          className="island-tab"
          title="Attach a file"
          aria-label="Attach a file"
          onClick={event => { event.stopPropagation(); onDrop(); }}
        >
          <Icon name="plus" size={13} />
        </button>
      </div>
      <div className="island-tabs-group">
        <button
          className={`island-tab${view === 'settings' ? ' on' : ''}`}
          title="Settings"
          aria-label="Settings"
          onClick={event => { event.stopPropagation(); onNavigate('settings'); }}
        >
          <Icon name="gear" size={14} />
        </button>
        <button
          className="island-tab"
          title={soundOn ? 'Mute' : 'Unmute'}
          aria-label={soundOn ? 'Mute' : 'Unmute'}
          onClick={event => { event.stopPropagation(); onToggleSound(); }}
        >
          <Icon name={soundOn ? 'speakerOn' : 'speakerOff'} size={14} />
        </button>
      </div>
    </div>
  );
}
