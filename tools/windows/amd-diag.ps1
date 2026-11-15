Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$ds = [Amd]::Init()
foreach ($d in $ds) {
  "=== " + $d
  # DDC/CI get VCP 0x60: write then read
  $p=[byte[]](0x51,0x82,0x01,0x60); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  "  ddc write -> " + [Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null)
  Start-Sleep -Milliseconds 50
  $r = New-Object byte[] 12
  "  ddc read  -> " + [Amd]::Block($d, [byte[]](0x6F), $r) + "  " + [Amd]::Hex($r)
  foreach ($a7 in 0x49,0x59,0x4A) { $x = New-Object byte[] 1
    "  probe read 0x{0:X2} -> {1} {2}" -f $a7, [Amd]::Block($d, [byte[]]([byte]($a7*2+1)), $x), [Amd]::Hex($x) }
}
