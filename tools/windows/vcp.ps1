# Get or set any VCP code over ADL (HDMI). Example: .\vcp.ps1 -Code 10 ; .\vcp.ps1 -Code 10 -Value 80
param([Parameter(Mandatory)][string]$Code, [string]$Value = '')
Import-Module (Join-Path $PSScriptRoot 'MonitorTools/MonitorTools.psm1') -Force
$d = Get-MonitorDisplay; $c = [Convert]::ToInt32($Code, 16)
if ($Value) { "set 0x{0:X2}={1}: {2}" -f $c, $Value, (Set-Vcp -Display $d -Code $c -Value ([int]$Value) -Verify) }
$r = Get-Vcp -Display $d -Code $c
if ($r) { "0x{0:X2}: rc={1} current={2} max={3}" -f $c, $r.rc, $r.current, $r.max } else { "0x{0:X2}: no valid reply" -f $c; exit 1 }
