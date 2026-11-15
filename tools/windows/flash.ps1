# Writes an 8 MB image to the monitor's SPI flash through MStar ISP over AMD ADL (HDMI).
# Safety: refuses the boot area, requires a backup, checks the image matches the backup outside the range,
# exits non-zero on any failure and does NOT reset the monitor after a failed write (it stays in ISP mode so the
# backup can be written back immediately). See docs/guides/flash.md and docs/guides/recover.md.
param(
  [ValidateSet('status', 'test', 'write')][string]$Mode = 'status',
  [string]$Image = '', [string]$Backup = '',
  [string]$Start = '11000', [string]$End = '161000',
  [int]$Chunk = 32, [string]$Log = '', [switch]$AllowBoot, [switch]$ForceReset
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MonitorTools/MonitorTools.psm1') -Force
function Say($s) { $s; if ($Log) { Add-Content -Path $Log -Value $s } }

$s = [Convert]::ToInt32($Start, 16) -band 0xFFF000
$e = ([Convert]::ToInt32($End, 16) + 0xFFF) -band 0xFFF000
$ok = $false; $inIsp = $false
try {
  if ($Mode -eq 'write') {
    if (-not $Image -or -not (Test-Path $Image)) { throw "-Image is required" }
    if (-not $Backup -or -not (Test-Path $Backup)) { throw "-Backup (a verified dump of this monitor) is required" }
    if (-not $AllowBoot -and $s -lt 0x11000) { throw ("refusing to write below 0x11000 (boot loaders); start=0x{0:X}" -f $s) }
    if ($e -gt 0x200000 -or $s -ge $e) { throw ("bad range 0x{0:X}..0x{1:X}" -f $s, $e) }
    $img = [IO.File]::ReadAllBytes($Image); $bak = [IO.File]::ReadAllBytes($Backup)
    if ($img.Length -ne 0x800000 -or $bak.Length -ne 0x800000) { throw "image and backup must both be 8 MB" }
    for ($i = 0; $i -lt 0x800000; $i++) {
      if (($i -lt $s -or $i -ge $e) -and $img[$i] -ne $bak[$i]) { throw ("image differs from backup outside the write range at 0x{0:X6}; wrong backup or wrong range" -f $i) }
    }
    Say ("image  {0}  sha256 {1}" -f $Image, (Get-FileSha256 $Image))
    Say ("backup {0}  sha256 {1}" -f $Backup, (Get-FileSha256 $Backup))
    Say ("range  0x{0:X6}..0x{1:X6}" -f $s, $e)
  }
  $d = Get-MonitorDisplay
  [AmdFlash]::MaxChunk = $Chunk
  $j = Enter-Isp $d; $inIsp = $true
  Say ("JEDEC " + [Amd]::Hex($j))
  Say ("SR1=0x{0:X2} SR2=0x{1:X2} SR3=0x{2:X2}" -f [AmdFlash]::Sr(0x05), [AmdFlash]::Sr(0x35), [AmdFlash]::Sr(0x15))
  if ($Mode -eq 'test') {
    # scratch sector at the very end of the chip: 0xFF in every known dump and never read by the boot code
    $a = 0x7FF000
    $before = [AmdFlash]::ReadBack($a, 4096)
    if (($before | Where-Object { $_ -ne 0xFF }).Count -ne 0) { throw "test sector 0x7FF000 is not blank; refusing" }
    $buf = New-Object byte[] 0x800000; for ($i = 0; $i -lt $buf.Length; $i++) { $buf[$i] = 0xFF }
    $rnd = New-Object Random 1234; for ($i = 0; $i -lt 4096; $i++) { $buf[$a + $i] = [byte]$rnd.Next(256) }
    if (-not [AmdFlash]::WriteSector($a, $buf, [Action[string]] { param($m) Say $m })) { throw "test write/verify failed" }
    [AmdFlash]::Erase4K($a)
    if ((([AmdFlash]::ReadBack($a, 4096)) | Where-Object { $_ -ne 0xFF }).Count -ne 0) { throw "test sector not blank after erase" }
    Say "test write+verify+erase: OK"
  }
  elseif ($Mode -eq 'write') {
    $t0 = Get-Date; $n = 0; $skipped = 0
    for ($a = $s; $a -lt $e; $a += 4096) {
      $cur = [AmdFlash]::ReadBack($a, 4096); $same = $true
      for ($i = 0; $i -lt 4096; $i++) { if ($cur[$i] -ne $img[$a + $i]) { $same = $false; break } }
      if ($same) { $skipped++; continue }
      if (-not [AmdFlash]::WriteSector($a, $img, [Action[string]] { param($m) Say $m })) { throw ("sector 0x{0:X6} failed after 3 tries" -f $a) }
      $n++; if ($n % 16 -eq 0) { Say ("  wrote {0} sectors, at 0x{1:X6}, {2:N0}s" -f $n, $a, ((Get-Date) - $t0).TotalSeconds) }
    }
    Say ("write done: {0} sectors written, {1} unchanged, {2:N0}s" -f $n, $skipped, ((Get-Date) - $t0).TotalSeconds)
  }
  $ok = $true
}
catch {
  Say ("ERROR: " + $_.Exception.Message)
}
finally {
  if ($inIsp -and ($ok -or $ForceReset -or $Mode -ne 'write')) { Say ("reset -> " + (Exit-Isp)) }
  elseif ($inIsp) {
    Say "NOT resetting: the flash may be partly written. The monitor stays in ISP mode."
    Say "Recover now: .\flash.ps1 -Mode write -Image <backup.bin> -Backup <backup.bin> -Start 11000 -End 161000"
  }
}
if (-not $ok) { exit 1 }
