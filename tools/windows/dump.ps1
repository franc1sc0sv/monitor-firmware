# Reads the monitor's SPI flash through MStar ISP over AMD ADL. Dump twice and compare hashes before trusting it.
param([string]$Start = '0', [string]$Length = '800000', [int]$Chunk = 256, [string]$Out = '')
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MonitorTools/MonitorTools.psm1') -Force
$d = Get-MonitorDisplay
$s = [Convert]::ToInt32($Start, 16); $l = [Convert]::ToInt32($Length, 16)
"jedec = " + [Amd]::Hex((Enter-Isp $d))
$sw = [Diagnostics.Stopwatch]::StartNew(); $ok = $false
try {
  $data = [AmdIsp]::Read($s, $l, $Chunk, [Action[int]] { param($o) [Console]::Error.WriteLine(("  0x{0:X6} {1:N0}s" -f $o, $sw.Elapsed.TotalSeconds)) })
  "read 0x{0:X} bytes in {1:N1}s" -f $l, $sw.Elapsed.TotalSeconds
  if ($Out) { [IO.File]::WriteAllBytes($Out, $data); "saved $Out  sha256 " + (Get-FileSha256 $Out) } else { "first 64: " + [Amd]::Hex($data[0..63]) }
  $ok = $true
} finally { "reset -> " + (Exit-Isp) }
if (-not $ok) { exit 1 }
