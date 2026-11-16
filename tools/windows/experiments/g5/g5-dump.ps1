# Resumable read-only memory dump over DDC via the dev hook: -Start/-End (runtime addresses), -Out file.
# F2 auto-increments; the pointer is re-synced every 1 KB and after any failed reply. Read-only.
param([UInt32]$Start,[UInt32]$End,[string]$Out)
. (Join-Path $PSScriptRoot 'g5-ddc.ps1')
$have=0; if(Test-Path -LiteralPath $Out){ $have=(Get-Item -LiteralPath $Out).Length - ((Get-Item -LiteralPath $Out).Length % 4) }
$a=[UInt32]($Start+$have); "resume at 0x{0:X8} (have {1} bytes)" -f $a,$have
$buf=New-Object System.Collections.Generic.List[byte]; $fails=0; $t0=Get-Date
SetAddr $a
while($a -lt $End){
  $m=GetF 0xF2 45
  if(-not $m){ $fails++; Start-Sleep -Milliseconds 200; SetAddr $a; if($fails -gt 400){ "TOO_MANY_FAILS at 0x{0:X8}" -f $a; break }; continue }
  $buf.AddRange($m); $a+=4
  if($buf.Count -ge 1024 -or $a -ge $End){
    $fs=[IO.File]::Open($Out,'Append'); $fs.Write($buf.ToArray(),0,$buf.Count); $fs.Close(); $buf.Clear()
    $el=((Get-Date)-$t0).TotalSeconds; "0x{0:X8} fails={1} {2:N0}s" -f $a,$fails,$el
    SetAddr $a   # resync pointer every 1KB
  }
}
"DONE at 0x{0:X8} fails={1}" -f $a,$fails
