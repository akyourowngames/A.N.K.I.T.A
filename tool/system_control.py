from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any


ACTION_ALIASES = {
    "status": "status",
    "get_status": "status",
    "system_status": "status",
    "pc_status": "status",
    "set_volume": "set_volume",
    "volume": "set_volume",
    "get_volume": "get_volume",
    "volume_status": "get_volume",
    "volume_up": "volume_up",
    "raise_volume": "volume_up",
    "increase_volume": "volume_up",
    "louder": "volume_up",
    "volume_down": "volume_down",
    "lower_volume": "volume_down",
    "decrease_volume": "volume_down",
    "quieter": "volume_down",
    "mute": "mute",
    "set_mute": "mute",
    "unmute": "unmute",
    "toggle_mute": "toggle_mute",
    "set_brightness": "set_brightness",
    "brightness": "set_brightness",
    "get_brightness": "get_brightness",
    "brightness_status": "get_brightness",
    "brightness_up": "brightness_up",
    "raise_brightness": "brightness_up",
    "increase_brightness": "brightness_up",
    "brighten": "brightness_up",
    "brightness_down": "brightness_down",
    "lower_brightness": "brightness_down",
    "decrease_brightness": "brightness_down",
    "dim": "brightness_down",
    "open_bluetooth": "open_bluetooth",
    "open_settings": "open_settings",
    "settings": "open_settings",
    "open_app": "open_app",
    "launch_app": "open_app",
    "start_app": "open_app",
    "find_app": "find_app",
    "discover_app": "find_app",
    "open_url": "open_url",
    "open_link": "open_url",
    "open_path": "open_path",
    "open_file": "open_path",
    "open_folder": "open_path",
    "reveal_path": "reveal_path",
    "show_in_folder": "reveal_path",
    "lock_screen": "lock_screen",
    "lock": "lock_screen",
}


@dataclass(frozen=True)
class SystemControlTool:
    name: str = "system_control"
    description: str = "Controls Windows settings, volume, brightness, system status, paths, URLs, and apps dynamically."

    def run(
        self,
        action: str,
        value: int | str | None = None,
        target: str | None = None,
        amount: int | str | None = None,
        timeout: int | str | None = None,
    ) -> str:
        normalized_action = self._normalize_action(action)
        command = self.command_for(action=normalized_action, value=value, target=target, amount=amount)
        if not command:
            return f"FAILED: unsupported system action '{action}'."

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                timeout=self._clamp_int(timeout, 1, 180, default=90),
            )
        except Exception as error:
            return f"FAILED: system control error: {error}\nFALLBACK_COMMAND: {command}"

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return (
                f"FAILED: system control returned exit code {result.returncode}\n"
                f"{stdout}\n"
                f"{stderr}\nFALLBACK_COMMAND: {command}"
            )

        return stdout or f"System action completed: {normalized_action}"

    def command_for(
        self,
        action: str,
        value: int | str | None = None,
        target: str | None = None,
        amount: int | str | None = None,
    ) -> str:
        action = self._normalize_action(action)

        if action == "status":
            return self._status_command()

        if action == "get_volume":
            return self._volume_command("get")

        if action == "set_volume":
            level = self._clamp_int(value, 0, 100, default=100)
            return self._volume_command("set", level=level)

        if action == "volume_up":
            step = self._step_amount(amount if amount is not None else value)
            return self._volume_command("adjust", amount=step)

        if action == "volume_down":
            step = self._step_amount(amount if amount is not None else value)
            return self._volume_command("adjust", amount=-step)

        if action == "mute":
            return self._volume_command("mute")

        if action == "unmute":
            return self._volume_command("unmute")

        if action == "toggle_mute":
            return self._volume_command("toggle_mute")

        if action == "get_brightness":
            return self._brightness_command("get")

        if action == "set_brightness":
            level = self._clamp_int(value, 0, 100, default=100)
            return self._brightness_command("set", level=level)

        if action == "brightness_up":
            step = self._step_amount(amount if amount is not None else value)
            return self._brightness_command("adjust", amount=step)

        if action == "brightness_down":
            step = self._step_amount(amount if amount is not None else value)
            return self._brightness_command("adjust", amount=-step)

        if action == "open_bluetooth":
            return self._open_settings_command("bluetooth")

        if action == "open_settings":
            page = str(target or value or "home").strip()
            return self._open_settings_command(page)

        if action == "open_app":
            app = str(target or value or "").strip()
            return self._open_app_command(app) if app else ""

        if action == "find_app":
            app = str(target or value or "").strip()
            return self._app_discovery_command(app) if app else ""

        if action == "open_url":
            url = str(target or value or "").strip()
            return self._open_url_command(url) if url else ""

        if action == "open_path":
            path = str(target or value or "").strip()
            return self._open_path_command(path) if path else ""

        if action == "reveal_path":
            path = str(target or value or "").strip()
            return self._reveal_path_command(path) if path else ""

        if action == "lock_screen":
            return "rundll32.exe user32.dll,LockWorkStation; Write-Output 'Screen locked'"

        return ""

    @staticmethod
    def _normalize_action(action: str) -> str:
        key = " ".join(str(action or "").strip().lower().replace("-", "_").split())
        key = key.replace(" ", "_")
        return ACTION_ALIASES.get(key, key)

    @staticmethod
    def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    @classmethod
    def _step_amount(cls, value: Any) -> int:
        return cls._clamp_int(value, 1, 100, default=10)

    @staticmethod
    def _ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @classmethod
    def _status_command(cls) -> str:
        return rf"""
{cls._audio_helper()}
Write-Output 'System status:'
try {{
    $volume = [Audio]::GetVolume()
    $muted = [Audio]::GetMute()
    Write-Output "Volume: $volume% muted=$muted"
}} catch {{
    Write-Output "Volume: unavailable ($($_.Exception.Message))"
}}

try {{
    $brightness = @(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop)
    if ($brightness.Count -gt 0) {{
        $current = [int]($brightness | Select-Object -First 1).CurrentBrightness
        Write-Output "Brightness: $current%"
    }} else {{
        Write-Output 'Brightness: unavailable'
    }}
}} catch {{
    Write-Output "Brightness: unavailable ($($_.Exception.Message))"
}}

try {{
    $batteries = @(Get-CimInstance -ClassName Win32_Battery -ErrorAction SilentlyContinue)
    if ($batteries.Count -gt 0) {{
        foreach ($battery in $batteries) {{
            Write-Output "Battery: $($battery.EstimatedChargeRemaining)% status=$($battery.BatteryStatus)"
        }}
    }} else {{
        Write-Output 'Battery: not detected'
    }}
}} catch {{
    Write-Output "Battery: unavailable ($($_.Exception.Message))"
}}

try {{
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $uptime = (Get-Date) - $os.LastBootUpTime
    Write-Output "OS: $($os.Caption) $($os.Version)"
    Write-Output "Uptime: $([int]$uptime.TotalHours)h $($uptime.Minutes)m"
}} catch {{
    Write-Output "OS: unavailable ($($_.Exception.Message))"
}}
"""

    @classmethod
    def _volume_command(cls, operation: str, level: int | None = None, amount: int = 0) -> str:
        if operation == "get":
            body = """
$volume = [Audio]::GetVolume()
$muted = [Audio]::GetMute()
Write-Output "Volume: $volume% muted=$muted"
"""
        elif operation == "set":
            body = f"""
[Audio]::SetVolume({level});
$muted = [Audio]::GetMute()
Write-Output 'Volume set to {level}%'
Write-Output "Muted: $muted"
"""
        elif operation == "adjust":
            sign = "+" if amount >= 0 else "-"
            body = f"""
$current = [Audio]::GetVolume()
$target = [Math]::Max(0, [Math]::Min(100, $current {sign} {abs(amount)}))
[Audio]::SetVolume($target)
Write-Output "Volume set to $target% (was $current%)"
"""
        elif operation == "mute":
            body = """
[Audio]::SetMute($true)
Write-Output 'Muted: true'
"""
        elif operation == "unmute":
            body = """
[Audio]::SetMute($false)
Write-Output 'Muted: false'
"""
        elif operation == "toggle_mute":
            body = """
$current = [Audio]::GetMute()
[Audio]::SetMute(-not $current)
$muted = [Audio]::GetMute()
Write-Output "Muted: $muted"
"""
        else:
            return ""

        return cls._audio_helper() + body

    @staticmethod
    def _audio_helper() -> str:
        return r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
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
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev);
}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int NotImpl1();
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject {}

public class Audio {
    static IAudioEndpointVolume Endpoint() {
        IMMDeviceEnumerator enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        IMMDevice device;
        enumerator.GetDefaultAudioEndpoint(0, 1, out device);
        Guid endpointVolumeGuid = typeof(IAudioEndpointVolume).GUID;
        IAudioEndpointVolume volume;
        device.Activate(ref endpointVolumeGuid, 23, 0, out volume);
        return volume;
    }

    public static void SetVolume(int level) {
        IAudioEndpointVolume volume = Endpoint();
        volume.SetMute(false, Guid.Empty);
        volume.SetMasterVolumeLevelScalar(level / 100.0f, Guid.Empty);
    }

    public static int GetVolume() {
        IAudioEndpointVolume volume = Endpoint();
        float scalar;
        volume.GetMasterVolumeLevelScalar(out scalar);
        return (int)Math.Round(scalar * 100.0f);
    }

    public static void SetMute(bool muted) {
        IAudioEndpointVolume volume = Endpoint();
        volume.SetMute(muted, Guid.Empty);
    }

    public static bool GetMute() {
        IAudioEndpointVolume volume = Endpoint();
        bool muted;
        volume.GetMute(out muted);
        return muted;
    }
}
'@
"""

    @classmethod
    def _brightness_command(cls, operation: str, level: int | None = None, amount: int = 0) -> str:
        if operation == "get":
            return """
$brightness = @(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop)
if ($brightness.Count -eq 0) { Write-Output 'FAILED: brightness status unavailable'; exit 1 }
$current = [int]($brightness | Select-Object -First 1).CurrentBrightness
Write-Output "Brightness: $current%"
"""

        if operation == "set":
            target_expression = str(level)
            success_output = f'"Brightness set to {level}% (was $current%)"'
        elif operation == "adjust":
            sign = "+" if amount >= 0 else "-"
            target_expression = f"[Math]::Max(0, [Math]::Min(100, $current {sign} {abs(amount)}))"
            success_output = '"Brightness set to $target% (was $current%)"'
        else:
            return ""

        return f"""
$brightness = @(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop)
if ($brightness.Count -eq 0) {{ Write-Output 'FAILED: brightness status unavailable'; exit 1 }}
$current = [int]($brightness | Select-Object -First 1).CurrentBrightness
$target = {target_expression}
$methods = @(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop)
if ($methods.Count -eq 0) {{ Write-Output 'FAILED: brightness control unavailable'; exit 1 }}
$methods | ForEach-Object {{ Invoke-CimMethod -InputObject $_ -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness=$target}} | Out-Null }}
Write-Output {success_output}
"""

    @classmethod
    def _open_settings_command(cls, page: str) -> str:
        normalized = page.strip()
        if normalized.lower().startswith("ms-settings:"):
            uri = normalized
        elif normalized.lower() in {"", "home"}:
            uri = "ms-settings:"
        else:
            uri = f"ms-settings:{normalized}"
        return f"Start-Process {cls._ps(uri)}; Write-Output {cls._ps(f'Settings opened: {uri}')}"

    @classmethod
    def _open_url_command(cls, url: str) -> str:
        target = cls._ps(url)
        return rf"""
$target = {target}
$uri = $null
if ([Uri]::TryCreate($target, [UriKind]::Absolute, [ref]$uri)) {{
    Start-Process $target
    Write-Output "URL opened: $target"
}} else {{
    Write-Output "FAILED: invalid URL: $target"
    exit 1
}}
"""

    @classmethod
    def _open_path_command(cls, path: str) -> str:
        target = cls._ps(path)
        return rf"""
$target = {target}
$resolved = Resolve-Path -LiteralPath $target -ErrorAction SilentlyContinue
if (-not $resolved) {{
    Write-Output "FAILED: path not found: $target"
    exit 1
}}
Start-Process -LiteralPath $resolved.Path
Write-Output "Path opened: $($resolved.Path)"
"""

    @classmethod
    def _reveal_path_command(cls, path: str) -> str:
        target = cls._ps(path)
        return rf"""
$target = {target}
$resolved = Resolve-Path -LiteralPath $target -ErrorAction SilentlyContinue
if (-not $resolved) {{
    Write-Output "FAILED: path not found: $target"
    exit 1
}}
explorer.exe /select,$resolved.Path
Write-Output "Path revealed: $($resolved.Path)"
"""

    @classmethod
    def _open_app_command(cls, app: str) -> str:
        query = cls._ps(app.strip())
        fallback = cls._ps(cls._app_discovery_command(app))
        return rf"""
$query = {query}
$fallbackCommand = {fallback}
$attempts = New-Object System.Collections.Generic.List[string]
$beforeProcessIds = @(Get-Process | ForEach-Object {{ $_.Id }})
{cls._app_match_helpers()}
{cls._app_candidate_script()}

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

foreach ($shortcut in $shortcuts) {{
    $resolved = $shell.CreateShortcut($shortcut.FullName)
    $expected = Get-ProcessNameFromTarget $resolved.TargetPath
    Try-Launch "shortcut" $shortcut.FullName $expected
}}

foreach ($startApp in $startApps) {{
    if ($startApp.AppID) {{
        Try-Launch "start-app" "shell:AppsFolder\$($startApp.AppID)" ""
    }}
}}

foreach ($appPath in $appPaths) {{
    $target = $appPath.'(default)'
    if (-not $target) {{ $target = $appPath.PSChildName }}
    Try-Launch "app-path" $target (Get-ProcessNameFromTarget $target)
}}

foreach ($command in $commands) {{
    Try-Launch "exact-command" $command.Source (Get-ProcessNameFromTarget $command.Source)
}}

if ($looksLikePathOrExe -and -not $commands) {{
    Try-Launch "direct-path" $query (Get-ProcessNameFromTarget $query)
}}

Write-Output "FAILED: app was not opened or verified for query: $query"
if ($attempts.Count) {{
    Write-Output "ATTEMPTS:"
    $attempts | Select-Object -First 20 | ForEach-Object {{ Write-Output "- $_" }}
}}
Write-Output 'DISCOVERED_MATCHES:'
$matches = Get-DiscoveredAppMatches
if ($matches.Count) {{
    $matches | Select-Object -First 20 | ForEach-Object {{ Write-Output "- $_" }}
}} else {{
    Write-Output '- none'
}}
Write-Output "FALLBACK_COMMAND: $fallbackCommand"
"""

    @classmethod
    def _app_discovery_command(cls, app: str) -> str:
        query = cls._ps(app.strip())
        return rf"""
$query = {query}
{cls._app_match_helpers()}
{cls._app_candidate_script()}
Write-Output "Dynamic app discovery for: $query"
$matches = Get-DiscoveredAppMatches
if ($matches.Count) {{
    $matches | Select-Object -First 30 | ForEach-Object {{ Write-Output "- $_" }}
}} else {{
    Write-Output '- no matches found'
}}
"""

    @staticmethod
    def _app_match_helpers() -> str:
        return r"""
function Normalize-AppText([string]$text) {
    if (-not $text) { return "" }
    $builder = New-Object System.Text.StringBuilder
    foreach ($char in $text.ToLowerInvariant().ToCharArray()) {
        if ([char]::IsLetterOrDigit($char)) { [void]$builder.Append($char) }
    }
    return $builder.ToString()
}

function Split-AppWords([string]$text) {
    $words = New-Object System.Collections.Generic.List[string]
    $builder = New-Object System.Text.StringBuilder
    foreach ($char in $text.ToLowerInvariant().ToCharArray()) {
        if ([char]::IsLetterOrDigit($char)) {
            [void]$builder.Append($char)
        } elseif ($builder.Length -gt 0) {
            $words.Add($builder.ToString())
            [void]$builder.Clear()
        }
    }
    if ($builder.Length -gt 0) { $words.Add($builder.ToString()) }
    return $words
}

function Test-AppMatch([string]$candidate, [string]$needle) {
    $candidateNorm = Normalize-AppText $candidate
    $needleNorm = Normalize-AppText $needle
    if (-not $candidateNorm -or -not $needleNorm) { return $false }
    if ($candidateNorm.Contains($needleNorm) -or $needleNorm.Contains($candidateNorm)) { return $true }

    $words = @(Split-AppWords $candidate)
    $acronymBuilder = New-Object System.Text.StringBuilder
    foreach ($word in $words) {
        if ($word.Length -gt 0) { [void]$acronymBuilder.Append($word.Substring(0, 1)) }
    }
    $acronym = $acronymBuilder.ToString()
    if ($acronym -and $needleNorm -eq $acronym) { return $true }

    foreach ($word in @(Split-AppWords $needle)) {
        if ($word.Length -ge 3 -and $candidateNorm.Contains($word)) { return $true }
    }
    return $false
}

function Get-ProcessNameFromTarget([string]$target) {
    if (-not $target) { return "" }
    $leaf = Split-Path -Leaf $target
    if (-not $leaf) { $leaf = $target.Split(" ")[0] }
    return [System.IO.Path]::GetFileNameWithoutExtension($leaf)
}

function Confirm-AppOpened([string]$method, [string]$target, [string]$expectedProcess) {
    Start-Sleep -Milliseconds 1800
    $newProcesses = @(Get-Process | Where-Object { $beforeProcessIds -notcontains $_.Id })

    if ($expectedProcess) {
        $existing = Get-Process -Name $expectedProcess -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
        if ($existing) {
            Write-Output "VERIFIED: app opened using $method`: $target (process: $($existing.ProcessName))"
            exit 0
        }
        $newExpected = $newProcesses | Where-Object { $_.ProcessName -eq $expectedProcess } | Select-Object -First 1
        if ($newExpected) {
            Write-Output "VERIFIED: app process started using $method`: $target (process: $($newExpected.ProcessName))"
            exit 0
        }
    }

    if (-not $expectedProcess) {
        $windowProcess = $newProcesses | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
        if ($windowProcess) {
            Write-Output "VERIFIED: app opened using $method`: $target (new window process: $($windowProcess.ProcessName))"
            exit 0
        }
    }
}
"""

    @staticmethod
    def _app_candidate_script() -> str:
        return r"""
$shortcutRoots = @(
    [Environment]::GetFolderPath("StartMenu"),
    [Environment]::GetFolderPath("CommonStartMenu"),
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("CommonDesktopDirectory")
) | Where-Object { $_ -and (Test-Path $_) }

$shortcuts = @(
    foreach ($root in $shortcutRoots) {
        Get-ChildItem -Path $root -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { Test-AppMatch $_.BaseName $query }
    }
) | Sort-Object { $_.BaseName.Length } -Unique | Select-Object -First 10

$shell = New-Object -ComObject WScript.Shell
$startApps = @(Get-StartApps -ErrorAction SilentlyContinue |
    Where-Object { (Test-AppMatch $_.Name $query) -or (Test-AppMatch $_.AppID $query) } |
    Sort-Object { $_.Name.Length } |
    Select-Object -First 10)

$appPathRoots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\*"
)

$appPaths = @(
    foreach ($root in $appPathRoots) {
        Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
            Where-Object { (Test-AppMatch (Split-Path -Leaf $_.PSChildName) $query) -or (Test-AppMatch $_.'(default)' $query) } |
            Select-Object -First 10
    }
) | Select-Object -First 10

$commands = @()
$queryWords = @(Split-AppWords $query)
$singleTokenQuery = $queryWords.Count -eq 1
$queryLower = $query.ToLowerInvariant()
$looksLikePathOrExe = $query.Contains(":") -or $query.Contains("\") -or $query.Contains("/") -or $queryLower.EndsWith(".exe")
if ($singleTokenQuery -or $looksLikePathOrExe) {
    $commands = @(Get-Command $query -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 4)
}

function Get-DiscoveredAppMatches {
    $matches = New-Object System.Collections.Generic.List[string]
    $commands | ForEach-Object { $matches.Add("command: $($_.Name) -> $($_.Source)") }
    $shortcuts | ForEach-Object { $matches.Add("shortcut: $($_.BaseName) -> $($_.FullName)") }
    $startApps | ForEach-Object { $matches.Add("start-app: $($_.Name) -> $($_.AppID)") }
    $appPaths | ForEach-Object { $matches.Add("app-path: $($_.PSChildName) -> $($_.'(default)')") }
    return $matches
}
"""
