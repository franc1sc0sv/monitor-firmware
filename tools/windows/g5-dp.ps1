Add-Type -Path (Join-Path $PSScriptRoot 'Dxva.cs')
$g5 = [Dxva]::All() | ? { [Dxva]::Get($_.h,0x10) -match 'max=0x32' } | select -First 1
if (-not $g5) { "G5 not found via dxva2"; exit 1 }
"G5 before: input " + [Dxva]::Get($g5.h,0x60)
"set 0x60=0x0F (DisplayPort) -> " + [Dxva]::SetVCPFeature($g5.h, 0x60, 0x0F)
Start-Sleep -Seconds 6
"G5 after (via same path): input " + [Dxva]::Get($g5.h,0x60)
"--- displays now:"; [Dxva]::All() | % { "  " + [Dxva]::Get($_.h,0x10) + " | input " + [Dxva]::Get($_.h,0x60) }
