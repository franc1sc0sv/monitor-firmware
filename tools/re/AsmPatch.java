// Assembles a patch file and writes the bytes into the program (in-memory only unless saved).
// Patch file lines: "@0xADDR" sets the cursor; other non-empty lines are instructions; "#" starts a comment.
// Args: <patchfile> <outfile>. outfile receives "ADDR HEXBYTES" lines plus a disassembly listing.
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.assembler.*;
import ghidra.app.plugin.assembler.sleigh.parse.*;
import ghidra.app.plugin.assembler.sleigh.sem.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import java.nio.file.*; import java.util.*;
public class AsmPatch extends GhidraScript {
  byte[] orig;
  boolean inOrig(byte[] b) { outer: for (int i = 0; i + b.length <= orig.length; i++) { for (int j = 0; j < b.length; j++) if (orig[i+j] != b[j]) continue outer; return true; } return false; }
  byte[] pick(Assembler asm, Address at, String line) throws Exception {
    java.util.Collection<AssemblyParseResult> parses = asm.parseLine(line);
    java.util.List<byte[]> cands = new java.util.ArrayList<>();
    for (AssemblyParseResult pr : parses) {
      if (pr.isError()) continue;
      AssemblyResolutionResults rr = asm.resolveTree(pr, at);
      for (AssemblyResolution r : rr) {
        if (r.isError()) continue;
        ghidra.app.plugin.assembler.sleigh.sem.AssemblyResolvedPatterns rp = (ghidra.app.plugin.assembler.sleigh.sem.AssemblyResolvedPatterns) r;
        byte[] b = rp.getInstruction().getVals();
        boolean dup = false; for (byte[] c : cands) if (java.util.Arrays.equals(c, b)) dup = true;
        if (!dup) cands.add(b);
      }
    }
    if (cands.isEmpty()) throw new RuntimeException("no encoding for '" + line + "' at " + at);
    // prefer an encoding whose exact bytes occur in the original image; else the longest (compiler favours 4-byte forms)
    for (byte[] c : cands) if (inOrig(c)) { log.append(String.format("  %s '%s': %d candidates, chose one seen in original%n", at, line, cands.size())); return c; }
    byte[] best = cands.get(0); for (byte[] c : cands) if (c.length > best.length) best = c;
    log.append(String.format("  WARN %s '%s': no candidate seen verbatim in original (%d cands), chose %d-byte form%n", at, line, cands.size(), best.length));
    return best;
  }
  StringBuilder log = new StringBuilder();
  @Override public void run() throws Exception {
    orig = java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(getScriptArgs()[2]));
    String[] a = getScriptArgs();
    List<String> lines = Files.readAllLines(Paths.get(a[0]));
    Assembler asm = Assemblers.getAssembler(currentProgram);
    StringBuilder out = new StringBuilder(); Address cur = null; Address blockStart = null;
    List<Address[]> blocks = new ArrayList<>();
    for (String raw : lines) {
      String l = raw.replaceAll("#.*", "").trim(); if (l.isEmpty()) continue;
      if (l.startsWith("@")) { if (cur != null) blocks.add(new Address[]{blockStart, cur}); cur = toAddr(Long.decode(l.substring(1))); blockStart = cur; continue; }
      clearListing(cur, cur.add(7));
      byte[] b = pick(asm, cur, l);
      setBytes(cur, b);
      StringBuilder hx = new StringBuilder(); for (byte x : b) hx.append(String.format("%02x", x & 0xff));
      out.append(String.format("%s %s ; %s%n", cur, hx, l));
      cur = cur.add(b.length);
    }
    if (cur != null) blocks.add(new Address[]{blockStart, cur});
    out.append("---- disassembly check\n");
    for (Address[] bl : blocks) {
      clearListing(bl[0], bl[1].subtract(1));
      new DisassembleCommand(new AddressSet(bl[0], bl[1].subtract(1)), null, false).applyTo(currentProgram, monitor);
      Address p = bl[0];
      while (p.compareTo(bl[1]) < 0) { Instruction i = getInstructionAt(p); if (i == null) { out.append(p + " ??\n"); break; } out.append(p + "  " + i + "\n"); p = i.getMaxAddress().add(1); }
    }
    out.append("---- encoding choices\n").append(log);
    Files.writeString(Paths.get(a[1]), out.toString());
    println("wrote " + a[1]);
  }
}
