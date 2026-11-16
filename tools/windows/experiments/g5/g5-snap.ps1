# READ-ONLY snapshot of 32-bit words over DDC (dev hook 1019.0+, F3 word read).
# -Spec: comma list of "addr" or "start-end" (hex, runtime SPARC addresses; end exclusive); 8051 XDATA register X is
# at 0xCF000000 + X*4, so use -Xdata "F1D0-F1E1" for byte registers. Prints one line per word. Never writes.
param([string]$Spec = '', [string]$Xdata = '')
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
function RdW([UInt32]$a) {
  for ($t = 0; $t -lt 4; $t++) { SetAddr $a; $m = GetF 0xF3; if ($m) { return (([UInt32]$m[0] -shl 24) -bor ([UInt32]$m[1] -shl 16) -bor ([UInt32]$m[2] -shl 8) -bor [UInt32]$m[3]) } }
  return $null
}
function Ranges([string]$s) {
  foreach ($p in ($s -split ',' | Where-Object { $_ })) {
    $q = $p.Trim() -split '-'
    $a = [Convert]::ToUInt32($q[0], 16); $b = if ($q.Count -gt 1) { [Convert]::ToUInt32($q[1], 16) } else { $a + 1 }
    ,@($a, $b)
  }
}
foreach ($r in (Ranges $Spec)) {
  for ($a = $r[0]; $a -lt $r[1]; $a += 4) { $w = RdW $a; if ($null -eq $w) { "0x{0:X8} FAIL" -f $a } else { "0x{0:X8} {1:X8}" -f $a, $w } }
}
$XB = [Convert]::ToUInt32('CF000000', 16)
foreach ($r in (Ranges $Xdata)) {
  for ($x = $r[0]; $x -lt $r[1]; $x++) { $w = RdW ([UInt32]($XB + $x * 4)); if ($null -eq $w) { "X{0:X4} FAIL" -f $x } else { "X{0:X4} {1:X2}" -f $x, ($w -band 0xFF) } }
}
