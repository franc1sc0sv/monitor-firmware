using System; using System.Runtime.InteropServices; using System.Collections.Generic;
public static class Dxva {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct PM { public IntPtr h; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string desc; }
  public delegate bool MonEnum(IntPtr hMon, IntPtr hdc, IntPtr rc, IntPtr data);
  [DllImport("user32.dll")] static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonEnum cb, IntPtr data);
  [DllImport("dxva2.dll")] static extern bool GetNumberOfPhysicalMonitorsFromHMONITOR(IntPtr h, out uint n);
  [DllImport("dxva2.dll")] static extern bool GetPhysicalMonitorsFromHMONITOR(IntPtr h, uint n, [Out] PM[] a);
  [DllImport("dxva2.dll")] public static extern bool GetVCPFeatureAndVCPFeatureReply(IntPtr h, byte code, out uint type, out uint cur, out uint max);
  [DllImport("dxva2.dll")] public static extern bool SetVCPFeature(IntPtr h, byte code, uint val);
  public static List<PM> All() { var l = new List<PM>();
    EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (hm, a, b, c) => { uint n; if (GetNumberOfPhysicalMonitorsFromHMONITOR(hm, out n) && n > 0) { var arr = new PM[n]; if (GetPhysicalMonitorsFromHMONITOR(hm, n, arr)) l.AddRange(arr); } return true; }, IntPtr.Zero);
    return l; }
  public static string Get(IntPtr h, byte code) { uint t, c, m; bool ok = GetVCPFeatureAndVCPFeatureReply(h, code, out t, out c, out m);
    return ok ? String.Format("cur=0x{0:X2} max=0x{1:X2}", c, m) : "FAIL err=" + Marshal.GetLastWin32Error(); }
}
