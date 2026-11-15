param([string]$DisplayId = "80061080")
Add-Type -Path (Join-Path $PSScriptRoot 'NvI2c.cs')
"init=" + [Nv]::Init()
[Isp]::Disp = [Convert]::ToUInt32($DisplayId, 16)
"enter MSTAR -> " + [Isp]::Enter()
Start-Sleep -Milliseconds 100
$id = New-Object byte[] 3
"RDID(9F) -> " + [Isp]::Spi([byte[]](0x9F), $id) + " id=" + [Nv]::Hex($id)
$sr = New-Object byte[] 1
"RDSR(05) -> " + [Isp]::Spi([byte[]](0x05), $sr) + " sr=" + [Nv]::Hex($sr)
$d = New-Object byte[] 32
"READ(03) @0x100 -> " + [Isp]::Spi([byte[]](0x03,0x00,0x01,0x00), $d) + " data=" + [Nv]::Hex($d)
"reset -> " + [Isp]::Reset()
