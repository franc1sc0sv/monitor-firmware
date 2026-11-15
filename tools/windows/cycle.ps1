Add-Type -Path (Join-Path $PSScriptRoot 'AmdI2c.cs')
Add-Type -Path (Join-Path $PSScriptRoot 'Dxva.cs')
$d = [Amd]::Init() | ? { "$_" -match 'LC34G55T' }
function AmdGet($code) { $p=[byte[]](0x51,0x82,0x01,[byte]$code); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [void][Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null); Start-Sleep -Milliseconds 150
  $r=New-Object byte[] 11; [void][Amd]::Block($d, [byte[]](0x6F), $r); [Amd]::Hex($r) }
function AmdSet($code,$val) { $p=[byte[]](0x51,0x84,0x03,[byte]$code,0,[byte]$val); $ck=0x6E; foreach($b in $p){$ck=$ck -bxor $b}
  [Amd]::Block($d, [byte[]](@(0x6E)+$p+[byte]$ck), $null) }
"[t0] HDMI get 60: " + (AmdGet 0x60)
"[t0] HDMI set 60=9 -> " + (AmdSet 0x60 9)
$found=$null
for ($i=1; $i -le 10; $i++) { Start-Sleep -Seconds 2
  $h = AmdGet 0x60
  $dx = foreach ($m in [Dxva]::All()) { $g=[Dxva]::Get($m.h,0x60); $b=[Dxva]::Get($m.h,0x10); "$g / bright $b"; if ($g -match 'cur=0x09' -and $b -match 'max=0x64') { $script:found=$m } }
  "[t+$(2*$i)s] HDMI: $h | dxva: " + ($dx -join ' ; ')
  if ($found) { break } }
if ($found) { "found 34in on DP; set back 60=6 -> " + [Dxva]::SetVCPFeature($found.h, 0x60, 6) }
else { "DP side not seen; trying HDMI set back -> " + (AmdSet 0x60 6) }
for ($i=1; $i -le 8; $i++) { Start-Sleep -Seconds 2; $h = AmdGet 0x60; "[back +$(2*$i)s] HDMI: $h"; if ($h -match '^6E 88 02 00 60') { break } }
