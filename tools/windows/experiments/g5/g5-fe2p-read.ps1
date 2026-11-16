# READ-ONLY end-to-end proof of the SPARC -> 8051 -> flash path: calls the stock MailBox_LoadFE2P(offset16, len)
# (SPARC file VA 0x15E490 = 8051 mailbox cmd 0x14 "set FE2P address" + cmd 0x12 "read + checksum") through the dev
# hook's F5, then reads the mailbox reply words. WARNING (2026-11-16): the 1019.0 SLOTS (0xA8039A00) lie inside a live
# settings table in RAM; the FE2P load rewrites them (seen on hardware), so RESULT/TARG/ARG read back as settings bytes. Hard guard: the call target is a constant and is read back before F5.
param([int]$Offset = 0, [int]$Len = 0x10)
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
$TARGET = [UInt32]0x0015E490
$SL = [Convert]::ToUInt32('A8039A00', 16)
$MB = [Convert]::ToUInt32('9F0A0100', 16)
if ($Offset -lt 0 -or $Offset -gt 0xFFFF -or $Len -lt 1 -or $Len -gt 0xFF) { throw "bad args" }
function RdW([UInt32]$a) {
  for ($t = 0; $t -lt 4; $t++) { SetAddr $a; $m = GetF 0xF3; if ($m) { return (([UInt32]$m[0] -shl 24) -bor ([UInt32]$m[1] -shl 16) -bor ([UInt32]$m[2] -shl 8) -bor [UInt32]$m[3]) } }
  throw ("read failed at 0x{0:X8}" -f $a)
}
function Words($tag) { $o = foreach ($k in 0xB0, 0xB4, 0xB8, 0x00) { '+{0:X2}={1:X8}' -f $k, (RdW ($MB + $k)) }; "$tag mailbox " + ($o -join ' ') }
Words 'before'
# stage TARG, ARG0..ARG3 (big-endian, F4 auto-increments from SLOTS+4)
$vals = @($TARGET, [UInt32]$Offset, [UInt32]$Len, 0, 0)
SetAddr ($SL + 4)
foreach ($v in $vals) { foreach ($sh in 24, 16, 8, 0) { SetF 0xF4 0 ([byte](($v -shr $sh) -band 0xFF)) } }
for ($i = 0; $i -lt $vals.Count; $i++) {
  $got = RdW ($SL + 4 + 4 * $i)
  if ($got -ne [UInt32]$vals[$i]) { throw ("staging mismatch slot {0}: 0x{1:X8} want 0x{2:X8} -- NOT calling" -f $i, $got, $vals[$i]) }
}
if ((RdW ($SL + 4)) -ne $TARGET) { throw "target guard" }
"staged: target=0x{0:X8} offset=0x{1:X4} len=0x{2:X2}; calling F5" -f $TARGET, $Offset, $Len
SetF 0xF5 0 0
Start-Sleep -Milliseconds 2000
function RdW([UInt32]$a) { RdWF $a }   # after F5 the monitor is busy: use stale-proof reads
"RESULT=0x{0:X8} DELTA=0x{1:X8}" -f (RdW ($SL + 0x18)), (RdW ($SL + 0x20))
Words 'after '
