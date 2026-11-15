// Decompiles every function to the file given as script arg.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
public class DecompAll extends GhidraScript {
  @Override public void run() throws Exception {
    DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
    try (PrintWriter w = new PrintWriter(new FileWriter(getScriptArgs()[0]))) {
      int n=0, bad=0;
      for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
        DecompileResults r = d.decompileFunction(f, 60, monitor);
        if (r.decompileCompleted()) w.println("//@@ " + f.getEntryPoint() + "\n" + r.getDecompiledFunction().getC()); else bad++;
        if (++n % 200 == 0) println("done " + n);
      }
      println("total " + n + " failed " + bad);
    }
  }
}
