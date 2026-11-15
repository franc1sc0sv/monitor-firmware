// Prints every instruction in the function containing arg0 that is a call/jump, with target.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
public class FindCalls extends GhidraScript {
  @Override public void run() throws Exception {
    for (String a : getScriptArgs()) {
      Function f = getFunctionContaining(toAddr(Long.decode(a)));
      if (f == null) { println("no func " + a); continue; }
      StringBuilder sb = new StringBuilder("== " + f.getEntryPoint() + "\n");
      for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) {
        String m = i.getMnemonicString();
        if (m.contains("jal") || m.equals("b.j") || m.contains("jr")) sb.append(i.getAddress()).append("  ").append(i).append("  [").append(i.getLength()).append("]\n");
      }
      println(sb.toString());
    }
  }
}
