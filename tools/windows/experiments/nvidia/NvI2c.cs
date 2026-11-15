// Raw I2C over the display cable through NVIDIA NvAPI. Loaded by the PowerShell tools.
using System; using System.Runtime.InteropServices; using System.Threading;
public static class Nv {
  [DllImport("nvapi64.dll", EntryPoint="nvapi_QueryInterface", CallingConvention=CallingConvention.Cdecl)] static extern IntPtr QI(uint id);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int F0();
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FEnum([Out] IntPtr[] h, out int n);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FIds(IntPtr gpu, IntPtr ids, ref uint count, uint flags);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int FI2C(IntPtr gpu, IntPtr info);
  static T G<T>(uint id) { var p = QI(id); if (p == IntPtr.Zero) throw new Exception("QI fail 0x"+id.ToString("X")); return (T)(object)Marshal.GetDelegateForFunctionPointer(p, typeof(T)); }
  public static IntPtr Gpu;
  public static int Init() { int r = G<F0>(0x0150E828)(); if (r!=0) return r; var h = new IntPtr[64]; int n; r = G<FEnum>(0xE5AC921F)(h, out n); Gpu = h[0]; return r; }
  public static uint[] DisplayIds() {
    uint count = 0; var f = G<FIds>(0x0078DBA2); f(Gpu, IntPtr.Zero, ref count, 0);
    IntPtr buf = Marshal.AllocHGlobal((int)(16*count));
    for (int i=0;i<count;i++) Marshal.WriteInt32(buf, i*16, 16 | (3<<16));
    int r = f(Gpu, buf, ref count, 0); if (r!=0) throw new Exception("GetConnectedDisplayIds="+r);
    var res = new uint[count]; for (int i=0;i<count;i++) res[i]=(uint)Marshal.ReadInt32(buf, i*16+8);
    Marshal.FreeHGlobal(buf); return res;
  }
  // NV_I2C_INFO_V3 (x64, 64 bytes). addr8 = 7-bit address << 1.
  public static int Xfer(bool write, uint displayId, byte addr8, byte[] reg, byte[] data) {
    IntPtr info = Marshal.AllocHGlobal(64); for (int i=0;i<64;i++) Marshal.WriteByte(info,i,0);
    IntPtr pr = IntPtr.Zero, pd = Marshal.AllocHGlobal(Math.Max(1,data.Length));
    if (reg != null && reg.Length>0) { pr = Marshal.AllocHGlobal(reg.Length); Marshal.Copy(reg,0,pr,reg.Length); }
    if (write && data.Length>0) Marshal.Copy(data,0,pd,data.Length);
    Marshal.WriteInt32(info,0, 64 | (3<<16)); Marshal.WriteInt32(info,4,(int)displayId);
    Marshal.WriteByte(info,8,1); Marshal.WriteByte(info,9,addr8);
    Marshal.WriteIntPtr(info,16,pr); Marshal.WriteInt32(info,24, reg==null?0:reg.Length);
    Marshal.WriteIntPtr(info,32,pd); Marshal.WriteInt32(info,40,data.Length);
    Marshal.WriteInt32(info,44,0xFFFF); Marshal.WriteInt32(info,48,0);
    int r = G<FI2C>(write ? 0xE812EB07u : 0x2FDE12C5u)(Gpu, info);
    if (!write && r==0) Marshal.Copy(pd,data,0,data.Length);
    Marshal.FreeHGlobal(info); Marshal.FreeHGlobal(pd); if (pr!=IntPtr.Zero) Marshal.FreeHGlobal(pr);
    return r;
  }
  public static string Hex(byte[] b) { return BitConverter.ToString(b).Replace("-"," "); }
}
// MStar ISP: I2C 0x49, I2C-to-SPI bridge (protocol from flashrom programmers/mstarddc_spi.c).
public static class Isp {
  public const byte A = 0x92;
  public static uint Disp;
  public static int Enter() { return Nv.Xfer(true, Disp, A, null, new byte[]{(byte)'M',(byte)'S',(byte)'T',(byte)'A',(byte)'R'}); }
  public static int End()   { return Nv.Xfer(true, Disp, A, null, new byte[]{0x12}); }
  public static int Reset() { return Nv.Xfer(true, Disp, A, null, new byte[]{0x24}); }
  // SPI transaction: send writearr, then read readcnt bytes.
  public static int Spi(byte[] w, byte[] r) {
    var cmd = new byte[w.Length+1]; cmd[0]=0x10; Array.Copy(w,0,cmd,1,w.Length);
    int e = Nv.Xfer(true, Disp, A, null, cmd); if (e!=0) return e;
    if (r!=null && r.Length>0) { e = Nv.Xfer(false, Disp, A, new byte[]{0x11}, r); if (e!=0) return e; }
    return End();
  }
}
