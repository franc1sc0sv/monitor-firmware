param([string]$Name = 'LC34G55T')
Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { $_.Name -eq $Name } | select -First 1
if (-not $d) { "display $Name not found"; exit 1 }
"using " + $d
function W([byte[]]$b) { [Amd]::Block($d, [byte[]](@(0x92)+$b), $null) }
function R([byte[]]$b, [int]$n) { $r = New-Object byte[] $n; $e = [Amd]::Block($d, [byte[]](@(0x92)+$b), $r); ,@($e, $r) }
"enter MSTAR -> " + (W ([byte[]][char[]]'MSTAR'))
Start-Sleep -Milliseconds 200
# style A: write 0x10+cmd, then combined write(0x11)+read, then end
"A spi write 9F -> " + (W ([byte[]](0x10,0x9F)))
$x = R ([byte[]](0x11)) 4; "A read          -> " + $x[0] + "  " + [Amd]::Hex($x[1])
"A end          -> " + (W ([byte[]](0x12)))
# style B: write 0x11 alone then a pure read from 0x93
"B spi write 9F -> " + (W ([byte[]](0x10,0x9F)))
"B write 11     -> " + (W ([byte[]](0x11)))
$r = New-Object byte[] 4; "B read 0x93    -> " + [Amd]::Block($d, [byte[]](0x93), $r) + "  " + [Amd]::Hex($r)
"B end          -> " + (W ([byte[]](0x12)))
# a second known command: read 16 bytes at 0x000100 (vendor bin has 50 60 01 C0 there)
"C spi read @100 -> " + (W ([byte[]](0x10,0x03,0x00,0x01,0x00)))
$x = R ([byte[]](0x11)) 16; "C read           -> " + $x[0] + "  " + [Amd]::Hex($x[1])
"C end           -> " + (W ([byte[]](0x12)))
"reset          -> " + (W ([byte[]](0x24)))
