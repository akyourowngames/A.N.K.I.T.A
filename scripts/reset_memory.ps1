param(
    [string]$DataRoot = (Join-Path $env:USERPROFILE '.zumba'),
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$memoryRoot = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
if ($memoryRoot -eq [IO.Path]::GetPathRoot($memoryRoot).TrimEnd('\')) { throw 'Refusing a drive root.' }

function Assert-WithinRoot([string]$Target, [string]$Root) {
    $absolute = [IO.Path]::GetFullPath($Target)
    if (-not $absolute.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes approved root: $absolute"
    }
    $check = $absolute
    while ($check.Length -ge $Root.Length) {
        if ((Test-Path -LiteralPath $check) -and ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing a linked path: $check"
        }
        $check = [IO.Path]::GetDirectoryName($check)
    }
    return $absolute
}

$targets = [Collections.Generic.List[string]]::new()
foreach ($name in @('memory.db','memory-inbox.db','vault.db','ChatLog.json','ChatLog.lock')) {
    foreach ($suffix in @('','-wal','-shm','-journal')) {
        $targets.Add((Assert-WithinRoot (Join-Path $memoryRoot ($name + $suffix)) $memoryRoot))
    }
}
foreach ($name in @('user.md','soul.md','soul.proposed.md','shell_audit.log','fs_audit.log','knowledge','webcache','tg_audio')) {
    $targets.Add((Assert-WithinRoot (Join-Path $memoryRoot $name) $memoryRoot))
}
if (Test-Path -LiteralPath $memoryRoot) {
    foreach ($file in Get-ChildItem -LiteralPath $memoryRoot -File -Filter 'ChatLog-*.tmp') {
        $targets.Add((Assert-WithinRoot $file.FullName $memoryRoot))
    }
}
foreach ($directory in @('sessions','core\sessions')) {
    $sessionRoot = Assert-WithinRoot (Join-Path $workspaceRoot $directory) $workspaceRoot
    if (Test-Path -LiteralPath $sessionRoot) {
        foreach ($file in Get-ChildItem -LiteralPath $sessionRoot -File -Filter '*.json') {
            $targets.Add((Assert-WithinRoot $file.FullName $workspaceRoot))
        }
    }
}
$artifacts = Join-Path $workspaceRoot '.artifacts'
if (Test-Path -LiteralPath $artifacts) {
    foreach ($file in Get-ChildItem -LiteralPath $artifacts -File -Filter 'knowledge-*.png') {
        $targets.Add((Assert-WithinRoot $file.FullName $workspaceRoot))
    }
}
# Old test snapshots can contain copies of the real memory database.
foreach ($directory in Get-ChildItem -LiteralPath $workspaceRoot -Directory -Force -Filter '.test-tmp-*') {
    $targets.Add((Assert-WithinRoot $directory.FullName $workspaceRoot))
}
$existing = @($targets | Where-Object { Test-Path -LiteralPath $_ })
$existing | ForEach-Object { Write-Output "Erase: $_" }
$appDatabase = Assert-WithinRoot (Join-Path $memoryRoot 'zumba.db') $memoryRoot
Write-Output "Clear conversation/execution/location rows: $appDatabase"
if (-not $Apply) { Write-Output 'Preview only. Stop Zumba, then pass -Apply to erase.'; exit 0 }

& rtk proxy python (Join-Path $PSScriptRoot 'reset_chat_database.py') $appDatabase
if ($LASTEXITCODE -ne 0) { throw 'Database reset failed; file cleanup has not run.' }
$failed = [Collections.Generic.List[string]]::new()
foreach ($target in $existing) {
    try { Remove-Item -LiteralPath $target -Recurse -Force }
    catch { $failed.Add($target); Write-Warning "Could not erase: $target" }
}
$remaining = @($existing | Where-Object { Test-Path -LiteralPath $_ })
if ($remaining.Count -or $failed.Count) { throw "Live database reset completed. File cleanup incomplete: $($failed -join ', ')" }
Write-Output "Reset verified: $($existing.Count) memory files/directories removed. Credentials and connection settings preserved."
