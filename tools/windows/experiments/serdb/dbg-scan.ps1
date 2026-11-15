param([string]$Fmt='3', [string]$Start='1E00', [int]$Count=32)
Add-Type -Path (Join-Path $PSScriptRoot '../../MonitorTools/AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
function W([byte[]]$b) { [Amd]::Block($d, [byte[]](@(0xB2)+$b), $null) }
function ReadDbg([int]$n) { $r=New-Object byte[] $n; [void][Amd]::Block($d, [byte[]](0xB3), $r); $r }
[void](W ([byte[]](0x53,0x45,0x52,0x44,0x42)))
$s=[Convert]::ToUInt32($Start,16); $line=''
for ($i=0; $i -lt $Count; $i++) { $a=$s+$i
  if ($Fmt -eq '3') { $cmd=[byte[]](0x10,[byte](($a -shr 8) -band 0xFF),[byte]($a -band 0xFF)) }
  else { $cmd=[byte[]](0x10,[byte](($a -shr 16) -band 0xFF),[byte](($a -shr 8) -band 0xFF),[byte]($a -band 0xFF)) }
  [void](W $cmd); $v1=(ReadDbg 1)[0]; [void](W $cmd); $v2=(ReadDbg 1)[0]
  $line += ('{0:X2}{1} ' -f $v1, $(if($v1 -ne $v2){'*'}else{''}))
  if ((($i+1) % 16) -eq 0) { ('{0:X6}: ' -f ($a-15)) + $line; $line='' } }
if ($line) { $line }
[void](W ([byte[]](0x45)))
