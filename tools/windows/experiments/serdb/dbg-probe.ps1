Add-Type -Path (Join-Path $PSScriptRoot '../../MonitorTools/AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
function W([byte[]]$b) { [Amd]::Block($d, [byte[]](@(0xB2)+$b), $null) }
function ReadDbg([int]$n) { $r=New-Object byte[] $n; $s=[Amd]::Block($d, [byte[]](0xB3), $r); "s=$s " + [Amd]::Hex($r) }
"enter SERDB: " + (W ([byte[]](0x53,0x45,0x52,0x44,0x42)))
foreach ($fmt in @(@(0x10,0x1E,0x00), @(0x10,0x1E,0x01), @(0x10,0x10,0x1E,0x00), @(0x10,0x00,0x10,0x1E,0x00), @(0x10,0x00,0x00))) {
  $w = W ([byte[]]$fmt); "read [" + (($fmt | % { '{0:X2}' -f $_ }) -join ' ') + "] w=$w -> " + (ReadDbg 2) }
"exit: " + (W ([byte[]](0x45)))
"ddc after:"; $p=[byte[]](0x51,0x82,0x01,0x10); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
[void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 150
$r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r); [Amd]::Hex($r)
