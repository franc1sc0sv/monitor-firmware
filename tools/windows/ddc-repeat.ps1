Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
foreach ($code in 0x10,0x60,0xD6,0x60,0x10) { foreach ($delay in 50,150) {
  $p=[byte[]](0x51,0x82,0x01,[byte]$code); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  $w=[Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds $delay
  $r=New-Object byte[] 11; $rr=[Amd]::Block($d, [byte[]](0x6F), $r)
  "vcp 0x{0:X2} delay {1}: w={2} r={3} {4}" -f $code,$delay,$w,$rr,[Amd]::Hex($r); Start-Sleep -Milliseconds 100 } }
