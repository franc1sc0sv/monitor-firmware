# Read-only identification for the Odyssey G5 "FALCON" (Novatek NT68500).
# Does ONLY: list ADL displays, a read-only 7-bit I2C scan, and standard Get VCP.
# No Set VCP, no vendor opcode, no write to any non-standard address, no flash access.
# Unlike isp-id.ps1 (MStar), this scaler has no DDC ISP slave; see docs/hardware/novatek-isp.md.
# Run with the G5 awake and its HDMI input active/rendered, or ADL reads can block on a sleeping panel.
param([string]$Name = 'Odyssey')
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MonitorTools/MonitorTools.psm1') -Force

Write-Host '=== Displays on the AMD iGPU (ADL) ==='
$all = [Amd]::Init()
foreach ($d in $all) { Write-Host "  $d" }

$g5 = $all | Where-Object { "$_" -match [regex]::Escape($Name) } | Select-Object -First 1
if (-not $g5) {
  Write-Host ''
  Write-Host "### '$Name' is NOT on the AMD iGPU HDMI link. Move its HDMI cable to the motherboard HDMI. ###"
  exit 2
}
Write-Host ''
Write-Host "=== Target: $g5 ==="

Write-Host ''
Write-Host '=== Read-only 7-bit I2C scan (addresses that ACK a read) ==='
$acks = @()
for ($a = 0x08; $a -le 0x77; $a++) {
  $buf = New-Object byte[] 1
  if ([Amd]::Block($g5, [byte[]]([byte](($a -shl 1) -bor 1)), $buf) -eq 0) { $acks += ('0x{0:X2}' -f $a) }
}
Write-Host ("  ACKed: {0}" -f ($acks -join ' '))
Write-Host '  (expect 0x30 0x37 0x3A 0x50 0x54; NO 0x49/0x59 => not an MStar ISP target)'

Write-Host ''
Write-Host '=== Standard Get VCP (read-only, validated) ==='
foreach ($c in 0x60,0x10,0x12,0xDF,0xC0,0x14) {
  $r = Get-Vcp -Display $g5 -Code $c -Retries 3 -DelayMs 100
  if ($r) { Write-Host ('  VCP 0x{0:X2} OK  cur=0x{1:X4} max=0x{2:X4}' -f $c, $r.current, $r.max) }
  else    { Write-Host ('  VCP 0x{0:X2} -> no valid reply' -f $c) }
}
Write-Host ''
Write-Host 'Note: 0x60 (input source) is the real-input readout; it works today with no patch.'
Write-Host 'No DDC flash read/write path exists on this scaler. See docs/hardware/novatek-isp.md.'
