// Disassemble from each start arg, then seed at every 9c 3x prologue inside [lo,hi) given as "lo-hi".
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
public class SeedRange extends GhidraScript {
  @Override public void run() throws Exception {
    Listing L = currentProgram.getListing(); Memory mem = currentProgram.getMemory();
    for (String arg : getScriptArgs()) {
      String[] p = arg.split("-"); long lo = Long.decode(p[0]), hi = Long.decode(p[1]);
      for (long o = lo; o < hi - 1; o++) {
        Address a = toAddr(o);
        if (L.getInstructionContaining(a) != null) continue;
        int b0 = mem.getByte(a) & 0xff, b1 = mem.getByte(a.add(1)) & 0xff;
        if (o == lo || (b0 == 0x9c && (b1 & 0xf0) == 0x30)) {
          new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
          if (L.getInstructionAt(a) != null && L.getFunctionAt(a) == null) new CreateFunctionCmd(a).applyTo(currentProgram, monitor);
        }
      }
    }
    println("instr=" + L.getNumInstructions() + " funcs=" + currentProgram.getFunctionManager().getFunctionCount());
  }
}
