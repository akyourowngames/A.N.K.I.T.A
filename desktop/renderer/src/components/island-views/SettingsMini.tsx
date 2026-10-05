// In-island mini settings — React port of buildSettings in Coucou's
// windows/src/views/views.ts (MIT License, (c) Louis Raille), reduced to the
// sound and volume controls use the same persisted preferences as the header.

import { useState } from 'react';
import { Card } from './Card';
import { getSoundVolume, setSoundVolume, SOUND_VOLUME_MAX, SOUND_VOLUME_STEP } from '../../island/sound';
import { BrowserHelperSetup } from '../BrowserHelperSetup';

export function SettingsMini({ soundOn: on, onToggleSound }: { soundOn: boolean; onToggleSound: () => void }) {
  const [vol, setVol] = useState(getSoundVolume());
  return (
    <div className="island-view">
      <Card wash={null}>
        <div className="island-settings-rows">
          <div className="island-settings-row">
            <button
              className={`island-switch${on ? ' on' : ''}`}
              role="switch"
              aria-checked={on}
              aria-label="Sound"
              onClick={event => {
                event.stopPropagation();
                onToggleSound();
              }}
            />
            <span>Sound</span>
            <input
              type="range"
              min="0"
              max={SOUND_VOLUME_MAX}
              step={SOUND_VOLUME_STEP}
              value={vol}
              aria-label="Volume"
              onChange={event => {
                const v = Number(event.target.value);
                setVol(v);
                setSoundVolume(v);
              }}
              onClick={event => event.stopPropagation()}
              disabled={!on}
            />
          </div>
        </div>
        <BrowserHelperSetup />
      </Card>
    </div>
  );
}
