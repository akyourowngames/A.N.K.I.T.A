# Test-only Win32 path alias discovery. Read the target from the child process
# environment so no user-controlled path is interpolated into shell source.
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class AnkitaTestShortPath {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    public static extern uint GetShortPathName(string path, StringBuilder result, uint capacity);
}
'@
$aliasBuffer = New-Object System.Text.StringBuilder 4096
$aliasLength = [AnkitaTestShortPath]::GetShortPathName($env:ANKITA_TEST_ALIAS_FILE, $aliasBuffer, $aliasBuffer.Capacity)
if ($aliasLength -eq 0 -or $aliasLength -ge $aliasBuffer.Capacity) { exit 1 }
Write-Output $aliasBuffer.ToString()
