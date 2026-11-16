# Host library for the 1021.0 final hook. Dot-source after g5-ddc.ps1.
#   Up([UInt32]addr, [byte[]]data)   upload into the window [0xA803C400, 0xA803CFE8) (2 bytes per frame; pads odd)
#   Call([UInt32]target, args[0..4]) absolute call (runtime address), returns RESULT
#   Mbox(cmd,b1,b2,b3,mode)          HAL mailbox to the 8051 (nominal 0xA002EF00 = runtime 0xA002F220)
#   Poke51([int]xaddr,[byte]v) / Peek51([int]xaddr)   8051 XDATA via the patched mailbox cmds 0x21 / 0x03
$script:SLF = [Convert]::ToUInt32('A803CFC0', 16)
$script:HALMBOX = [Convert]::ToUInt32('A002F220', 16)
$script:MBOX = [Convert]::ToUInt32('9F0A0100', 16)
function Up([UInt32]$addr, [byte[]]$data) {
  if ($data.Length % 2) { $data = $data + [byte]0 }
  SetAddr $addr
  for ($i = 0; $i -lt $data.Length; $i += 2) { SetF 0xF4 $data[$i] $data[$i + 1] }
  $end = RdWF $script:SLF; if ($end -ne [UInt32]($addr + $data.Length)) { throw ("upload ended at 0x{0:X8}, want 0x{1:X8}" -f $end, ($addr + $data.Length)) }
}
function W32([UInt32]$v) { [byte[]](($v -shr 24) -band 0xFF, ($v -shr 16) -band 0xFF, ($v -shr 8) -band 0xFF, $v -band 0xFF) }
function Call([UInt32]$target, [UInt32[]]$a) {
  $buf = @(); $buf += W32 $target; for ($k = 0; $k -lt 5; $k++) { $buf += W32 ($(if ($k -lt $a.Count) { $a[$k] } else { 0 })) }
  Up ([UInt32]($script:SLF + 4)) ([byte[]]$buf)
  if ((RdWF ([UInt32]($script:SLF + 4))) -ne $target) { throw "TARG staging mismatch" }
  SetF 0xF5 0 0; Start-Sleep -Milliseconds 300
  RdWF ([UInt32]($script:SLF + 0x18))
}
function Mbox([int]$cmd, [int]$b1, [int]$b2, [int]$b3, [int]$mode = 1) { Call $script:HALMBOX @([UInt32]$cmd, [UInt32]$b1, [UInt32]$b2, [UInt32]$b3, [UInt32]$mode) | Out-Null }
function Poke51([int]$x, [int]$v) { Mbox 0x21 (($x -shr 8) -band 0xFF) ($x -band 0xFF) ($v -band 0xFF) 1 }
function Peek51([int]$x) { Mbox 0x03 (($x -shr 8) -band 0xFF) ($x -band 0xFF) 0 1; Start-Sleep -Milliseconds 100; RdWF ([UInt32]($script:MBOX + 0xB4)) }
