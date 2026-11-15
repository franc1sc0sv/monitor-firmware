# Lists ADL displays and does a DDC/CI read on each (read-only).
Import-Module (Join-Path $PSScriptRoot 'MonitorTools/MonitorTools.psm1') -Force
foreach ($d in [Amd]::Init()) {
  "=== $d"
  $r = Get-Vcp -Display $d -Code 0x10 -Retries 2
  if ($r) { "  brightness current=$($r.current) max=$($r.max)" } else { "  no valid DDC/CI reply" }
}
