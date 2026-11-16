# In-chip DRAM search for the staged update file header ("\x7FNVT") with dev hook 1020.3+ (F7). READ-ONLY on DRAM
# (writes only the DRAM-port address/trigger registers and the hook slots). Each F7 call scans -Chunk probes.
param([string]$From = '0', [string]$To = '1000000', [string]$Stride = '1', [string]$Chunk = '4000')
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
$SL = [Convert]::ToUInt32('A803CFC0', 16)
function Stage([UInt32[]]$w) { SetAddr ([UInt32]($SL + 8)); foreach ($v in $w) { foreach ($sh in 24, 16, 8, 0) { SetF 0xF4 0 ([byte](($v -shr $sh) -band 0xFF)) } } }
$f = [Convert]::ToUInt32($From, 16); $t = [Convert]::ToUInt32($To, 16); $s = [Convert]::ToUInt32($Stride, 16); $c = [Convert]::ToUInt32($Chunk, 16)
$line = $f; $t0 = Get-Date
while ($line -lt $t) {
  $n = [Math]::Min([double]$c, [Math]::Ceiling(($t - $line) / [double]$s))
  Stage @([UInt32]$line, [UInt32]$n, [UInt32]$s)
  $chk = RdWF ([UInt32]($SL + 8)); if ($chk -ne $line) { throw ("ARG0 staging mismatch 0x{0:X8} want 0x{1:X8}" -f $chk, $line) }
  SetF 0xF7 0 0; Start-Sleep -Milliseconds 300
  $res = RdWF ([UInt32]($SL + 0x18)); $next = RdWF ([UInt32]($SL + 8)); $last = RdWF ([UInt32]($SL + 0x20))
  "{0,6:N0}s lines 0x{1:X8}..0x{2:X8} result=0x{3:X8} lastword=0x{4:X8}" -f ((Get-Date) - $t0).TotalSeconds, $line, $next, $res, $last
  if ($res -ne [UInt32]::MaxValue) { "FOUND header at line 0x{0:X8} (byte 0x{1:X})" -f $res, ([UInt64]$res * 32); break }
  $line = [UInt32]($next)
  if ($next -le $line -and $res -eq [UInt32]::MaxValue -and $n -gt 0) { }
}
