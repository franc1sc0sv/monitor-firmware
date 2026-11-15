param([int]$Seconds=60)
Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
Add-Type -Path (Join-Path $PSScriptRoot 'Dxva.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
function AmdGet($code) { $p=[byte[]](0x51,0x82,0x01,[byte]$code); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 150
  $r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r); [Amd]::Hex($r) }
function AmdSet($code,$val) { $p=[byte[]](0x51,0x84,0x03,[byte]$code,0,[byte]$val); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null) }
"set 60=9 via HDMI -> " + (AmdSet 0x60 9); $t0 = Get-Date
while (((Get-Date)-$t0).TotalSeconds -lt $Seconds) { Start-Sleep -Seconds 5
  $g = AmdGet 0x60; $b = AmdGet 0x10
  "t+{0,3:N0}s HDMI 60: {1} | 10: {2}" -f ((Get-Date)-$t0).TotalSeconds, $g, $b }
$dp = [Dxva]::All() | ? { [Dxva]::Get($_.h,0x10) -match 'max=0x64' -and [Dxva]::Get($_.h,0x60) -match 'cur=0x09' } | select -First 1
if ($dp) { "back via DP -> " + [Dxva]::SetVCPFeature($dp.h, 0x60, 6) } else { "DP handle not found, back via HDMI -> " + (AmdSet 0x60 6) }
Start-Sleep -Seconds 6; "after return HDMI 60: " + (AmdGet 0x60)
