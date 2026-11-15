param([string]$DisplayId = "80061080")
Add-Type -Path (Join-Path $PSScriptRoot 'NvI2c.cs')
[void][Nv]::Init(); $d = [Convert]::ToUInt32($DisplayId, 16)
function Hx($b){ [Nv]::Hex($b) }
# A) control: DDC/CI get VCP 0x10 with the opcode as data (no reg address)
$p=[byte[]](0x51,0x82,0x01,0x10); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
"A ddc write no-reg     -> " + [Nv]::Xfer($true,$d,0x6E,$null,[byte[]]($p+[byte]$ck))
Start-Sleep -Milliseconds 50; $r=New-Object byte[] 12
"A ddc read             -> " + [Nv]::Xfer($false,$d,0x6E,$null,$r) + " " + (Hx $r)
# B) EDID (0x50) read with offset register
$e=New-Object byte[] 16
"B edid 0x50 read       -> " + [Nv]::Xfer($false,$d,0xA0,[byte[]](0x00),$e) + " " + (Hx $e)
# C) probe other addresses with a 1-byte read (no writes)
foreach ($a7 in 0x49,0x59,0x3A,0x4A,0x30,0x1E,0x2A) {
  $x=New-Object byte[] 1
  "C read 7bit 0x{0:X2}       -> {1} {2}" -f $a7, [Nv]::Xfer($false,$d,[byte]($a7*2),$null,$x), (Hx $x)
}
# D) MSTAR entry with first byte as register
"D enter reg-form       -> " + [Nv]::Xfer($true,$d,0x92,[byte[]](0x4D),[byte[]](0x53,0x54,0x41,0x52))
Start-Sleep -Milliseconds 100
"D reset                -> " + [Nv]::Xfer($true,$d,0x92,[byte[]](0x24),(New-Object byte[] 0))
