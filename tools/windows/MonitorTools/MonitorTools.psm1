# Shared helpers for the Windows-side tools: AMD ADL raw I2C (HDMI), DDC/CI framing, MStar ISP.
# Every script imports this module instead of re-implementing the DDC frame.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not ('Amd' -as [type])) {
  Add-Type -Path @((Join-Path $here 'AmdI2c.cs'), (Join-Path $here 'AmdFlash.cs'), (Join-Path $here 'Dxva.cs'))
}

function Get-MonitorDisplay {
  # Returns the ADL display whose name matches (default: $env:MFW_DISPLAY or LC34G55T).
  param([string]$Name = $(if ($env:MFW_DISPLAY) { $env:MFW_DISPLAY } else { 'LC34G55T' }))
  $d = [Amd]::Init() | Where-Object { "$_" -match [regex]::Escape($Name) } | Select-Object -First 1
  if (-not $d) { throw "display '$Name' not found through AMD ADL (is it on the AMD GPU's HDMI port?)" }
  return $d
}

function Get-Vcp {
  # DDC/CI Get VCP over ADL. Returns @{rc,mh,ml,ch,cl,max,current} or $null after retries.
  param([Parameter(Mandatory)]$Display, [Parameter(Mandatory)][int]$Code, [int]$Retries = 6, [int]$DelayMs = 80)
  for ($t = 0; $t -lt $Retries; $t++) {
    $p = [byte[]](0x51, 0x82, 0x01, [byte]$Code); $ck = 0x6E; foreach ($b in $p) { $ck = $ck -bxor $b }
    [void][Amd]::Block($Display, [byte[]](@(0x6E) + $p + [byte]$ck), $null); Start-Sleep -Milliseconds $DelayMs
    $r = New-Object byte[] 11; [void][Amd]::Block($Display, [byte[]](0x6F), $r)
    $x = 0x50 -bxor 0x6E; for ($i = 1; $i -le 9; $i++) { $x = $x -bxor $r[$i] }
    if ($r[0] -eq 0x6E -and $r[1] -eq 0x88 -and $r[2] -eq 0x02 -and $r[4] -eq $Code -and $x -eq $r[10]) {
      return [pscustomobject]@{ rc = [int]$r[3]; mh = [int]$r[6]; ml = [int]$r[7]; ch = [int]$r[8]; cl = [int]$r[9]
        max = ([int]$r[6] -shl 8) -bor [int]$r[7]; current = ([int]$r[8] -shl 8) -bor [int]$r[9] }
    }
    Start-Sleep -Milliseconds 40
  }
  return $null
}

function Set-Vcp {
  # DDC/CI Set VCP over ADL. With -Verify, re-reads and retries until the value sticks.
  param([Parameter(Mandatory)]$Display, [Parameter(Mandatory)][int]$Code, [Parameter(Mandatory)][int]$Value, [switch]$Verify)
  for ($t = 0; $t -lt 5; $t++) {
    $p = [byte[]](0x51, 0x84, 0x03, [byte]$Code, [byte](($Value -shr 8) -band 0xFF), [byte]($Value -band 0xFF))
    $ck = 0x6E; foreach ($b in $p) { $ck = $ck -bxor $b }
    [void][Amd]::Block($Display, [byte[]](@(0x6E) + $p + [byte]$ck), $null); Start-Sleep -Milliseconds 120
    if (-not $Verify) { return $true }
    $r = Get-Vcp -Display $Display -Code $Code
    if ($r -and $r.current -eq $Value) { return $true }
  }
  return $false
}

function Enter-Isp {
  param([Parameter(Mandatory)]$Display)
  [AmdIsp]::D = $Display
  $e = [AmdIsp]::Enter(); Start-Sleep -Milliseconds 200
  $j = [AmdIsp]::Jedec()
  if (-not ($j[0] -eq 0xEF -and $j[1] -eq 0x40 -and $j[2] -eq 0x17)) { throw ("unexpected JEDEC id {0} (enter={1}); expected EF 40 17 (W25Q64)" -f [Amd]::Hex($j), $e) }
  return $j
}

function Exit-Isp { return [AmdIsp]::Reset() }

function Get-FileSha256([string]$Path) { (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower() }

Export-ModuleMember -Function Get-MonitorDisplay, Get-Vcp, Set-Vcp, Enter-Isp, Exit-Isp, Get-FileSha256
