// Writes "mnemonic length firstbyte" for every instruction in the program (unique set) to arg0.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.util.*; import java.nio.file.*;
public class MnemLens extends GhidraScript {
  @Override public void run() throws Exception {
    TreeSet<String> s = new TreeSet<>();
    for (Instruction i : currentProgram.getListing().getInstructions(true))
      s.add(i.getMnemonicString() + " " + i.getLength() + " " + String.format("%02x", i.getByte(0) & 0xfc));
    Files.write(Paths.get(getScriptArgs()[0]), s);
  }
}
