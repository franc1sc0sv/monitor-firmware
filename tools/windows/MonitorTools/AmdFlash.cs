using System; using System.IO;
// SPI flash writes through the MStar ISP bridge (I2C 0x49). Requires AmdIsp.D set and ISP mode entered.
public static class AmdFlash {
  static int W(params byte[] b) { var s = new byte[b.Length+1]; s[0]=0x92; Array.Copy(b,0,s,1,b.Length); return Amd.Block(AmdIsp.D, s, null); }
  public static int MaxChunk = 32;   // payload bytes per I2C write inside one SPI transaction
  static void Must(int e, string what) { if (e != 0) throw new Exception(what + " failed code " + e); }
  public static byte Sr(byte cmd) { var r = new byte[1]; Must(AmdIsp.Spi(new byte[]{cmd}, r), "read SR"); return r[0]; }
  public static void Wren() { Must(AmdIsp.Spi(new byte[]{0x06}, null), "WREN"); if ((Sr(0x05) & 2) == 0) throw new Exception("WEL not set after WREN"); }
  public static void WaitIdle(int ms) { var t0 = DateTime.Now; while ((Sr(0x05) & 1) != 0) { if ((DateTime.Now - t0).TotalMilliseconds > ms) throw new Exception("flash busy timeout"); System.Threading.Thread.Sleep(2); } }
  public static void Erase4K(int a) { Wren(); Must(AmdIsp.Spi(new byte[]{0x20,(byte)(a>>16),(byte)(a>>8),(byte)a}, null), "erase"); WaitIdle(2000); }
  // Page program, split across several 0x10 writes inside one transaction (CS stays low until 0x12).
  public static void Program(int a, byte[] data, int off, int n) {
    if (n <= 0 || n > 256 || ((a & 0xFF) + n) > 256) throw new Exception("bad page program range");
    Wren();
    Must(W(0x10, 0x02, (byte)(a>>16), (byte)(a>>8), (byte)a), "PP cmd");
    for (int i = 0; i < n; i += MaxChunk) { int k = Math.Min(MaxChunk, n - i); var w = new byte[k+1]; w[0] = 0x10; Array.Copy(data, off+i, w, 1, k); Must(W(w), "PP data"); }
    Must(W(0x12), "PP end");
    WaitIdle(50);
  }
  public static byte[] ReadBack(int a, int n) { return AmdIsp.Read(a, n, 256, null); }
  // Erase + program one 4 KB sector from img (img indexed by flash address); verify; up to 3 tries.
  public static bool WriteSector(int a, byte[] img, Action<string> log) {
    for (int t = 1; t <= 3; t++) {
      Erase4K(a);
      bool blank = true; foreach (var x in ReadBack(a, 4096)) if (x != 0xFF) { blank = false; break; }
      if (!blank) { log(string.Format("  0x{0:X6} not blank after erase (try {1})", a, t)); continue; }
      for (int p = 0; p < 4096; p += 256) {
        bool allFF = true; for (int i = 0; i < 256; i++) if (img[a+p+i] != 0xFF) { allFF = false; break; }
        if (!allFF) Program(a + p, img, a + p, 256);
      }
      var rb = ReadBack(a, 4096); int bad = -1;
      for (int i = 0; i < 4096; i++) if (rb[i] != img[a+i]) { bad = i; break; }
      if (bad < 0) return true;
      log(string.Format("  0x{0:X6} verify mismatch at +0x{1:X3}: got {2:X2} want {3:X2} (try {4})", a, bad, rb[bad], img[a+bad], t));
    }
    return false;
  }
}
