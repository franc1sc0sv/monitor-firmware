// Ranks functions by how many advertised MCCS VCP codes appear as immediates in them.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;
public class FindVcpHandler extends GhidraScript {
  static final int[] VCP = {0x02,0x04,0x05,0x08,0x10,0x12,0x14,0x16,0x18,0x1A,0x52,0x60,0xAA,0xAC,0xAE,0xB2,0xB6,0xC6,0xC8,0xC9,0xD6,0xDC,0xDF,0xFD};
  static final int[] MSG = {0x51,0x6E,0x88,0xF3,0xE3,0x0C,0x07};
  @Override public void run() throws Exception {
    Set<Integer> vcp = new HashSet<>(); for (int v: VCP) vcp.add(v);
    Set<Integer> msg = new HashSet<>(); for (int v: MSG) msg.add(v);
    List<String> rows = new ArrayList<>();
    for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
      Set<Integer> hv = new TreeSet<>(), hm = new TreeSet<>();
      for (Instruction in : currentProgram.getListing().getInstructions(f.getBody(), true)) {
        String mn = in.getMnemonicString().toLowerCase();
        boolean cmp = mn.contains("sf") || mn.contains("cmp") || mn.contains("bf") || mn.contains("beq") || mn.contains("bne") || mn.contains("bg.") ;
        for (int op=0; op<in.getNumOperands(); op++) for (Object o : in.getOpObjects(op)) if (o instanceof Scalar) {
          int v = (int)((Scalar)o).getUnsignedValue();
          if (cmp && vcp.contains(v)) hv.add(v);
          if (msg.contains(v)) hm.add(v);
        }
      }
      if (hv.size() >= 6) rows.add(String.format("%3d vcp %2d msg  %s %s  vcp=%s msg=%s", hv.size(), hm.size(), f.getEntryPoint(), f.getName(), hex(hv), hex(hm)));
    }
    Collections.sort(rows, Collections.reverseOrder());
    for (int i=0;i<Math.min(25,rows.size());i++) println(rows.get(i));
  }
  static String hex(Set<Integer> s){ StringBuilder b=new StringBuilder(); for(int v: s) b.append(String.format("%02X ",v)); return b.toString().trim(); }
}
