param([int]$Ch=3, [string]$Start='1E00', [int]$Count=16, [int]$Width=4, [int]$Reps=2, [switch]$Comb, [switch]$NoSetup)
Add-Type -Path (Join-Path $PSScriptRoot '../../MonitorTools/AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
function W([byte[]]$b) { [Amd]::Block($d, [byte[]](@(0xB2)+$b), $null) }
function ReadDbg([int]$n) { $r=New-Object byte[] $n; [void][Amd]::Block($d, [byte[]](0xB3), $r); $r }
[void](W ([byte[]](0x53,0x45,0x52,0x44,0x42)))
if (-not $NoSetup) { foreach ($c in @($(if($Ch -band 1){0x81}else{0x80}), $(if($Ch -band 2){0x83}else{0x82}), $(if($Ch -band 4){0x85}else{0x84}), 0x53, 0x7F, 0x35, 0x71)) { [void](W ([byte[]]@($c))) } }
$s=[Convert]::ToUInt32($Start,16); $line=''
for ($i=0; $i -lt $Count; $i++) { $a=$s+$i
  if ($Width -eq 2) { $cmd=[byte[]](0x10,[byte](($a -shr 8) -band 0xFF),[byte]($a -band 0xFF)) }
  else { $cmd=[byte[]](0x10,[byte](($a -shr 24) -band 0xFF),[byte](($a -shr 16) -band 0xFF),[byte](($a -shr 8) -band 0xFF),[byte]($a -band 0xFF)) }
  $vals=@(); for($k=0;$k -lt $Reps;$k++){ if ($Comb) { $r=New-Object byte[] 1; [void][Amd]::Block($d, [byte[]](@(0xB2)+$cmd), $r); $vals += $r[0] } else { [void](W $cmd); $vals += (ReadDbg 1)[0] } }
  $same = ($vals | Select-Object -Unique).Count -eq 1
  $line += ('{0:X2}{1} ' -f $vals[0], $(if($same){''}else{'*'}))
  if ((($i+1) % 16) -eq 0) { ('{0:X8}: ' -f ($a-15)) + $line; $line='' } }
if ($line) { $line }
[void](W ([byte[]](0x34))); [void](W ([byte[]](0x45)))
