param([string]$Mode='status', [string]$Image='', [string]$Start='0', [string]$End='0', [int]$Chunk=32, [string]$Log='')
Add-Type -Path @((Join-Path $PSScriptRoot 'AmdI2c.cs'), (Join-Path $PSScriptRoot 'AmdFlash.cs'))
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' } | select -First 1
if (-not $d) { "LC34G55T not found"; exit 1 }
[AmdIsp]::D = $d; [AmdFlash]::MaxChunk = $Chunk
function Say($s) { $s; if ($Log) { Add-Content -Path $Log -Value $s } }
Say ("enter ISP -> " + [AmdIsp]::Enter()); Start-Sleep -Milliseconds 200
try {
  $j = [AmdIsp]::Jedec(); Say ("JEDEC " + [Amd]::Hex($j))
  if (-not ($j[0] -eq 0xEF -and $j[1] -eq 0x40 -and $j[2] -eq 0x17)) { throw "unexpected JEDEC id, refusing" }
  Say ("SR1=0x{0:X2} SR2=0x{1:X2} SR3=0x{2:X2}" -f [AmdFlash]::Sr(0x05), [AmdFlash]::Sr(0x35), [AmdFlash]::Sr(0x15))
  if ($Mode -eq 'test') {
    # scratch sector at the very end of the 8 MB chip; it is 0xFF in the backup and not referenced by the boot code
    $a = 0x7FF000
    $before = [AmdFlash]::ReadBack($a, 4096); $ff = ($before | ? { $_ -ne 0xFF }).Count
    Say ("test sector 0x7FF000 non-FF bytes before: $ff"); if ($ff -ne 0) { throw "test sector not blank, refusing" }
    $img = New-Object byte[] 0x800000; for ($i=0; $i -lt 0x800000; $i++) { $img[$i] = 0xFF }
    $rnd = New-Object Random 1234; for ($i=0; $i -lt 4096; $i++) { $img[$a+$i] = [byte]$rnd.Next(256) }
    $ok = [AmdFlash]::WriteSector($a, $img, [Action[string]]{ param($m) Say $m })
    Say ("test write+verify: " + $ok)
    [AmdFlash]::Erase4K($a); $after = [AmdFlash]::ReadBack($a, 4096); $ff2 = ($after | ? { $_ -ne 0xFF }).Count
    Say ("test sector erased back, non-FF bytes: $ff2")
  }
  elseif ($Mode -eq 'write') {
    $img = [IO.File]::ReadAllBytes($Image); if ($img.Length -ne 0x800000) { throw "image must be 8 MB" }
    $s = [Convert]::ToInt32($Start,16) -band 0xFFF000; $e = ([Convert]::ToInt32($End,16) + 0xFFF) -band 0xFFF000
    $t0 = Get-Date; $n = 0; $skipped = 0
    for ($a = $s; $a -lt $e; $a += 4096) {
      $cur = [AmdFlash]::ReadBack($a, 4096); $same = $true
      for ($i=0; $i -lt 4096; $i++) { if ($cur[$i] -ne $img[$a+$i]) { $same = $false; break } }
      if ($same) { $skipped++; continue }
      if (-not [AmdFlash]::WriteSector($a, $img, [Action[string]]{ param($m) Say $m })) { throw ("sector 0x{0:X6} failed after 3 tries" -f $a) }
      $n++; if ($n % 16 -eq 0) { Say ("  wrote {0} sectors, at 0x{1:X6}, {2:N0}s" -f $n, $a, ((Get-Date)-$t0).TotalSeconds) }
    }
    Say ("write done: {0} sectors written, {1} unchanged, {2:N0}s" -f $n, $skipped, ((Get-Date)-$t0).TotalSeconds)
  }
}
catch { Say ("ERROR: " + $_.Exception.Message) }
finally { Say ("reset -> " + [AmdIsp]::Reset()) }
