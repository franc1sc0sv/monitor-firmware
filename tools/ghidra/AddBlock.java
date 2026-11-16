// Adds a raw binary file as an initialized, executable memory block, then disassembles and creates functions at the
// given entry points. Used for regions only readable at runtime (e.g. a RAM/HAL dump taken over DDC).
// Args: <block-name> <base-addr> <file-path> [entry-addr ...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.MemoryBlock;
import java.io.File;
import java.io.FileInputStream;

public class AddBlock extends GhidraScript {
  @Override public void run() throws Exception {
    String[] a = getScriptArgs();
    if (a.length < 3) { println("usage: AddBlock <name> <base> <file> [entries...]"); return; }
    Address base = toAddr(Long.decode(a[0 + 1]));
    File f = new File(a[2]);
    if (getMemoryBlock(base) == null) {
      try (FileInputStream in = new FileInputStream(f)) {
        MemoryBlock b = currentProgram.getMemory().createInitializedBlock(a[0], base, in, f.length(), monitor, false);
        b.setRead(true); b.setWrite(true); b.setExecute(true);
        println("added block " + a[0] + " at " + base + " len 0x" + Long.toHexString(f.length()));
      }
    } else {
      println("block already present at " + base);
    }
    int made = 0;
    for (int i = 3; i < a.length; i++) {
      Address e = toAddr(Long.decode(a[i]));
      disassemble(e);
      if (getFunctionAt(e) == null && createFunction(e, null) != null) made++;
    }
    println("functions created: " + made);
  }
}
