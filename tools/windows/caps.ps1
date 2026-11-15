# Prints the MCCS capabilities string of every monitor Windows sees (dxva2, read-only).
Import-Module (Join-Path $PSScriptRoot "MonitorTools/MonitorTools.psm1") -Force
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class Caps {
  [DllImport("dxva2.dll")] public static extern bool GetCapabilitiesStringLength(IntPtr h, out uint len);
  [DllImport("dxva2.dll")] public static extern bool CapabilitiesRequestAndCapabilitiesReply(IntPtr h, StringBuilder s, uint len);
  public static string Get(IntPtr h) { uint n; if (!GetCapabilitiesStringLength(h, out n)) return "FAIL len err=" + Marshal.GetLastWin32Error();
    var sb = new StringBuilder((int)n); if (!CapabilitiesRequestAndCapabilitiesReply(h, sb, n)) return "FAIL caps err=" + Marshal.GetLastWin32Error(); return sb.ToString(); }
}
"@
foreach ($m in [Dxva]::All()) { "=== " + $m.desc + " bright: " + [Dxva]::Get($m.h, 0x10); [Caps]::Get($m.h) }
