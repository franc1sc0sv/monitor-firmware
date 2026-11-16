# G5 DDC flasher primitives (dev hook 1021.1+ with the 8051 POKE/PEEK patch). Dot-source after g5-ddc.ps1 and
# g5-final.ps1. Writes go through the stock 8051 routines; on this chip variant every 8051 flash op ends by setting
# F1A8 bit0, which resets the chip, so each Erase4K / Program256 call ends with a reboot (WaitBack waits for it).
# Reads/verification use the XIP window: flash F is visible at VA (F - 0x108000) mod 0x800000.
# HARD GUARD: only bank B [0x400000, 0x800000) may be erased/programmed, plus sector 0x7000 when -Activation is set.
$script:PUSH = [Convert]::ToUInt32('0015FEBC', 16)
$script:BUF = [Convert]::ToUInt32('A803C400', 16)
function FlashVa([UInt32]$f) { [UInt32](([UInt64]$f + 0x800000 - 0x108000) % 0x800000) }
function FlashRd32([UInt32]$f) { RdWF (FlashVa $f) }
function FlashRead([UInt32]$f, [int]$n) { $o = New-Object byte[] $n; for ($i = 0; $i -lt $n; $i += 4) { $w = [UInt64](FlashRd32 ([UInt32]($f + $i))); for ($k = 0; $k -lt 4 -and $i + $k -lt $n; $k++) { $o[$i + $k] = [byte](($w -shr (24 - 8 * $k)) -band 0xFF) } }; , $o }
function Guard([UInt32]$f, [switch]$Activation) {
  if ($Activation) { if (($f -band 0xFFFFF000) -ne 0x7000) { throw ("REFUSED: activation write outside sector 0x7000 (0x{0:X6})" -f $f) }; return }
  if ($f -lt 0x400000 -or $f -ge 0x800000) { throw ("REFUSED: 0x{0:X6} is not in bank B" -f $f) }
}
function WaitBack([int]$timeoutS = 90) {
  Start-Sleep -Seconds 8
  for ($t = 0; $t -lt $timeoutS; $t += 3) { try { $v = RdWF ([UInt32]0x245664); return $true } catch { Start-Sleep -Seconds 3 } }
  throw 'monitor did not come back'
}
function BaseOffsetList([UInt32]$f, [int]$lenPages, [int]$cmd) {
  $H = $script:HALMBOX; $base = $f -band 0xFFFF0000; $off = $f -band 0xFFFF
  @( @($H, 0x21, 0xA7, 0x57, (($base -shr 24) -band 0xFF), 1), @($H, 0x21, 0xA7, 0x58, (($base -shr 16) -band 0xFF), 1),
     @($H, 0x21, 0xA7, 0x59, (($base -shr 8) -band 0xFF), 1), @($H, 0x21, 0xA7, 0x5A, ($base -band 0xFF), 1),
     @($H, 0x14, $lenPages, (($off -shr 8) -band 0xFF), ($off -band 0xFF), 1), @($H, $cmd, 0, 0, 0, 2) )
}
function Erase4K([UInt32]$f, [switch]$Activation) {
  if ($f -band 0xFFF) { throw 'Erase4K needs a 4 KB-aligned address' }; Guard $f -Activation:$Activation
  $null = try { RunList (BaseOffsetList $f 1 0x13) } catch { }
  $null = WaitBack
  $chk = FlashRead $f 16; if (($chk | Where-Object { $_ -ne 0xFF }).Count) { throw ("erase verify failed at 0x{0:X6}" -f $f) }
}
function Program256([UInt32]$f, [byte[]]$data, [switch]$Activation) {
  if ($f -band 0xFF) { throw 'Program256 needs a 256-byte-aligned address' }; if ($data.Length -ne 256) { throw 'need 256 bytes' }
  Guard $f -Activation:$Activation
  Up $script:BUF $data
  $null = Call $script:PUSH @(0, 256, $script:BUF)
  $null = try { RunList (BaseOffsetList $f 1 0x11) } catch { }
  $null = WaitBack
  $back = FlashRead $f 256
  for ($i = 0; $i -lt 256; $i++) { if ($back[$i] -ne $data[$i]) { throw ("program verify failed at 0x{0:X6}: 0x{1:X2} want 0x{2:X2}" -f ($f + $i), $back[$i], $data[$i]) } }
}
