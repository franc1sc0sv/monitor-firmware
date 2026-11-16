# READ-ONLY watcher for a real USB update: polls the updater/hand-off registers over DDC and prints every change with a
# timestamp (F190..F19F, F1E0, F1EB, 0xCF011F80). Run it, then start the update from the stick; Ctrl+C to stop.
# Uses stale-proof reads (a standard VCP query between F3 reads); keeps going when the monitor stops answering.
param([string]$Log = '')
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
$XB = [Convert]::ToUInt32('CF000000', 16)
$regs = [ordered]@{}
foreach ($x in 0xF190..0xF19F + 0xF1E0, 0xF1EB) { $regs[('X{0:X4}' -f $x)] = [UInt32]($XB + $x * 4) }
$regs['CF011F80'] = [Convert]::ToUInt32('CF011F80', 16)
$last = @{}; $t0 = Get-Date; $miss = 0
function Out1($s) { $l = ('{0,7:N1}s {1}' -f ((Get-Date) - $t0).TotalSeconds, $s); $l; if ($Log) { Add-Content -LiteralPath $Log -Value $l } }
Out1 'watch start'
while ($true) {
  foreach ($k in $regs.Keys) {
    if (-not (GetF 0x10 80)) { $miss++; if ($miss -eq 5) { Out1 'monitor not answering' }; Start-Sleep -Milliseconds 300; continue }
    if ($miss -ge 5) { Out1 'monitor answering again' }; $miss = 0
    SetAddr $regs[$k]; $m = GetF 0xF3 80
    if (-not $m) { continue }
    $v = [UInt32]$m[3] -bor ([UInt32]$m[2] -shl 8) -bor ([UInt32]$m[1] -shl 16) -bor ([UInt32]$m[0] -shl 24)
    if (-not $last.ContainsKey($k) -or $last[$k] -ne $v) { Out1 ('{0} = 0x{1:X2}' -f $k, $v); $last[$k] = $v }
  }
}
