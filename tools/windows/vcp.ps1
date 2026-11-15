param([string]$Op='get', [string]$Code='60', [string]$Value='0', [string]$Target='all')
Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
Add-Type -Path (Join-Path $PSScriptRoot 'Dxva.cs')
$c = [Convert]::ToByte($Code,16); $v = [Convert]::ToUInt32($Value,16)
function AmdGet($d, $code) {
  $p=[byte[]](0x51,0x82,0x01,$code); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  $w=[Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 60
  $r=New-Object byte[] 11; $rr=[Amd]::Block($d, [byte[]](0x6F), $r); "w=$w r=$rr " + [Amd]::Hex($r) }
function AmdSet($d, $code, $val) {
  $p=[byte[]](0x51,0x84,0x03,$code,[byte](($val -shr 8) -band 0xFF),[byte]($val -band 0xFF)); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  "set w=" + [Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null) }
if ($Target -in 'all','dxva') { foreach ($m in [Dxva]::All()) {
  if ($Op -eq 'set' -and $m.desc -match 'G55T|Odyssey|Generic') { }
  "dxva [{0}] get 0x{1:X2}: {2}" -f $m.desc, $c, [Dxva]::Get($m.h, $c) } }
if ($Target -in 'all','amd') { foreach ($d in [Amd]::Init()) {
  "amd [$d] get: " + (AmdGet $d $c)
  if ($Op -eq 'set' -and "$d" -match 'LC34G55T') { AmdSet $d $c $v; Start-Sleep -Seconds 4; "amd after set get: " + (AmdGet $d $c) } } }
