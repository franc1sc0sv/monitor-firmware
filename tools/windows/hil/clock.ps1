# HIL: samples the firmware clock (VCP 0xEF, 10 ms units) against the host for ~10 s; expect ~100 per second.
Import-Module (Join-Path $PSScriptRoot "../MonitorTools/MonitorTools.psm1") -Force
$d = Get-MonitorDisplay; $t0 = Get-Date; $first = $null
for ($k = 0; $k -lt 20; $k++) {
  $r = Get-Vcp -Display $d -Code 0xEF
  if ($r) { $v = ($r.mh -shl 24) -bor ($r.ml -shl 16) -bor $r.current; if ($null -eq $first) { $first = $v; $h0 = Get-Date }
    "{0,6:N2}s host  clock={1}  rate={2:N1}/s" -f ((Get-Date) - $t0).TotalSeconds, $v, (($v - $first) / [Math]::Max(0.001, ((Get-Date) - $h0).TotalSeconds)) }
  Start-Sleep -Milliseconds 400 }
