# Reads the patched firmware's event log over ADL (VCP 0xEA..0xEF). See docs/protocol/vcp-interface.md.
param([int]$Last = 40, [switch]$Watch, [int]$Seconds = 0)
Import-Module (Join-Path $PSScriptRoot "MonitorTools/MonitorTools.psm1") -Force
$d = Get-MonitorDisplay
$names = @{ 0='boot'; 1='input-port'; 2='source-select'; 3='power-flags'; 4='powersave-flags'; 5='sync-flags'; 6='signal'
  7='system-state'; 8='window-port'; 0x10='ddc-switch-request'; 0x11='switch-done'; 0x12='switch-FAILED'; 0x13='ddc-power-request'
  0x20='setting-changed'; 0x21='setting-changed' }
function Read-Event([int]$seq) {
  for ($t = 0; $t -lt 4; $t++) {
    [void](Set-Vcp -Display $d -Code 0xEB -Value $seq)
    $e = Get-Vcp -Display $d -Code 0xEC; $tm = Get-Vcp -Display $d -Code 0xED
    if ($e -and $tm -and $e.cl -eq ($seq -band 0xFF) -and $tm.mh -eq ($seq -band 0xFF)) {
      $ts = ($tm.ml -shl 16) -bor ($tm.ch -shl 8) -bor $tm.cl
      $n = $names[[int]$e.mh]; if (-not $n) { $n = ('id 0x{0:X2}' -f $e.mh) }
      return ('#{0,-5} t={1,9:N2}s  {2,-20} old=0x{3:X2} new=0x{4:X2}' -f $seq, ($ts / 100.0), $n, $e.ml, $e.ch) } }
  return ('#{0,-5} (read failed)' -f $seq) }
$info = Get-Vcp -Display $d -Code 0xEA
if (-not $info) { "no reply to VCP 0xEA"; exit 1 }
if ($info.rc -ne 0) { "VCP 0xEA unsupported (rc=$($info.rc)): stock firmware?"; exit 1 }
$seq = $info.current
$now = Get-Vcp -Display $d -Code 0xEF
"event log v{0}, ring {1}, events so far {2}, monitor clock {3:N2}s" -f $info.ml, $info.mh, $seq, ((($now.mh -shl 24) -bor ($now.ml -shl 16) -bor $now.current) / 100.0)
$first = [Math]::Max(1, $seq - [Math]::Min($Last, $info.mh) + 1)
for ($s = $first; $s -le $seq; $s++) { Read-Event $s }
if ($Watch) {
  $t0 = Get-Date; $lastSeq = $seq
  while ($Seconds -eq 0 -or ((Get-Date) - $t0).TotalSeconds -lt $Seconds) {
    Start-Sleep -Milliseconds 300
    $i = Get-Vcp -Display $d -Code 0xEA; if (-not $i) { continue }
    while ($lastSeq -ne $i.current) { $lastSeq = ($lastSeq + 1) -band 0xFFFF; Read-Event $lastSeq } } }
