param([string]$Name='LC34G55T', [string]$Start='0', [string]$Length='1000', [int]$Chunk=256, [string]$Out='')
Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { $_.Name -eq $Name } | select -First 1
if (-not $d) { "display $Name not found"; exit 1 }
[AmdIsp]::D = $d
$s=[Convert]::ToInt32($Start,16); $l=[Convert]::ToInt32($Length,16)
"enter -> " + [AmdIsp]::Enter(); Start-Sleep -Milliseconds 200
"jedec = " + [Amd]::Hex([AmdIsp]::Jedec())
$sw=[Diagnostics.Stopwatch]::StartNew()
try {
  $data = [AmdIsp]::Read($s, $l, $Chunk, [Action[int]]{ param($o) [Console]::Error.WriteLine(("  0x{0:X6} {1:N0}s" -f $o, $sw.Elapsed.TotalSeconds)) })
  "read 0x{0:X} bytes in {1:N1}s" -f $l, $sw.Elapsed.TotalSeconds
  if ($Out) { [IO.File]::WriteAllBytes($Out, $data); "saved " + $Out } else { "first 64: " + [Amd]::Hex($data[0..63]) }
} finally { "reset -> " + [AmdIsp]::Reset() }
