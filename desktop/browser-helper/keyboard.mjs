// CDP uses Windows virtual-key codes on all platforms; DOM codes preserve physical key identity.
const SPECIAL_KEYS = Object.freeze({
  Enter: [13, 'Enter', '\r'], Tab: [9, 'Tab', '\t'], Backspace: [8, 'Backspace'], Escape: [27, 'Escape'],
  Delete: [46, 'Delete'], Insert: [45, 'Insert'], Home: [36, 'Home'], End: [35, 'End'],
  PageUp: [33, 'PageUp'], PageDown: [34, 'PageDown'], ArrowLeft: [37, 'ArrowLeft'], ArrowUp: [38, 'ArrowUp'], ArrowRight: [39, 'ArrowRight'], ArrowDown: [40, 'ArrowDown'],
  Space: [32, 'Space', ' '],
});
const MODIFIERS = Object.freeze({ alt: 1, control: 2, ctrl: 2, meta: 4, command: 4, cmd: 4, shift: 8 }); // CDP bitmask.
const COMMAND_MODIFIERS = MODIFIERS.alt | MODIFIERS.control | MODIFIERS.meta;
const ALIASES = Object.freeze({ Esc: 'Escape', Return: 'Enter', Left: 'ArrowLeft', Right: 'ArrowRight', Up: 'ArrowUp', Down: 'ArrowDown', ' ': 'Space' });
const LETTER_CODE = 'Key', DIGIT_CODE = 'Digit'; // DOM KeyboardEvent.code prefixes.

export function keyEvents(chord, platform) {
  const parts = String(chord).split('+'), original = parts.pop();
  let modifiers = 0;
  for (const part of parts) {
    const normalized = part.toLowerCase();
    const mask = normalized === 'controlormeta' ? (platform === 'mac' ? MODIFIERS.meta : MODIFIERS.control) : MODIFIERS[normalized];
    if (!mask) throw new Error('Unsupported keyboard modifier');
    modifiers |= mask;
  }
  const keyName = ALIASES[original] || original;
  let key = keyName, code, windowsVirtualKeyCode, text;
  if (SPECIAL_KEYS[keyName]) { [windowsVirtualKeyCode, code, text] = SPECIAL_KEYS[keyName]; if (keyName === 'Space') key = ' '; }
  else if (/^[a-z]$/i.test(keyName)) { key = modifiers & MODIFIERS.shift ? keyName.toUpperCase() : keyName.toLowerCase(); code = LETTER_CODE + keyName.toUpperCase(); windowsVirtualKeyCode = keyName.toUpperCase().charCodeAt(0); text = keyName; }
  else if (/^[0-9]$/.test(keyName)) { code = DIGIT_CODE + keyName; windowsVirtualKeyCode = keyName.charCodeAt(0); text = keyName; }
  else throw new Error('Unsupported keyboard key; use fill/type for text or a named key such as Enter.');
  if (modifiers & COMMAND_MODIFIERS) text = undefined;
  const details = { key, code, windowsVirtualKeyCode, modifiers };
  return [{ type: text ? 'keyDown' : 'rawKeyDown', ...details, ...(text ? { text, unmodifiedText: text } : {}) }, { type: 'keyUp', ...details }];
}
