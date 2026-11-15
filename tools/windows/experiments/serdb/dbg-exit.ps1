Add-Type -Path (Join-Path $PSScriptRoot '../../MonitorTools/AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
foreach ($c in 0x36,0x34,0x45) { "0xB2 <- {0:X2}: {1}" -f $c, [Amd]::Block($d, [byte[]](0xB2,[byte]$c), $null) }
