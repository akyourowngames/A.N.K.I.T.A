export function windowChrome(platform = process.platform, native = process.env.ANKITA_NATIVE_FRAME === '1') {
  if (native || platform === 'linux') return { frame: true, controls: 'native' };
  if (platform === 'darwin') return { titleBarStyle: 'hiddenInset', controls: 'native' };
  return { frame: false, controls: 'custom' };
}
