Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' } | select -First 1
function G { $p=[byte[]](0x51,0x82,0x01,0x10); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 80
  $r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r); [int]$r[9] }
function S($v) { for ($t=0; $t -lt 5; $t++) { $p=[byte[]](0x51,0x84,0x03,0x10,0,[byte]$v); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 150; if ((G) -eq $v) { return "ok" } }; "NOT CONFIRMED" }
"{0:HH:mm:ss.f} brightness -> 0: {1}" -f (Get-Date), (S 0)
Start-Sleep -Seconds 5
"{0:HH:mm:ss.f} brightness -> 99: {1}" -f (Get-Date), (S 99)
