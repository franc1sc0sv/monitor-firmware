# In-chip byte-sum of a DRAM region (dev hook 1020.4+, F7). READ-ONLY on DRAM. Default: the staged update file
# (line 0x64500) over -Bytes bytes; prints sum32 and sum16 to compare with the image file / its [XXXX] name tag.
param([string]$Line = '64500', [int]$Bytes = 3449760, [string]$Chunk = '2000')
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
$SL = [Convert]::ToUInt32('A803CFC0', 16)
function Stage([UInt32[]]$w) { SetAddr ([UInt32]($SL + 8)); foreach ($v in $w) { foreach ($sh in 24, 16, 8, 0) { SetF 0xF4 0 ([byte](($v -shr $sh) -band 0xFF)) } } }
$l = [Convert]::ToUInt32($Line, 16); $c = [Convert]::ToUInt32($Chunk, 16)
$lines = [UInt32][Math]::Floor($Bytes / 32); $tail = $Bytes % 32
$end = $l + $lines; $total = [UInt64]0; $t0 = Get-Date
while ($l -lt $end) {
  $n = [UInt32][Math]::Min([double]$c, [double]($end - $l))
  Stage @($l, $n, [UInt32]1)
  if ((RdWF ([UInt32]($SL + 8))) -ne $l) { throw "staging mismatch" }
  SetF 0xF7 0 0; Start-Sleep -Milliseconds 300
  $next = RdWF ([UInt32]($SL + 8)); if ($next -ne $l + $n) { throw ("F7 did not finish: next=0x{0:X8} want 0x{1:X8}" -f $next, ($l + $n)) }
  $total += [UInt64](RdWF ([UInt32]($SL + 0x20))); $l = $next
}
"lines={0} (+{1} tail bytes not summed) sum32=0x{2:X8} sum16=0x{3:X4} in {4:N0}s" -f $lines, $tail, ($total -band 0xFFFFFFFF), ($total -band 0xFFFF), ((Get-Date) - $t0).TotalSeconds
