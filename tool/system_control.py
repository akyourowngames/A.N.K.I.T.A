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
                f"{result.stdout.strip()}\n"
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
            return self._open_app_command(app)

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

    @staticmethod
    def _open_app_command(app: str) -> str:
        query = app.strip().replace("'", "''")
        fallback = SystemControlTool._app_discovery_command(app).replace("'", "''")
        return rf"""
$query = '{query}'
$fallbackCommand = '{fallback}'
$attempts = New-Object System.Collections.Generic.List[string]
$beforeProcessIds = @(Get-Process | ForEach-Object {{ $_.Id }})

function Normalize-AppText([string]$text) {{
    if (-not $text) {{ return "" }}
    return ([regex]::Replace($text.ToLowerInvariant(), "[^a-z0-9]", ""))
}}

function Test-AppMatch([string]$candidate, [string]$needle) {{
    $candidateNorm = Normalize-AppText $candidate
    $needleNorm = Normalize-AppText $needle
    if (-not $candidateNorm -or -not $needleNorm) {{ return $false }}
    if ($candidateNorm.Contains($needleNorm) -or $needleNorm.Contains($candidateNorm)) {{ return $true }}

    $words = [regex]::Matches($candidate.ToLowerInvariant(), "[a-z0-9]+") | ForEach-Object {{ $_.Value }}
    $acronym = -join ($words | ForEach-Object {{ $_.Substring(0, 1) }})
    if ($acronym -and $needleNorm -eq $acronym) {{ return $true }}

    $needleWords = [regex]::Matches($needle.ToLowerInvariant(), "[a-z0-9]+") | ForEach-Object {{ $_.Value }}
    foreach ($word in $needleWords) {{
        if ($word.Length -ge 3 -and $candidateNorm.Contains($word)) {{ return $true }}
    }}
    return $false
}}

function Get-ProcessNameFromTarget([string]$target) {{
    if (-not $target) {{ return "" }}
    $leaf = Split-Path -Leaf $target
    if (-not $leaf) {{ $leaf = $target.Split(" ")[0] }}
    return [System.IO.Path]::GetFileNameWithoutExtension($leaf)
}}

function Confirm-AppOpened([string]$method, [string]$target, [string]$expectedProcess) {{
    Start-Sleep -Milliseconds 1800
    $newProcesses = @(Get-Process | Where-Object {{ $beforeProcessIds -notcontains $_.Id }})

    if ($expectedProcess) {{
        $existing = Get-Process -Name $expectedProcess -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowTitle }} | Select-Object -First 1
        if ($existing) {{
            Write-Output "VERIFIED: app opened using $method`: $target (process: $($existing.ProcessName))"
            exit 0
        }}
        $newExpected = $newProcesses | Where-Object {{ $_.ProcessName -eq $expectedProcess }} | Select-Object -First 1
        if ($newExpected) {{
            Write-Output "VERIFIED: app process started using $method`: $target (process: $($newExpected.ProcessName))"
            exit 0
        }}
    }}

    if (-not $expectedProcess) {{
        $windowProcess = $newProcesses | Where-Object {{ $_.MainWindowTitle }} | Select-Object -First 1
        if ($windowProcess) {{
            Write-Output "VERIFIED: app opened using $method`: $target (new window process: $($windowProcess.ProcessName))"
            exit 0
        }}
    }}
}}

function Try-Launch([string]$method, [string]$target, [string]$expectedProcess = "") {{
    if (-not $target) {{ return }}
    try {{
        $attempts.Add("$method`: $target")
        Start-Process $target
        Confirm-AppOpened $method $target $expectedProcess
    }} catch {{
        $attempts.Add("$method failed: $($_.Exception.Message)")
    }}
}}

$shortcutRoots = @(
    [Environment]::GetFolderPath("StartMenu"),
    [Environment]::GetFolderPath("CommonStartMenu"),
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("CommonDesktopDirectory")
) | Where-Object {{ $_ -and (Test-Path $_) }}

$shortcuts = @(
    foreach ($root in $shortcutRoots) {{
        Get-ChildItem -Path $root -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue |
            Where-Object {{ Test-AppMatch $_.BaseName $query }}
    }}
) | Sort-Object {{ $_.BaseName.Length }} -Unique | Select-Object -First 10

$shell = New-Object -ComObject WScript.Shell
foreach ($shortcut in $shortcuts) {{
    $resolved = $shell.CreateShortcut($shortcut.FullName)
    $expected = Get-ProcessNameFromTarget $resolved.TargetPath
    Try-Launch "shortcut" $shortcut.FullName $expected
}}

$startApps = @(Get-StartApps -ErrorAction SilentlyContinue |
    Where-Object {{ (Test-AppMatch $_.Name $query) -or (Test-AppMatch $_.AppID $query) }} |
    Sort-Object {{ $_.Name.Length }} |
    Select-Object -First 10)

foreach ($startApp in $startApps) {{
    $appId = $startApp.AppID
    if ($appId) {{
        Try-Launch "start-app" "shell:AppsFolder\$appId" ""
    }}
}}

$appPathRoots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\*"
)

$appPaths = @(
    foreach ($root in $appPathRoots) {{
        Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
            Where-Object {{ (Test-AppMatch (Split-Path -Leaf $_.PSChildName) $query) -or (Test-AppMatch $_.'(default)' $query) }} |
            Select-Object -First 10
    }}
) | Select-Object -First 10

foreach ($appPath in $appPaths) {{
    $target = $appPath.'(default)'
    if (-not $target) {{ $target = $appPath.PSChildName }}
    Try-Launch "app-path" $target (Get-ProcessNameFromTarget $target)
}}

$commands = @()
$singleTokenQuery = $query -notmatch "\s"
$looksLikePathOrExe = $query -match "[:\\/]" -or $query.ToLowerInvariant().EndsWith(".exe")
if ($singleTokenQuery -or $looksLikePathOrExe) {{
    $commands = @(Get-Command $query -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 4)
}}

foreach ($command in $commands) {{
    Try-Launch "exact-command" $command.Source (Get-ProcessNameFromTarget $command.Source)
}}

if ($looksLikePathOrExe -and -not $commands) {{
    Try-Launch "direct-path" $query (Get-ProcessNameFromTarget $query)
}}

$matches = @()
$matches += $commands | ForEach-Object {{ "command: $($_.Name) -> $($_.Source)" }}
$matches += $shortcuts | ForEach-Object {{ "shortcut: $($_.BaseName) -> $($_.FullName)" }}
$matches += $startApps | ForEach-Object {{ "start-app: $($_.Name) -> $($_.AppID)" }}
$matches += $appPaths | ForEach-Object {{ "app-path: $($_.PSChildName) -> $($_.'(default)')" }}

Write-Output "FAILED: app was not opened or verified for query: $query"
if ($attempts.Count) {{
    Write-Output "ATTEMPTS:"
    $attempts | Select-Object -First 20 | ForEach-Object {{ Write-Output "- $_" }}
}}
if ($matches.Count) {{
    Write-Output "DISCOVERED_MATCHES:"
    $matches | Select-Object -First 20 | ForEach-Object {{ Write-Output "- $_" }}
}} else {{
    Write-Output "DISCOVERED_MATCHES: none"
}}
Write-Output "FALLBACK_COMMAND: $fallbackCommand"
"""

    @staticmethod
    def _app_discovery_command(app: str) -> str:
        escaped = app.strip().replace("'", "''")
        return (
            f"$query='{escaped}'; "
            "Get-StartApps | Where-Object { $_.Name -like \"*$query*\" } | Select-Object -First 20 Name,AppID; "
            "$roots=@([Environment]::GetFolderPath('StartMenu'),[Environment]::GetFolderPath('CommonStartMenu')); "
            "$roots | Where-Object { $_ -and (Test-Path $_) } | ForEach-Object { "
            "Get-ChildItem $_ -Filter '*.lnk' -Recurse -ErrorAction SilentlyContinue | "
            "Where-Object { $_.BaseName -like \"*$query*\" } | Select-Object -First 20 FullName }; "
            "$appPathRoots=@('HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\*','HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\*','HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\App Paths\\*'); "
            "$appPathRoots | ForEach-Object { Get-ItemProperty -Path $_ -ErrorAction SilentlyContinue | "
            "Where-Object { $_.PSChildName -like \"*$query*\" -or $_.'(default)' -like \"*$query*\" } | "
            "Select-Object -First 20 PSChildName,'(default)' }"
        )
