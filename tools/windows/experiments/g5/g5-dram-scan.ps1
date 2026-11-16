# READ-ONLY scan of the DRAM port for the staged update file ("\x7FNVTSC_IMG" header). Probes the first bytes of every
# -Stride lines (32-byte lines) in [-From, -To). Needs dev hook 1020.2+. Writes only the DRAM-port address/trigger regs.
param([string]$From = '0', [string]$To = '400000', [string]$Stride = '10000', [string]$Log = '')
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
. (Join-Path $PSScriptRoot 'g5-dram.ps1')
$cache = @{}
function WrFast([UInt32]$a, [UInt32]$v) {                     # unverified F6 write; VALW restaged only when it changes
  if ($script:lastV -ne $v) { SetAddr $script:VALW20; foreach ($sh in 24, 16, 8, 0) { SetF 0xF4 0 ([byte](($v -shr $sh) -band 0xFF)) }; $script:lastV = $v }
  SetAddr $a; SetF 0xF6 0 0; $cache[$a] = $v
}
function SetReg([string]$h, [UInt32]$v) { $a = P $h; if (-not $cache.ContainsKey($a) -or $cache[$a] -ne $v) { WrFast $a $v } }
function Head([UInt32]$line, [int]$n) {
  SetReg 'CF011FA0' ($line -band 0xFF); SetReg 'CF011FA4' (($line -shr 8) -band 0xFF)
  SetReg 'CF011FA8' (($line -shr 16) -band 0xFF); SetReg 'CF011FAC' (($line -shr 24) -band 0xFF)
  WrFast (P 'CF011F84') 0x80; WrFast (P 'CF011F8C') 0x80
  $b = @(); for ($k = 0; $k -lt $n; $k++) { SetAddr (P 'CF011F94'); $m = GetF 0xF3 50; if ($m) { $b += $m[3] } else { $b += -1 } }
  , $b
}
$script:lastV = [UInt32]::MaxValue
$f = [Convert]::ToUInt32($From, 16); $t = [Convert]::ToUInt32($To, 16); $s = [Convert]::ToUInt32($Stride, 16)
for ($l = $f; $l -lt $t; $l += $s) {
  $b = Head ([UInt32]$l) 4
  $line = "0x{0:X8}: {1}" -f $l, (($b | ForEach-Object { '{0:X2}' -f ($_ -band 0xFF) }) -join ' ')
  if ($b[0] -eq 0x7F -and $b[1] -eq 0x4E) { $line += '   <== NVTSC header' }
  $line; if ($Log) { Add-Content -LiteralPath $Log -Value $line }
}
