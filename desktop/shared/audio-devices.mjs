/** Private main/worker protocol; renderers cannot issue native audio operations. */
export const AUDIO_DEVICE_OPS = Object.freeze({ inspect: 'inspect', route: 'route', restore: 'restore', watch: 'watch', unwatch: 'unwatch', close: 'close' });
export const AUDIO_OUTPUT_CHANGED = 'output-changed';
