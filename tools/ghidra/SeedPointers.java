// Seeds disassembly at every aligned 32-bit little-endian value that points into the code range and is not yet code.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
public class SeedPointers extends GhidraScript {
  @Override public void run() throws Exception {
    Memory mem = currentProgram.getMemory(); Listing L = currentProgram.getListing();
    long b0 = currentProgram.getMinAddress().getOffset(); long lo = b0 + 0x8800, hi = b0 + 0x1c0000; int seeds = 0, cand = 0;
    long base = currentProgram.getMinAddress().getOffset(), end = currentProgram.getMaxAddress().getOffset();
    for (int pass = 0; pass < 3; pass++) {
      for (long off = base; off + 4 <= end; off += 4) {
        Address a = toAddr(off);
        if (L.getInstructionContaining(a) != null) continue;
        int v; try { v = mem.getInt(a, false); } catch (Exception e) { continue; }
        long t = v & 0xffffffffL; if (t < lo || t >= hi) continue;
        cand++;
        Address ta = toAddr(t);
        if (L.getInstructionContaining(ta) != null) continue;
        new DisassembleCommand(ta, null, true).applyTo(currentProgram, monitor);
        if (L.getInstructionAt(ta) != null && L.getFunctionAt(ta) == null) { new CreateFunctionCmd(ta).applyTo(currentProgram, monitor); seeds++; }
      }
      println("pass " + pass + " candidates=" + cand + " seeds=" + seeds + " instr=" + L.getNumInstructions() + " funcs=" + currentProgram.getFunctionManager().getFunctionCount());
    }
  }
}
