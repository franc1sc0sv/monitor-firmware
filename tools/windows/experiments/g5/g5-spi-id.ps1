# READ-ONLY SPI flash identification through the 8051's SPI command engine, driven from the SPARC dev hook (1019.0+).
# Replicates the 8051 runtime's own status-read primitive (segment A, 0xE876) with opcode 0x9F (JEDEC) / 0x05 (RDSR).
# 8051 XDATA register X is visible to the SPARC at 0xCF000000 + X*4 (byte register, 32-bit access).
#
# Hard guards (enforced below, not by convention):
#   - only the registers in $Allowed may be written; F0EE (opcode-only register, used for WREN etc.) is never touched
#   - the opcode register F0EA only accepts 0x9F / 0x05 (or its own saved value on restore)
#   - the start register F0E5 only accepts 2 (= opcode + read phase); 1 (opcode-only) is refused
#   - every staged value is read back before the write; original values are restored at the end, even on error
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')

$VALW = [Convert]::ToUInt32('A8039A24', 16)
$XBASE = [Convert]::ToUInt32('CF000000', 16)
function XA([int]$x) { [UInt32]($XBASE + [UInt32]($x * 4)) }
$R = @{ F1C0 = 0xF1C0; F0EA = 0xF0EA; F0E6 = 0xF0E6; F0EB = 0xF0EB; F0EC = 0xF0EC; F0ED = 0xF0ED; F0F4 = 0xF0F4; F0E5 = 0xF0E5; F0EF = 0xF0EF }
$Allowed = @(0xF1C0, 0xF0EA, 0xF0E6, 0xF0EB, 0xF0EC, 0xF0ED, 0xF0F4, 0xF0E5)

function RdW([UInt32]$a) {
  for ($t = 0; $t -lt 4; $t++) { SetAddr $a; $m = GetF 0xF3; if ($m) { return (([UInt32]$m[0] -shl 24) -bor ([UInt32]$m[1] -shl 16) -bor ([UInt32]$m[2] -shl 8) -bor [UInt32]$m[3]) } }
  throw ("read failed at 0x{0:X8}" -f $a)
}
function RdX([int]$x) { (RdW (XA $x)) -band 0xFF }
function WrX([int]$x, [int]$v, [switch]$Restore) {
  if ($Allowed -notcontains $x) { throw ("REFUSED: register {0:X4} not allowed" -f $x) }
  if ($x -eq 0xF0EA -and -not $Restore -and @(0x9F, 0x05) -notcontains $v) { throw ("REFUSED: opcode {0:X2}" -f $v) }
  if ($x -eq 0xF0E5 -and $v -ne 2) { throw ("REFUSED: start value {0:X2}" -f $v) }
  SetAddr $VALW; SetF 0xF4 0 0; SetF 0xF4 0 0; SetF 0xF4 0 0; SetF 0xF4 0 ([byte]$v)
  $s = RdW $VALW
  if ($s -ne [UInt32]$v) { throw ("staging mismatch: VALW=0x{0:X8} want 0x{1:X2}" -f $s, $v) }
  SetAddr (XA $x); SetF 0xF6 0 0
}

$orig = @{}
foreach ($k in 'F1C0', 'F0EA', 'F0E6', 'F0EB', 'F0EC', 'F0ED', 'F0F4', 'F0EF', 'F0E5') { $orig[$k] = RdX $R[$k] }
"before: " + (($orig.GetEnumerator() | Sort-Object Name | ForEach-Object { '{0}={1:X2}' -f $_.Name, $_.Value }) -join ' ')
if (($orig['F0E5'] -band 3) -ne 0) { "engine busy (F0E5=0x{0:X2}); abort" -f $orig['F0E5']; exit 2 }

try {
  foreach ($op in 0x9F, 0x05, 0x9F) {
    WrX 0xF1C0 0
    WrX 0xF0EA $op
    WrX 0xF0E6 (($orig['F0E6'] -band 0x0C) -bor 0x41)
    WrX 0xF0EB 0; WrX 0xF0EC 0; WrX 0xF0ED 0
    WrX 0xF0F4 7
    WrX 0xF0E5 2
    $busy = $true
    for ($i = 0; $i -lt 20; $i++) { $st = RdX 0xF0E5; if (($st -band 2) -eq 0) { $busy = $false; break } }
    $res = RdX 0xF0EF
    "op 0x{0:X2}: result F0EF=0x{1:X2}  (F0E5 after=0x{2:X2}{3})" -f $op, $res, $st, $(if ($busy) { ' STILL BUSY' } else { '' })
  }
}
finally {
  foreach ($k in 'F0F4', 'F0ED', 'F0EC', 'F0EB', 'F0EA', 'F0E6', 'F1C0') { try { WrX $R[$k] $orig[$k] -Restore } catch { "restore $k failed: $_" } }
  $after = @{}; foreach ($k in 'F1C0', 'F0EA', 'F0E6', 'F0EB', 'F0EC', 'F0ED', 'F0F4', 'F0E5') { $after[$k] = RdX $R[$k] }
  "after:  " + (($after.GetEnumerator() | Sort-Object Name | ForEach-Object { '{0}={1:X2}' -f $_.Name, $_.Value }) -join ' ')
}
