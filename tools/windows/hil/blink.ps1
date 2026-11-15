# HIL: identify the patched monitor by blinking brightness 100/10, then restore.
Import-Module (Join-Path $PSScriptRoot "../MonitorTools/MonitorTools.psm1") -Force
$d = Get-MonitorDisplay; $orig = (Get-Vcp -Display $d -Code 0x10).current
foreach ($v in 100, 10, 100, 10, 100) { "{0:HH:mm:ss.f} -> {1}: {2}" -f (Get-Date), $v, (Set-Vcp -Display $d -Code 0x10 -Value $v -Verify); Start-Sleep -Milliseconds 1500 }
"restore -> $orig: " + (Set-Vcp -Display $d -Code 0x10 -Value $orig -Verify)
