# HIL: switch to DisplayPort over HDMI, confirm Get 0x60 from both cables, switch back over DP (dxva2/NVIDIA).
Import-Module (Join-Path $PSScriptRoot "../MonitorTools/MonitorTools.psm1") -Force
$d = Get-MonitorDisplay
"start: 0x60 = " + (Get-Vcp -Display $d -Code 0x60).current
"set 0x60=9 -> " + (Set-Vcp -Display $d -Code 0x60 -Value 9)
$found = $null
for ($i = 1; $i -le 10 -and -not $found; $i++) { Start-Sleep -Seconds 2
  $h = Get-Vcp -Display $d -Code 0x60
  foreach ($m in [Dxva]::All()) { if ([Dxva]::Get($m.h, 0x60) -match 'cur=0x09' -and [Dxva]::Get($m.h, 0x10) -match 'max=0x64') { $found = $m } }
  "t+{0}s HDMI reports 0x60 = {1}; DP path seen: {2}" -f (2 * $i), $(if ($h) { $h.current } else { 'none' }), [bool]$found }
if ($found) { "back via DP -> " + [Dxva]::SetVCPFeature($found.h, 0x60, 6) } else { "back via HDMI -> " + (Set-Vcp -Display $d -Code 0x60 -Value 6) }
Start-Sleep -Seconds 6; "end: 0x60 = " + (Get-Vcp -Display $d -Code 0x60).current
