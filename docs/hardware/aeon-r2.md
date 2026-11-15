# AEON R2 notes

- OpenRISC-derived, 32 registers, 2/3/4-byte instructions; Ghidra plugin `eb4x/ghidra-plugin-aeon` (`AEON:BE:32:R2`).
- **Data is little-endian** (pointers, jump tables, `lwz` of words), although the plugin is labelled BE. Instruction
  streams assemble and disassemble correctly.
- Calling convention seen in the stock code: `r1` stack, `r9` link, arguments `r3..r8`, return `r3`; prologues save
  `r9..r13` when used (`b.addi r1,r1,-N` = bytes `9c 3x`). Hook code uses only `r3..r8` and saves `r9` around calls.
- `b.movi` takes a 4-bit immediate, `b.beqi/bnei` a small one; use `b.ori rX,r0,imm` and `b.sfeqi` + `b.bf/bnf` for
  larger values. `b.sfgtu rA,rB` sets the flag when rA > rB.
- Branch ranges: conditional branches cannot reach far targets; use `b.bf` to a local label and `b.j` from there.
- Memory: prefix at 0x200000, AP body at 0x203800, .text `0x20c000..0x39a000` (MIU write-protected), BSS
  `0x4c1ea0..0x4fe6b0`, heap via sbrk up to 0x800000, stack in SRAM at 0xb000xxxx, RIU base pointer at `0x4c1cbc`.
