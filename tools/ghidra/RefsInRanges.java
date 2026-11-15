// For each "lo-hi" arg, counts memory references (from the reference manager) whose target is inside the range,
// plus scalar operands of instructions whose value falls inside (catches movhi/addi-built addresses only partly).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;
public class RefsInRanges extends GhidraScript {
  @Override public void run() throws Exception {
    List<long[]> rs = new ArrayList<>();
    for (String a : getScriptArgs()) { String[] p = a.split("-"); rs.add(new long[]{Long.decode(p[0]), Long.decode(p[1]), 0, 0}); }
    ReferenceManager rm = currentProgram.getReferenceManager();
    for (Address src : rm.getReferenceSourceIterator(currentProgram.getMinAddress(), true)) {
      for (Reference r : rm.getReferencesFrom(src)) { long t = r.getToAddress().getOffset();
        for (long[] x : rs) if (t >= x[0] && t < x[1]) { x[2]++; if (x[2] <= 3) println(String.format("ref %x -> %x", src.getOffset(), t)); } }
    }
    // movhi hi + following imm (within 4 instructions, same register) reconstruction
    Listing L = currentProgram.getListing();
    InstructionIterator it = L.getInstructions(true);
    while (it.hasNext()) { Instruction i = it.next();
      if (!i.getMnemonicString().endsWith("movhi")) continue;
      Object[] o0 = i.getOpObjects(0), o1 = i.getOpObjects(1); if (o1.length == 0 || !(o1[0] instanceof Scalar)) continue;
      String reg = o0[0].toString(); long hi = ((Scalar) o1[0]).getUnsignedValue() << 16;
      Instruction n = i;
      for (int k = 0; k < 4; k++) { n = n.getNext(); if (n == null) break;
        String s = n.toString(); if (!s.contains(reg)) continue;
        for (int op = 0; op < n.getNumOperands(); op++) for (Object ob : n.getOpObjects(op)) if (ob instanceof Scalar) {
          long v = hi + ((Scalar) ob).getSignedValue();
          for (long[] x : rs) if (v >= x[0] && v < x[1]) { x[3]++; if (x[3] <= 3) println(String.format("hi/lo %x: %s ; %s -> %x", n.getAddress().getOffset(), i, n, v)); } }
        break; }
    }
    for (long[] x : rs) println(String.format("RANGE %x-%x refs=%d hilo=%d", x[0], x[1], x[2], x[3]));
  }
}
