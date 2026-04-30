from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemControlTool:
    name: str = "system_control"
    description: str = "Controls Windows settings such as brightness, volume, Bluetooth settings, and apps."

    def run(self, action: str, value: int | str | None = None, target: str | None = None) -> str:
        action = action.strip().lower()
        command = self.command_for(action=action, value=value, target=target)
        if not command:
            return f"FAILED: unsupported system action '{action}'."

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as error:
            return f"FAILED: system control error: {error}\nFALLBACK_COMMAND: {command}"

        if result.returncode != 0:
            return (
                f"FAILED: system control returned exit code {result.returncode}\n"
                f"{result.stderr.strip()}\nFALLBACK_COMMAND: {command}"
            )

        return result.stdout.strip() or f"System action completed: {action}"

    def command_for(self, action: str, value: int | str | None = None, target: str | None = None) -> str:
        if action == "set_brightness":
            level = self._clamp_int(value, 0, 100)
            return (
                "$methods = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods; "
                f"$methods | ForEach-Object {{ Invoke-CimMethod -InputObject $_ -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={level}}} }}; "
                f"Write-Output 'Brightness set to {level}%'"
            )

        if action == "set_volume":
            level = self._clamp_int(value, 0, 100)
            return self._volume_command(level)

        if action == "mute":
            return (
                "$wshell = New-Object -ComObject WScript.Shell; "
                "$wshell.SendKeys([char]173); "
                "Write-Output 'Mute toggled'"
            )

        if action == "open_bluetooth":
            return "Start-Process 'ms-settings:bluetooth'; Write-Output 'Bluetooth settings opened'"

        if action == "open_settings":
            page = (target or "").strip() or "home"
            return f"Start-Process 'ms-settings:{page}'; Write-Output 'Settings opened: {page}'"

        if action == "open_app":
            app = (target or str(value or "")).strip()
            if not app:
                return ""
            escaped = app.replace("'", "''")
            return f"Start-Process '{escaped}'; Write-Output 'Opened app: {escaped}'"

        return ""

    @staticmethod
    def _clamp_int(value: int | str | None, minimum: int, maximum: int) -> int:
        try:
            number = int(value) if value is not None else maximum
        except ValueError:
            number = maximum
        return max(minimum, min(maximum, number))

    @staticmethod
    def _volume_command(level: int) -> str:
        return rf"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {{
    int RegisterControlChangeNotify(IntPtr pNotify);
    int UnregisterControlChangeNotify(IntPtr pNotify);
    int GetChannelCount(out uint pnChannelCount);
    int SetMasterVolumeLevel(float fLevelDB, Guid pguidEventContext);
    int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
    int GetMasterVolumeLevel(out float pfLevelDB);
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int SetChannelVolumeLevel(uint nChannel, float fLevelDB, Guid pguidEventContext);
    int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, Guid pguidEventContext);
    int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
    int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
    int SetMute(bool bMute, Guid pguidEventContext);
    int GetMute(out bool pbMute);
    int GetVolumeStepInfo(out uint pnStep, out uint pnStepCount);
    int VolumeStepUp(Guid pguidEventContext);
    int VolumeStepDown(Guid pguidEventContext);
    int QueryHardwareSupport(out uint pdwHardwareSupportMask);
    int GetVolumeRange(out float pflVolumeMindB, out float pflVolumeMaxdB, out float pflVolumeIncrementdB);
}}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {{
    int Activate(ref Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev);
}}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {{
    int NotImpl1();
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
}}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject {{}}

public class Audio {{
    public static void SetVolume(int level) {{
        IMMDeviceEnumerator enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        IMMDevice device;
        enumerator.GetDefaultAudioEndpoint(0, 1, out device);
        Guid endpointVolumeGuid = typeof(IAudioEndpointVolume).GUID;
        IAudioEndpointVolume volume;
        device.Activate(ref endpointVolumeGuid, 23, 0, out volume);
        volume.SetMute(false, Guid.Empty);
        volume.SetMasterVolumeLevelScalar(level / 100.0f, Guid.Empty);
    }}
}}
'@
[Audio]::SetVolume({level});
Write-Output 'Volume set to {level}%'
"""
