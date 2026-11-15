// Raw DDC-line I2C through AMD ADL (atiadlxx.dll). Loaded by the PowerShell tools.
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
public static class Amd {
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] public delegate IntPtr Alloc(int size);
  static Alloc keep = s => Marshal.AllocHGlobal(s);
  [DllImport("atiadlxx.dll")] static extern int ADL2_Main_Control_Create(Alloc cb, int connectedOnly, out IntPtr ctx);
  [DllImport("atiadlxx.dll")] static extern int ADL2_Adapter_NumberOfAdapters_Get(IntPtr ctx, out int n);
  [DllImport("atiadlxx.dll")] static extern int ADL2_Adapter_AdapterInfo_Get(IntPtr ctx, IntPtr info, int size);
  [DllImport("atiadlxx.dll")] static extern int ADL2_Display_DisplayInfo_Get(IntPtr ctx, int adapter, out int n, out IntPtr info, int force);
  [DllImport("atiadlxx.dll")] static extern int ADL2_Display_DDCBlockAccess_Get(IntPtr ctx, int adapter, int display, int option, int cmdIndex, int sendLen, byte[] send, ref int recvLen, byte[] recv);
  public static IntPtr Ctx;
  public class Disp { public int Adapter, LAdapter, PAdapter, Value, Index; public string Name, Maker; public int Type, Connector; public override string ToString(){ return string.Format("adapter={0} (l={5},p={6}) display={1} name='{2}' maker='{3}' connector={4} value=0x{7:X}", Adapter, Index, Name, Maker, Connector, LAdapter, PAdapter, Value); } }
  const int AISize = 1572, DISize = 552;
  public static List<Disp> Init() {
    int r = ADL2_Main_Control_Create(keep, 1, out Ctx); if (r!=0) throw new Exception("ADL create="+r);
    int n; ADL2_Adapter_NumberOfAdapters_Get(Ctx, out n);
    IntPtr ai = Marshal.AllocHGlobal(AISize*n); for (int i=0;i<n;i++) Marshal.WriteInt32(ai, i*AISize, AISize);
    ADL2_Adapter_AdapterInfo_Get(Ctx, ai, AISize*n);
    var res = new List<Disp>(); var seen = new HashSet<string>();
    for (int i=0;i<n;i++) {
      int idx = Marshal.ReadInt32(ai, i*AISize+4);
      int nd; IntPtr di;
      if (ADL2_Display_DisplayInfo_Get(Ctx, idx, out nd, out di, 0)!=0 || di==IntPtr.Zero) continue;
      for (int j=0;j<nd;j++) {
        IntPtr p = di + j*DISize;
        int logical = Marshal.ReadInt32(p,0), padapter = Marshal.ReadInt32(p,12);
        int ladapter = Marshal.ReadInt32(p,8); int mask = Marshal.ReadInt32(p,544), val = Marshal.ReadInt32(p,548);
        if ((val & 1) == 0) continue; // connected
        string key = idx+":"+logical; if (!seen.Add(key)) continue;
        res.Add(new Disp{ Adapter=idx, LAdapter=ladapter, PAdapter=padapter, Value=val, Index=logical, Name=Marshal.PtrToStringAnsi(p+20), Maker=Marshal.PtrToStringAnsi(p+276), Type=Marshal.ReadInt32(p,532), Connector=Marshal.ReadInt32(p,540)});
      }
    }
    return res;
  }
  // send[0] = 8-bit I2C address. Returns ADL code; recv filled on success.
  public static int Block(Disp d, byte[] send, byte[] recv) {
    int rl = recv==null?0:recv.Length;
    return ADL2_Display_DDCBlockAccess_Get(Ctx, d.Adapter, d.Index, 0, 0, send.Length, send, ref rl, recv ?? new byte[0]);
  }
  public static string Hex(byte[] b) { return BitConverter.ToString(b).Replace("-"," "); }
}
// MStar ISP over the AMD DDC line (I2C 0x49 = 0x92/0x93). Protocol: flashrom programmers/mstarddc_spi.c.
public static class AmdIsp {
  public static Amd.Disp D;
  static int W(params byte[] b) { var s = new byte[b.Length+1]; s[0]=0x92; Array.Copy(b,0,s,1,b.Length); return Amd.Block(D, s, null); }
  public static int Enter() { return W((byte)'M',(byte)'S',(byte)'T',(byte)'A',(byte)'R'); }
  public static int Reset() { return W(0x24); }
  public static int Spi(byte[] cmd, byte[] rx) {
    var w = new byte[cmd.Length+1]; w[0]=0x10; Array.Copy(cmd,0,w,1,cmd.Length);
    int e = W(w); if (e!=0) return e;
    if (rx!=null && rx.Length>0) { e = W(0x11); if (e!=0) return e; e = Amd.Block(D, new byte[]{0x93}, rx); if (e!=0) return e; }
    return W(0x12);
  }
  public static byte[] Jedec() { var r = new byte[3]; Spi(new byte[]{0x9F}, r); return r; }
  // Read [start, start+len) in chunks; retries each chunk.
  public static byte[] Read(int start, int len, int chunk, Action<int> progress) {
    var outb = new byte[len];
    for (int off=0; off<len; off+=chunk) {
      int n = Math.Min(chunk, len-off), a = start+off; var buf = new byte[n]; int e = -1;
      for (int t=0; t<5 && e!=0; t++) e = Spi(new byte[]{0x03,(byte)(a>>16),(byte)(a>>8),(byte)a}, buf);
      if (e!=0) throw new Exception(string.Format("read failed at 0x{0:X6} code {1}", a, e));
      Array.Copy(buf,0,outb,off,n);
      if (progress!=null && (off/chunk)%256==0) progress(off);
    }
    return outb;
  }
}
