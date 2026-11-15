Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' } | select -First 1
function Get-Vcp([int]$code) {
  for ($t=0; $t -lt 6; $t++) {
    $p=[byte[]](0x51,0x82,0x01,[byte]$code); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
    [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 60
    $r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r)
    $x = 0x50 -bxor 0x6E; for ($i=1; $i -le 9; $i++) { $x = $x -bxor $r[$i] }
    if ($r[0] -eq 0x6E -and $r[1] -eq 0x88 -and $r[4] -eq $code -and $x -eq $r[10]) { return $r } }
  return $null }
$t0 = Get-Date
for ($k=0; $k -lt 20; $k++) {
  $r = Get-Vcp 0xEF
  $v = if ($r) { ($r[6] -shl 24) -bor ($r[7] -shl 16) -bor ($r[8] -shl 8) -bor $r[9] } else { -1 }
  "{0,6:N2}s host  clock={1} raw={2}" -f ((Get-Date)-$t0).TotalSeconds, $v, $(if ($r) { [Amd]::Hex($r) } else { 'none' })
  Start-Sleep -Milliseconds 400 }
