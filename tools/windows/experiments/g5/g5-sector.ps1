# Host side of the 1021.4+ SRAM sector job. Dot-source after g5-ddc.ps1 and g5-final.ps1.
#   SectorJob(dst, srcVA, nruns, runsHex) -> mismatching words after programming (0 = verified, -1 = refused)
#   Reboot51  -> resets the chip (POKE XDATA F1A8 bit0, the reset found on 2026-11-16) to boot the activated bank
$script:SECJOB = [Convert]::ToUInt32('A002D780', 16); $script:JOB = [Convert]::ToUInt32('A803CA00', 16)
function SectorJob([UInt32]$dst, [UInt32]$srcva, [int]$nruns, [string]$hex) {
  $buf = New-Object System.Collections.Generic.List[byte]
  $buf.AddRange((BytesOf $dst)); $buf.AddRange((BytesOf $srcva)); $buf.AddRange((BytesOf ([UInt64]$nruns)))
  for ($i = 0; $i -lt $hex.Length; $i += 2) { $buf.Add([Convert]::ToByte($hex.Substring($i, 2), 16)) }
  if ($script:JOB + $buf.Count -gt [Convert]::ToUInt32('A803CFC0', 16)) { throw 'job does not fit the upload window' }
  Up $script:JOB $buf.ToArray()
  $r = Call $script:SECJOB @()
  if ($r -eq [UInt32]::MaxValue) { return -1 }; [int]$r
}
function Reboot51 { try { Poke51 0xF1A8 0x03 } catch { } }
