# Checks that MStar ISP answers and the SPI flash is the expected W25Q64 (EF 40 17). Read-only; resets the scaler.
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MonitorTools/MonitorTools.psm1') -Force
$d = Get-MonitorDisplay
"using $d"
try { "JEDEC " + [Amd]::Hex((Enter-Isp $d)) + "  SR1=0x{0:X2}" -f [AmdFlash]::Sr(0x05) } finally { "reset -> " + (Exit-Isp) }
