import {
  PHONE_ACTION_NAMES, PHONE_DESTRUCTIVE_ACTIONS, PHONE_LOG_LIMIT_MAX, PHONE_LOG_LIMIT_DEFAULT,
  PHONE_PACKAGE_SPEC, PHONE_DOCS, PHONE_RAW_DESTRUCTIVE_TOOLS, PHONE_GUIDANCE, PHONE_WIRELESS_ACTIONS,
  phoneReadOnly, phoneNeedsApproval,
} from '../../src/integrations/phone-control.mjs';
import { PhoneSession, phoneSession, connectApprovalText } from './session.mjs';

export const name = 'phone';

// The long-form guidance lives in the description, not the system prompt: it is
// paid only once this family is discovered, never by users who never mention a phone.
export const description =
  'Control a real or emulated Android phone (and an iOS simulator on a Mac): read the screen, tap, type, swipe, ' +
  'open apps and URLs, take screenshots, and read logs. ' +
  `Requires ${PHONE_PACKAGE_SPEC} and a running emulator or USB-debugged phone; docs: ${PHONE_DOCS}. ` +
  `The first call asks once to start the bridge; after that safe actions run and only ${PHONE_DESTRUCTIVE_ACTIONS.join(', ')} ask again. ` +
  PHONE_GUIDANCE;

export const parameters = {
  type: 'object',
  properties: {
    action: { type: 'string', enum: [...PHONE_ACTION_NAMES], description: 'What to do. wireless/wireless_pair/wireless_connect set up Wi-Fi phones; devices/use select one; see reads the screen; tap/double_tap/long_press/swipe/type/button act on it.' },
    device: { type: 'string', description: 'Exact device id from action="devices" (for use) or when several phones are attached. Never guessed.' },
    code: { type: 'string', description: 'wireless_pair: the six-digit pairing code shown on the phone. Never guess it; ask the user to read it.' },
    address: { type: 'string', description: 'wireless_pair/wireless_connect: optional host:port. Omit to use the address I discovered over the network.' },
    ref: { type: 'string', description: 'Element ref from the latest action="see" (e.g. "@e5"). Preferred over x/y.' },
    x: { type: 'number', description: 'Screen x coordinate, only when no ref fits. From the latest screenshot, never guessed.' },
    y: { type: 'number', description: 'Screen y coordinate, only with x.' },
    text: { type: 'string', description: 'type: the text to enter. clipboard: optional text to set; omit to read.' },
    submit: { type: 'boolean', description: 'type: press Enter after typing.' },
    direction: { type: 'string', enum: ['up', 'down', 'left', 'right'], description: 'swipe direction.' },
    distance: { type: 'number', description: 'swipe distance in pixels; omit for the device default.' },
    button: { type: 'string', description: 'Hardware button: HOME, BACK, APP_SWITCH, POWER, LOCK, ENTER, VOLUME_UP, VOLUME_DOWN, DPAD_*. Android BACK/HOME/APP_SWITCH; iOS HOME/LOCK/VOLUME.' },
    url: { type: 'string', description: 'open: an http:// or https:// address to open in the phone browser.' },
    package: { type: 'string', description: 'App package id, e.g. com.android.chrome. From action="apps".' },
    path: { type: 'string', description: 'install: a .apk, .ipa, .zip or .app file on this computer.' },
    orientation: { type: 'string', enum: ['portrait', 'landscape'], description: 'set_orientation target.' },
    posture: { type: 'string', description: 'fold: "folded" or "unfolded", for foldable devices.' },
    angle: { type: 'number', description: 'fold: hinge angle in degrees.' },
    latitude: { type: 'number', description: 'location: latitude; omit latitude and longitude to clear the override.' },
    longitude: { type: 'number', description: 'location: longitude; omit both to clear.' },
    limit: { type: 'integer', minimum: 1, maximum: PHONE_LOG_LIMIT_MAX, description: `logs: entries to capture (default ${PHONE_LOG_LIMIT_DEFAULT}).` },
    filter: { type: 'string', description: 'logs: key=value filter such as tag=AndroidRuntime.' },
    id: { type: 'string', description: 'crash: crash report id from action="crashes".' },
    maxSize: { type: 'integer', minimum: 1, description: 'screenshot: longest edge in pixels (default 1024).' },
    output: { type: 'string', description: 'start_recording: output .mp4 path; omit for the device default.' },
    timeLimit: { type: 'integer', minimum: 1, description: 'start_recording: maximum seconds to record.' },
    steps: { type: 'array', description: 'batch: { name, arguments } mobile-mcp steps, each run against the active phone.', items: { type: 'object', properties: { name: { type: 'string' }, arguments: { type: 'object' } }, required: ['name'] } },
    stopOnError: { type: 'boolean', description: 'batch: stop at the first failing step (default true).' },
    tool: { type: 'string', description: 'raw: an allow-listed mobile-mcp tool name, e.g. mobile_fold_device.' },
    args: { type: 'object', description: 'raw: arguments for that tool; device is added automatically.' },
  },
  required: ['action'],
};

/**
 * Approval happens in two distinct moments:
 *   - the first call that needs the bridge: ask once, showing the exact command;
 *   - state-destroying actions (uninstall, clear_data, and the raw equivalents):
 *     always ask, because they are not cheap to undo.
 * Everything else runs after the connect decision has been made.
 */
export function needsApproval(args = {}, ctx = {}) {
  const session = phoneSession(ctx);
  // Wireless setup runs local adb only and never touches the phone's contents,
  // so it needs no prompt of its own - but starting the bridge still does.
  if (PHONE_WIRELESS_ACTIONS.includes(String(args.action || '').toLowerCase())) return false;
  if (!session?.connected) return true;
  return phoneNeedsApproval(args.action) || (String(args.action).toLowerCase() === 'raw' && PHONE_RAW_DESTRUCTIVE_TOOLS.includes(String(args.tool || '')));
}

export const readOnly = (args = {}) => phoneReadOnly(args.action, args);

/** What the user sees before connecting, or before an action that destroys phone state. */
export function approval(args = {}, ctx = {}) {
  const session = phoneSession(ctx);
  if (!session?.connected) return connectApprovalText();
  if (!phoneNeedsApproval(args.action) && String(args.action).toLowerCase() !== 'raw') return null;
  return `${String(args.action).toUpperCase()} on phone ${args.device || session.device || '(active device)'}. This changes the phone and cannot be undone by the assistant.`;
}

export { connectApprovalText };

/** Hide typed text and the pairing code from the approval preview. */
export function display(args = {}) {
  const shown = { ...args };
  if (typeof shown.text === 'string') shown.text = `[${shown.text.length} characters hidden]`;
  if (typeof shown.code === 'string') shown.code = '[pairing code hidden]';
  if (shown.args && typeof shown.args === 'object') shown.args = Object.fromEntries(
    Object.entries(shown.args).map(([key, value]) => [key, typeof value === 'string' && value.length > 40 ? `[${value.length} characters hidden]` : value])
  );
  return shown;
}

export async function run(args = {}, ctx = {}) {
  const session = phoneSession(ctx);
  if (!(session instanceof PhoneSession)) return 'Error: phone control needs a connected session in this host.';
  return session.run(args, ctx);
}
