# DRAM access port over DDC (dev hook 1020.0+: F6 may write 0xCF011F80..0xCF011FBF). Dot-source after g5-ddc.ps1.
# Port (decoded from SPARC 0x1413EC / 0x1415C8): line address (32-byte lines) in A0/A4/A8/AC (byte 0..3);
# read = F84:=0x80, F8C:=0x80, wait F90==0x80, then 32 bytes from F94; write = F84:=0x80, then 32 bytes to F88.
$script:SL20 = [Convert]::ToUInt32('A803CFC0', 16)          # 1020.1 slots: ADDR +0 ... VALW +0x24
$script:VALW20 = [UInt32]($script:SL20 + 0x24)
function P([string]$h) { [Convert]::ToUInt32($h, 16) }
function WrW20([UInt32]$a, [UInt32]$v) {                      # stage VALW with 4 F4 bytes, verify, then F6 to $a
  SetAddr $script:VALW20
  foreach ($sh in 24, 16, 8, 0) { SetF 0xF4 0 ([byte](($v -shr $sh) -band 0xFF)) }
  $chk = RdWF $script:VALW20
  if ($chk -ne $v) { throw ("VALW staging mismatch 0x{0:X8} want 0x{1:X8}" -f $chk, $v) }
  SetAddr $a; SetF 0xF6 0 0
}
function DramLine([UInt32]$line) {                            # READ one 32-byte line -> byte[32]
  WrW20 (P 'CF011FA0') ($line -band 0xFF); WrW20 (P 'CF011FA4') (($line -shr 8) -band 0xFF)
  WrW20 (P 'CF011FA8') (($line -shr 16) -band 0xFF); WrW20 (P 'CF011FAC') (($line -shr 24) -band 0xFF)
  WrW20 (P 'CF011F84') 0x80; WrW20 (P 'CF011F8C') 0x80
  for ($i = 0; $i -lt 20; $i++) { if (((RdWF (P 'CF011F90')) -band 0xFF) -eq 0x80) { break } }
  $b = New-Object byte[] 32
  for ($k = 0; $k -lt 32; $k++) { SetAddr (P 'CF011F94'); $m = GetF 0xF3 60; if (-not $m) { $k--; continue }; $b[$k] = $m[3] }
  , $b
}
