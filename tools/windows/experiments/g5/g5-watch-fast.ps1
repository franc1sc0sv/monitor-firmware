# READ-ONLY fast watcher for a USB update: tight loop over the USB-Cop registers that carry the staged file location /
# size (F190 status, F191 cmd, F198 handshake, F19B..F19E data) plus F1E0. No per-read VCP flush (speed); a reading is
# logged only when it differs from the last one for that register, together with the sweep number, so stale frames
# show up as runs of identical values across registers. Writes a CSV-like log; Ctrl+C / timeout to stop.
param([string]$Log = '', [int]$Ms = 40)
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
$XB = [Convert]::ToUInt32('CF000000', 16)
$regs = [ordered]@{}
foreach ($x in 0xF190, 0xF191, 0xF198, 0xF19B, 0xF19C, 0xF19D, 0xF19E, 0xF1E0) { $regs[('X{0:X4}' -f $x)] = [UInt32]($XB + $x * 4) }
$last = @{}; $t0 = Get-Date; $sweep = 0; $dead = 0
function Out1($s) { $l = ('{0,8:N2}s #{1} {2}' -f ((Get-Date) - $t0).TotalSeconds, $sweep, $s); $l; if ($Log) { Add-Content -LiteralPath $Log -Value $l } }
Out1 'fast watch start'
while ($true) {
  $sweep++; $got = 0
  foreach ($k in $regs.Keys) {
    SetAddr $regs[$k]; $m = GetF 0xF3 $Ms
    if (-not $m) { continue }
    $got++; $v = [UInt32]$m[3]
    if (-not $last.ContainsKey($k) -or $last[$k] -ne $v) { Out1 ('{0} = 0x{1:X2}' -f $k, $v); $last[$k] = $v }
  }
  if ($got -eq 0) { $dead++; if ($dead -eq 3) { Out1 'no replies' }; Start-Sleep -Milliseconds 200 } else { if ($dead -ge 3) { Out1 'replies again' }; $dead = 0 }
}
