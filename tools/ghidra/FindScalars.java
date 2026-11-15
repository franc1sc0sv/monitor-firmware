// Lists functions using several of the given scalar constants (any instruction). Args: hex values.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;
public class FindScalars extends GhidraScript {
  @Override public void run() throws Exception {
    Set<Long> want = new HashSet<>(); for (String a : getScriptArgs()) want.add(Long.decode(a));
    List<String> rows = new ArrayList<>();
    for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
      Map<Long,Integer> hit = new TreeMap<>();
      for (Instruction in : currentProgram.getListing().getInstructions(f.getBody(), true))
        for (int op=0; op<in.getNumOperands(); op++) for (Object o : in.getOpObjects(op)) if (o instanceof Scalar) {
          long v = ((Scalar)o).getUnsignedValue() & 0xffffffffL; if (want.contains(v)) hit.merge(v,1,Integer::sum); }
      if (hit.size() >= Math.min(3, want.size())) { StringBuilder b=new StringBuilder(); for (Map.Entry<Long,Integer> e: hit.entrySet()) b.append(String.format("%X:%d ",e.getKey(),e.getValue()));
        rows.add(String.format("%2d  %s %s  %s", hit.size(), f.getEntryPoint(), f.getName(), b)); }
    }
    Collections.sort(rows, Collections.reverseOrder()); for (int i=0;i<Math.min(30,rows.size());i++) println(rows.get(i));
  }
}
