// Disassemble N instructions linearly from each address arg ("addr:count").
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
public class Dis extends GhidraScript {
  @Override public void run() throws Exception {
    for (String a : getScriptArgs()) { String[] p = a.split(":"); Address ad = toAddr(Long.decode(p[0])); int n = p.length > 1 ? Integer.parseInt(p[1]) : 30;
      StringBuilder sb = new StringBuilder("----- " + p[0] + "\n");
      for (int k = 0; k < n; k++) { Instruction i = getInstructionAt(ad);
        if (i == null) { new DisassembleCommand(new AddressSet(ad, ad.add(2)), null, false).applyTo(currentProgram, monitor); i = getInstructionAt(ad); }
        if (i == null) { sb.append(ad).append("  ??\n"); break; }
        sb.append(ad).append("  ").append(i).append("\n"); ad = i.getMaxAddress().add(1); }
      println(sb.toString()); }
  }
}
