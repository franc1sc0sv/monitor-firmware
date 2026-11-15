Add-Type -Path (Join-Path $PSScriptRoot '../../MonitorTools/AmdI2c.cs')
$all = [Amd]::Init(); $all | % { "$_" }
$g = $all | ? { "$_" -match 'Odyssey' } | select -First 1
"--- G5 via ADL: DDC/CI get 0x10"
$p=[byte[]](0x51,0x82,0x01,0x10); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
"write -> " + [Amd]::Block($g, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 120
$r=New-Object byte[] 11; "read  -> " + [Amd]::Block($g, [byte[]](0x6F), $r) + "  " + [Amd]::Hex($r)
foreach ($a in 0x50,0x49,0x59) { $x=New-Object byte[] 4; "probe read 0x{0:X2} -> {1} {2}" -f $a, [Amd]::Block($g, [byte[]]([byte]($a*2+1)), $x), [Amd]::Hex($x) }
"ISP enter (MSTAR) -> " + [Amd]::Block($g, [byte[]](0x92,0x4D,0x53,0x54,0x41,0x52), $null)
