// For each address arg: disassemble, create a function if missing, print listing (optional) and decompiled C.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
public class DisDecomp extends GhidraScript {
  @Override public void run() throws Exception {
    DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
    boolean asm = false;
    for (String a : getScriptArgs()) {
      if (a.equals("asm")) { asm = true; continue; }
      Address ad = toAddr(Long.decode(a));
      if (getInstructionAt(ad) == null) new DisassembleCommand(ad, null, true).applyTo(currentProgram, monitor);
      Function f = getFunctionAt(ad);
      if (f == null) { Function c = getFunctionContaining(ad); if (c != null && !c.getEntryPoint().equals(ad)) removeFunction(c);
        new CreateFunctionCmd(ad).applyTo(currentProgram, monitor); f = getFunctionAt(ad); }
      if (f == null) { println("no function at " + a); continue; }
      if (asm) { StringBuilder sb = new StringBuilder();
        for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) sb.append(i.getAddress()).append("  ").append(i).append("\n");
        println("----- asm " + f.getEntryPoint() + "\n" + sb); }
      DecompileResults r = d.decompileFunction(f, 120, monitor);
      println("===== " + f.getEntryPoint() + " " + f.getName() + "\n" + (r.decompileCompleted() ? r.getDecompiledFunction().getC() : r.getErrorMessage()));
    }
  }
}
