// Seeds disassembly from known code starts, then from every prologue-like site found by the first pass.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.util.*;
public class SeedDisasm extends GhidraScript {
  @Override public void run() throws Exception {
    Listing L = currentProgram.getListing();
    Address start = currentProgram.getMinAddress().add(0x8800);
    new DisassembleCommand(start, null, true).applyTo(currentProgram, monitor);
    createFunction(start, null);
    println("pass1 instructions=" + L.getNumInstructions());
    // learn the first instruction's bytes (a prologue) and seed at every match
    Instruction first = L.getInstructionAt(start);
    byte[] pro = first.getBytes();
    println("prologue " + first + " bytes=" + hex(pro));
    Memory mem = currentProgram.getMemory();
    byte[] pat = Arrays.copyOf(pro, 2); // opcode + register byte; immediate varies
    int seeds = 0;
    Address a = currentProgram.getMinAddress();
    while (a != null && !monitor.isCancelled()) {
      a = mem.findBytes(a, pat, null, true, monitor);
      if (a == null) break;
      if (L.getInstructionContaining(a) == null) {
        new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
        if (L.getInstructionAt(a) != null && L.getFunctionAt(a) == null) { new CreateFunctionCmd(a).applyTo(currentProgram, monitor); seeds++; }
      }
      a = a.add(1);
    }
    println("seeds=" + seeds + " instructions=" + L.getNumInstructions() + " functions=" + currentProgram.getFunctionManager().getFunctionCount());
  }
  static String hex(byte[] b){ StringBuilder s=new StringBuilder(); for(byte x: b) s.append(String.format("%02x ",x)); return s.toString().trim(); }
}
