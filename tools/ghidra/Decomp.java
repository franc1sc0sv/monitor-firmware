// Prints decompiled C for the functions at the given addresses (script args).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
public class Decomp extends GhidraScript {
  @Override public void run() throws Exception {
    DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
    for (String a : getScriptArgs()) {
      Function f = getFunctionContaining(toAddr(Long.decode(a)));
      if (f == null) { println("no function at " + a); continue; }
      DecompileResults r = d.decompileFunction(f, 120, monitor);
      println("===== " + f.getEntryPoint() + " " + f.getName() + "\n" + (r.decompileCompleted() ? r.getDecompiledFunction().getC() : r.getErrorMessage()));
    }
  }
}
