param([int]$Last=40, [switch]$Watch, [int]$Seconds=0)
Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' } | select -First 1
function Get-Vcp([int]$code) {
  for ($t=0; $t -lt 6; $t++) {
    $p=[byte[]](0x51,0x82,0x01,[byte]$code); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
    [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 60
    $r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r)
    # valid reply: 6E 88 02 RC VCP TP MH ML CH CL CHK, checksum = XOR of 0x50 and bytes 1..9 ... (source 0x6E counted as 0x50 virtual host)
    $x = 0x50 -bxor 0x6E; for ($i=1; $i -le 9; $i++) { $x = $x -bxor $r[$i] }
    if ($r[0] -eq 0x6E -and $r[1] -eq 0x88 -and $r[2] -eq 0x02 -and $r[4] -eq $code -and $x -eq $r[10]) {
      return [pscustomobject]@{ rc=[int]$r[3]; mh=[int]$r[6]; ml=[int]$r[7]; ch=[int]$r[8]; cl=[int]$r[9] } }
    Start-Sleep -Milliseconds 40 }
  return $null }
function Set-Vcp([int]$code, [int]$val) {
  $p=[byte[]](0x51,0x84,0x03,[byte]$code,[byte](($val -shr 8) -band 0xFF),[byte]($val -band 0xFF)); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 60 }
$names = @{ 0='boot'; 1='input-port'; 2='source-select'; 3='power-flags'; 4='powersave-flags'; 5='sync-flags'; 6='signal'; 7='system-state'; 8='window-port';
            0x10='ddc-switch-request'; 0x11='switch-done'; 0x12='switch-FAILED'; 0x13='ddc-power-request' }
function Read-Event([int]$seq) {
  for ($t=0; $t -lt 4; $t++) {
    Set-Vcp 0xEB $seq
    $e = Get-Vcp 0xEC; $tm = Get-Vcp 0xED
    if ($e -and $tm -and $e.cl -eq ($seq -band 0xFF) -and $tm.mh -eq ($seq -band 0xFF)) {
      $ts = ($tm.ml -shl 16) -bor ($tm.ch -shl 8) -bor $tm.cl
      $n = $names[[int]$e.mh]; if (-not $n) { $n = ('id 0x{0:X2}' -f $e.mh) }
      return ('#{0,-5} t={1,9:N2}s  {2,-20} old=0x{3:X2} new=0x{4:X2}' -f $seq, ($ts/100.0), $n, $e.ml, $e.ch) } }
  return ('#{0,-5} (read failed)' -f $seq) }
$info = Get-Vcp 0xEA
if (-not $info) { "no reply to VCP 0xEA (event log not present?)"; exit 1 }
if ($info.rc -ne 0) { "VCP 0xEA unsupported (rc={0}) - stock firmware?" -f $info.rc; exit 1 }
$seq = ($info.ch -shl 8) -bor $info.cl
$now = Get-Vcp 0xEF; $nowt = (($now.mh -shl 24) -bor ($now.ml -shl 16) -bor ($now.ch -shl 8) -bor $now.cl) / 100.0
$live = Get-Vcp 0xEE
"event log v{0}, ring {1}, events so far {2}, monitor clock {3:N2}s" -f $info.ml, $info.mh, $seq, $nowt
"live: input-port={0} source-select=0x{1:X2} power-flags=0x{2:X2} signal={3}" -f $live.mh, $live.ml, $live.ch, $live.cl
$first = [Math]::Max(1, $seq - [Math]::Min($Last, $info.mh) + 1)
for ($s = $first; $s -le $seq; $s++) { Read-Event $s }
if ($Watch) {
  $t0 = Get-Date; $lastSeq = $seq
  while ($Seconds -eq 0 -or ((Get-Date)-$t0).TotalSeconds -lt $Seconds) {
    Start-Sleep -Milliseconds 300
    $i = Get-Vcp 0xEA; if (-not $i) { continue }
    $cur = ($i.ch -shl 8) -bor $i.cl
    while ($lastSeq -ne $cur) { $lastSeq = ($lastSeq + 1) -band 0xFFFF; Read-Event $lastSeq } } }
