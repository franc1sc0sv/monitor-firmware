# HIL: brightness 0 for 5 s, then restore. Watch the panel: it must visibly go dark.
Import-Module (Join-Path $PSScriptRoot "../MonitorTools/MonitorTools.psm1") -Force
$d = Get-MonitorDisplay; $orig = (Get-Vcp -Display $d -Code 0x10).current
"{0:HH:mm:ss.f} brightness -> 0: {1}" -f (Get-Date), (Set-Vcp -Display $d -Code 0x10 -Value 0 -Verify)
Start-Sleep -Seconds 5
"{0:HH:mm:ss.f} brightness -> {1}: {2}" -f (Get-Date), $orig, (Set-Vcp -Display $d -Code 0x10 -Value $orig -Verify)
