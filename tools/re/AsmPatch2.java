// Multi-pass assembler for patch files with labels and data directives.
// Syntax: "@0xADDR" sets cursor; "name:" defines a label; "@name" inside an instruction is replaced by the label address;
// ".le32 0xVALUE" / ".bytes HEX" emit data; "#" comments. Prefers encodings seen verbatim in the original image.
// Args: <patchfile> <outfile> <original-image-at-program-base>
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.assembler.*;
import ghidra.app.plugin.assembler.sleigh.parse.*;
import ghidra.app.plugin.assembler.sleigh.sem.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import java.nio.file.*; import java.util.*; import java.util.regex.*;
public class AsmPatch2 extends GhidraScript {
  byte[] orig; Assembler asm; StringBuilder log = new StringBuilder();
  boolean inOrig(byte[] b) { outer: for (int i = 0; i + b.length <= orig.length; i++) { for (int j = 0; j < b.length; j++) if (orig[i+j] != b[j]) continue outer; return true; } return false; }
  Map<String,byte[]> cache = new HashMap<>();
  byte[] pick(Address at, String line, boolean final_) throws Exception { return pick(at, line, final_, false); }
  byte[] pick(Address at, String line, boolean final_, boolean longest) throws Exception {
    String key = at + "|" + line + "|" + longest; if (cache.containsKey(key)) return cache.get(key);
    List<byte[]> cands = new ArrayList<>();
    for (AssemblyParseResult pr : asm.parseLine(line)) {
      if (pr.isError()) continue;
      for (AssemblyResolution r : asm.resolveTree(pr, at)) {
        if (r.isError()) continue;
        byte[] b = ((AssemblyResolvedPatterns) r).getInstruction().getVals();
        boolean dup = false; for (byte[] c : cands) if (Arrays.equals(c, b)) dup = true; if (!dup) cands.add(b);
      }
    }
    if (cands.isEmpty()) throw new RuntimeException("no encoding for '" + line + "' at " + at);
    byte[] res = null;
    String note = "seen";
    if (longest) {
      int max = 0; for (byte[] c : cands) max = Math.max(max, c.length);
      for (byte[] c : cands) if (c.length == max && inOrig(Arrays.copyOf(c, 1))) { res = c; break; }
      if (res == null) for (byte[] c : cands) if (c.length == max) { res = c; break; }
      note = "label-branch longest form";
      if (final_) log.append(String.format("  %s %s '%s' (%d cands, %d bytes)%n", note, at, line, cands.size(), res.length));
      cache.put(key, res); return res;
    }
    for (byte[] c : cands) if (inOrig(c)) { res = c; break; }
    if (res == null) { // same length class as some seen instruction with identical first byte = same opcode form
      for (byte[] c : cands) { byte[] p = Arrays.copyOf(c, Math.min(2, c.length)); if (inOrig(p) && c.length >= 3) { res = c; note = "opcode-prefix seen"; break; } }
    }
    if (res == null) { res = cands.get(0); for (byte[] c : cands) if (c.length > res.length) res = c; note = "WARN unseen"; }
    if (final_ && !note.equals("seen")) log.append(String.format("  %s %s '%s' (%d cands)%n", note, at, line, cands.size()));
    cache.put(key, res); return res;
  }
  Map<Integer,String> origLine = new HashMap<>();
  static final Pattern LBL = Pattern.compile("@([A-Za-z_][A-Za-z0-9_]*)");
  @Override public void run() throws Exception {
    String[] a = getScriptArgs();
    orig = Files.readAllBytes(Paths.get(a[2]));
    asm = Assemblers.getAssembler(currentProgram);
    List<String> lines = new ArrayList<>(); for (String raw : Files.readAllLines(Paths.get(a[0]))) { String l = raw.replaceAll("#.*", "").trim(); if (!l.isEmpty()) lines.add(l); }
    Map<String,Long> labels = new HashMap<>();
    // initial guess: every label at its block start
    List<String[]> out = null; boolean converged = false;
    for (int pass = 0; pass < 12; pass++) {
      Map<String,Long> newLabels = new HashMap<>(); out = new ArrayList<>(); long cur = -1; boolean last = pass >= 2;
      for (String l : lines) {
        if (l.startsWith("@0x")) { cur = Long.decode(l.substring(1)); continue; }
        if (l.endsWith(":")) { newLabels.put(l.substring(0, l.length()-1), cur); continue; }
        byte[] b;
        if (l.startsWith(".le32")) { String tok = l.split("\\s+")[1]; Long lv = tok.startsWith("@") ? labels.get(tok.substring(1)) : Long.valueOf(Long.decode(tok)); long v = lv == null ? 0 : lv; b = new byte[]{(byte)v,(byte)(v>>8),(byte)(v>>16),(byte)(v>>24)}; }
        else if (l.startsWith(".bytes")) { String h = l.split("\\s+")[1]; b = new byte[h.length()/2]; for (int i = 0; i < b.length; i++) b[i] = (byte)Integer.parseInt(h.substring(2*i, 2*i+2), 16); }
        else {
          Matcher m = LBL.matcher(l); StringBuffer sb = new StringBuffer(); boolean hasLbl = false;
          while (m.find()) { hasLbl = true; Long v = labels.get(m.group(1)); if (v == null) v = cur; m.appendReplacement(sb, String.format("0x%x", v)); }
          m.appendTail(sb);
          boolean isBranch = hasLbl || sb.toString().matches("b\\.(j|jal|bf|bnf|beq|bne|beqi|bnei|bgtui|bleui|bgtu|bleu)\\b.*");
          b = pick(toAddr(cur), sb.toString(), false, isBranch);
          origLine.put(out.size(), l);
          l = sb.toString();
        }
        StringBuilder hx = new StringBuilder(); for (byte x : b) hx.append(String.format("%02x", x & 0xff));
        out.add(new String[]{String.format("%08x", cur), hx.toString(), l}); cur += b.length;
      }
      boolean stable = newLabels.equals(labels); labels = newLabels;
      if (stable && pass >= 1) { converged = true; break; }
    }
    if (!converged) throw new RuntimeException("label layout did not converge");
    // final: write bytes, record notes, disassemble check
    StringBuilder res = new StringBuilder();
    for (String[] o : out) {
      Address ad = toAddr(Long.parseLong(o[0], 16)); byte[] b = new byte[o[1].length()/2];
      for (int i = 0; i < b.length; i++) b[i] = (byte)Integer.parseInt(o[1].substring(2*i, 2*i+2), 16);
      if (!o[2].startsWith(".")) { boolean br = o[2].matches("b\\.(j|jal|bf|bnf|beq|bne|beqi|bnei|bgtui|bleui|bgtu|bleu)\\b.*"); pick(ad, o[2], true, br); }
      clearListing(ad, ad.add(b.length - 1)); setBytes(ad, b);
      res.append(String.format("ram:%s %s ; %s%n", o[0], o[1], o[2]));
    }
    res.append("---- labels\n"); for (Map.Entry<String,Long> e : new TreeMap<>(labels).entrySet()) res.append(String.format("  %s = 0x%x%n", e.getKey(), e.getValue()));
    res.append("---- disassembly check\n");
    for (String[] o : out) { if (o[2].startsWith(".")) continue; Address ad = toAddr(Long.parseLong(o[0], 16));
      new DisassembleCommand(new AddressSet(ad, ad), null, false).applyTo(currentProgram, monitor);
      Instruction i = getInstructionAt(ad); String dis = i == null ? "??" : i.toString();
      String want = o[2].replaceAll("\\s+", " ").toLowerCase(); String got = dis.replaceAll("\\s+", " ").toLowerCase();
      res.append(String.format("%s  %-40s %s%n", o[0], dis, normalize(got).equals(normalize(want)) ? "" : "   <-- differs from source: " + o[2]));
    }
    res.append("---- encoding notes\n").append(log);
    Files.writeString(Paths.get(a[1]), res.toString());
    println("wrote " + a[1]);
  }
  static String normalize(String s) { // canonicalize hex immediates
    Matcher m = Pattern.compile("(-?)0x([0-9a-f]+)").matcher(s); StringBuffer sb = new StringBuffer();
    while (m.find()) m.appendReplacement(sb, m.group(1) + Long.parseLong(m.group(2), 16)); m.appendTail(sb);
    return sb.toString().replaceAll("\\b0+(\\d)", "$1");
  }
}
