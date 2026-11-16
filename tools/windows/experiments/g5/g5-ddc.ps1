# G5 dev-hook DDC driver (needs dev image 1019.0+: F0/F1 addr, F2 read4, F3 read word). Dot-source it.
# Reply bytes are validated (header + checksum 0x50) and mapped mem0=b9 mem1=b7 mem2=b8 mem3=b6.
# Note: never name a function H/R/Rd etc. - PowerShell aliases (Get-History, Remove-Item) shadow them.
Add-Type -Path (Join-Path $PSScriptRoot '../../MonitorTools/AmdI2c.cs')
$script:g=([Amd]::Init() | ? { "$_" -match 'Odyssey' } | select -First 1)
if(-not $script:g){ throw "G5_NOT_FOUND" }
function Chk($b){ $c=0; foreach($x in $b){$c=$c -bxor $x}; [byte]$c }
function SetF($vcp,$vh,$vl){ $p=[byte[]](0x6E,0x51,0x84,0x03,$vcp,$vh,$vl); [Amd]::Block($script:g,[byte[]]($p+(Chk $p)),$null)|Out-Null; Start-Sleep -Milliseconds 50 }
# returns 4 mem bytes [m0..m3] or $null if reply invalid
function GetF($vcp,$ms=60){
  $p=[byte[]](0x6E,0x51,0x82,0x01,$vcp); [Amd]::Block($script:g,[byte[]]($p+(Chk $p)),$null)|Out-Null
  Start-Sleep -Milliseconds $ms
  $r=New-Object byte[] 11; $st=[Amd]::Block($script:g,[byte[]](0x6F),$r)
  if($st -ne 0 -or $r[0] -ne 0x6E -or $r[1] -ne 0x88 -or $r[2] -ne 0x02 -or $r[4] -ne $vcp -or (Chk $r) -ne 0x50){ return $null }
  ,([byte[]]($r[9],$r[7],$r[8],$r[6]))
}
function SetAddr($a){ SetF 0xF0 ([byte](($a-shr 24)-band 0xFF)) ([byte](($a-shr 16)-band 0xFF)); SetF 0xF1 ([byte](($a-shr 8)-band 0xFF)) ([byte]($a-band 0xFF)) }
function Rd4($a){ for($t=0;$t -lt 4;$t++){ SetAddr $a; $m=GetF 0xF2; if($m){return $m} }; $null }
# Power check: in standby the DDC buffer keeps returning the last reply (a stale F3 frame passes GetF's header
# check), so refuse to run unless VCP D6 (power mode) gets a fresh reply (vcp code D6 echoed back).
$script:pw=GetF 0xD6 150
if(-not $script:pw){ throw "G5_NOT_ON (D6 reply: $script:pw)" }
function HexB($b){ if($b){ ($b|%{'{0:X2}' -f $_}) -join ' ' } else {'FAIL'} }
# Fresh 32-bit word read (F3). A busy monitor (e.g. right after an F5 call) leaves the previous F3 frame in the buffer,
# which passes GetF's checks; a standard VCP query in between proves the reply buffer is live again.
function RdWF([UInt32]$a){ for($t=0;$t -lt 6;$t++){ if(-not (GetF 0x10 100)){ Start-Sleep -Milliseconds 300; continue }; SetAddr $a; $m=GetF 0xF3 100; if($m){ return (([UInt32]$m[0] -shl 24) -bor ([UInt32]$m[1] -shl 16) -bor ([UInt32]$m[2] -shl 8) -bor [UInt32]$m[3]) } }; throw ("read failed at 0x{0:X8}" -f $a) }
