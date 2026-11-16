# Host library for the 1021.0 final hook. Dot-source after g5-ddc.ps1.
#   Up([UInt32]addr, [byte[]]data)   upload into the window [0xA803C400, 0xA803CFE8) (2 bytes per frame), verified
#   Call([UInt32]target, args)       absolute call (runtime address) with up to 5 args, returns RESULT
#   Mbox(cmd,b1,b2,b3,mode)          HAL mailbox to the 8051 (nominal 0xA002EF00 = runtime 0xA002F220)
#   Poke51(xaddr, v) / Peek51(xaddr) 8051 XDATA via the patched mailbox cmds 0x21 / 0x03
# Note: reading ADDR itself over DDC is impossible (SetAddr overwrites it); verify uploads by reading the data back.
$script:SLF = [Convert]::ToUInt32('A803CFC0', 16)
$script:HALMBOX = [Convert]::ToUInt32('A002F220', 16)
$script:MBOX = [Convert]::ToUInt32('9F0A0100', 16)
function BytesOf([UInt64]$v) { $b = New-Object byte[] 4; for ($k = 0; $k -lt 4; $k++) { $b[$k] = [byte](($v -shr (24 - 8 * $k)) -band 0xFF) }; , $b }
function Up([UInt32]$addr, [byte[]]$data) {
  for ($try = 0; $try -lt 4; $try++) { try { Up1 $addr $data; return } catch { if ($try -eq 3) { throw }; Start-Sleep -Milliseconds 1500 } }
}
function Up1([UInt32]$addr, [byte[]]$data) {
  $n = $data.Length; if ($n % 2) { $data = [byte[]]($data + [byte]0) }
  SetAddr $addr
  for ($i = 0; $i -lt $data.Length; $i += 2) { SetF 0xF4 $data[$i] $data[$i + 1] }
  for ($i = 0; $i -lt $n; $i += 4) {
    $w = [UInt64](RdWF ([UInt32]($addr + $i)))
    for ($k = 0; $k -lt 4 -and $i + $k -lt $n; $k++) {
      $got = ($w -shr (24 - 8 * $k)) -band 0xFF
      if ($got -ne $data[$i + $k]) { throw ("upload verify failed at 0x{0:X8}: 0x{1:X2} want 0x{2:X2}" -f ($addr + $i + $k), $got, $data[$i + $k]) }
    }
  }
}
function Call([UInt32]$target, [object[]]$a) {
  $buf = New-Object System.Collections.Generic.List[byte]
  $buf.AddRange((BytesOf $target))
  for ($k = 0; $k -lt 5; $k++) { $v = 0; if ($k -lt $a.Count) { $v = [UInt64]$a[$k] }; $buf.AddRange((BytesOf $v)) }
  Up ([UInt32]($script:SLF + 4)) $buf.ToArray()
  SetF 0xF5 0 0; Start-Sleep -Milliseconds 300
  for ($t = 0; $t -lt 30; $t++) { try { return RdWF ([UInt32]($script:SLF + 0x18)) } catch { Start-Sleep -Milliseconds 1000 } }
  throw 'monitor did not come back after F5'
}
function Mbox([int]$cmd, [int]$b1, [int]$b2, [int]$b3, [int]$mode = 1) { $null = Call $script:HALMBOX @($cmd, $b1, $b2, $b3, $mode) }
function Poke51([int]$x, [int]$v) { Mbox 0x21 (($x -shr 8) -band 0xFF) ($x -band 0xFF) ($v -band 0xFF) 1 }
function Peek51([int]$x) { Mbox 0x03 (($x -shr 8) -band 0xFF) ($x -band 0xFF) 0 1; Start-Sleep -Milliseconds 100; RdWF ([UInt32]($script:MBOX + 0xB4)) }
# F8 (1021.1+): run a call list in-chip. $calls = array of @(target, a0, a1, a2, a3, a4); returns the results.
$script:LIST = [Convert]::ToUInt32('A803C600', 16)
function RunList([object[]]$calls) {
  $buf = New-Object System.Collections.Generic.List[byte]
  foreach ($c in $calls) { for ($k = 0; $k -lt 6; $k++) { $v = 0; if ($k -lt $c.Count) { $v = [UInt64]$c[$k] }; $buf.AddRange((BytesOf $v)) } }
  $buf.AddRange((BytesOf 0))
  Up $script:LIST $buf.ToArray()
  SetF 0xF8 0 0; Start-Sleep -Milliseconds 300
  $out = @()
  for ($i = 0; $i -lt $calls.Count; $i++) {
    for ($t = 0; $t -lt 30; $t++) { try { $out += (RdWF ([UInt32]($script:LIST + 24 * $i))); break } catch { Start-Sleep -Milliseconds 1000 } }
  }
  , $out
}
# 1021.2+: SRAM flash worker. Same entry format as RunList, but every fn must be an SRAM (HAL) address, or 1 = delay.
$script:WORKER = [Convert]::ToUInt32('A002D6C0', 16); $script:WLIST = [Convert]::ToUInt32('A803CA00', 16)
function RunWorker([object[]]$calls) {
  $buf = New-Object System.Collections.Generic.List[byte]
  foreach ($c in $calls) { for ($k = 0; $k -lt 6; $k++) { $v = 0; if ($k -lt $c.Count) { $v = [UInt64]$c[$k] }; $buf.AddRange((BytesOf $v)) } }
  $buf.AddRange((BytesOf 0))
  Up $script:WLIST $buf.ToArray()
  $ret = Call $script:WORKER @()
  $out = @($ret)
  for ($i = 0; $i -lt $calls.Count; $i++) { $out += (RdWF ([UInt32]($script:WLIST + 24 * $i))) }
  , $out
}
