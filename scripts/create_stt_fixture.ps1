# Generate a reproducible, synthetic six-second speech fixture entirely offline.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$fixtureRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tests\fixtures'))
[IO.Directory]::CreateDirectory($fixtureRoot) | Out-Null
$fixturePath = Join-Path $fixtureRoot 'stt-six-seconds.wav'
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female, [System.Speech.Synthesis.VoiceAge]::Adult, 0, [Globalization.CultureInfo]::GetCultureInfo('en-US'))
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $voice.SetOutputToWaveFile($fixturePath, $format)
    $voice.Speak('Hello Ankita. Please tell me what time it is.')
} finally {
    $voice.Dispose()
}
$sourceWave = [IO.File]::ReadAllBytes($fixturePath)
$chunkOffset = 12
$speechBytes = $null
while ($chunkOffset + 8 -le $sourceWave.Length) {
    $chunkName = [Text.Encoding]::ASCII.GetString($sourceWave, $chunkOffset, 4)
    $chunkLength = [BitConverter]::ToInt32($sourceWave, $chunkOffset + 4)
    if ($chunkName -eq 'data') {
        $speechBytes = New-Object byte[] $chunkLength
        [Array]::Copy($sourceWave, $chunkOffset + 8, $speechBytes, 0, $chunkLength)
        break
    }
    $chunkOffset += 8 + $chunkLength + ($chunkLength % 2)
}
$targetBytes = 6 * 16000 * 2
if ($null -eq $speechBytes -or $speechBytes.Length -gt $targetBytes) {
    throw 'Generated speech must fit within six seconds.'
}
$padded = New-Object byte[] $targetBytes
[Array]::Copy($speechBytes, $padded, $speechBytes.Length)
$writer = New-Object IO.BinaryWriter([IO.File]::Create($fixturePath))
try {
    $writer.Write([Text.Encoding]::ASCII.GetBytes('RIFF'))
    $writer.Write([int](36 + $targetBytes))
    $writer.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt '))
    $writer.Write([int]16)
    $writer.Write([int16]1)
    $writer.Write([int16]1)
    $writer.Write([int]16000)
    $writer.Write([int]32000)
    $writer.Write([int16]2)
    $writer.Write([int16]16)
    $writer.Write([Text.Encoding]::ASCII.GetBytes('data'))
    $writer.Write([int]$targetBytes)
    $writer.Write($padded)
} finally {
    $writer.Dispose()
}
Write-Output $fixturePath
