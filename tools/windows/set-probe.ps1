param([string]$Values='6,3')
Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
function Get60 { $out=@(); for($i=0;$i -lt 3;$i++){ $p=[byte[]](0x51,0x82,0x01,0x60); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 150
  $r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r); $out += [Amd]::Hex($r); Start-Sleep -Milliseconds 100 }; $out -join ' | ' }
"before: " + (Get60)
foreach ($v in $Values.Split(',')) { $val=[int]$v
  $p=[byte[]](0x51,0x84,0x03,0x60,0x00,[byte]$val); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  "set 0x60=$val w=" + [Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null)
  Start-Sleep -Seconds 6
  "after $val : " + (Get60)
  $ok = (Get60) -match '6E 88 02 00 60'
  if ($ok) { "VALID reply after $val -> HDMI-PC port is active"; break } }
