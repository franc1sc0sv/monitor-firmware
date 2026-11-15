---
name: re-query
description: Run reverse-engineering queries (disassemble, decompile, find calls/references) against the right Ghidra project. Use when investigating firmware code.
---
# re-query

- Full RAM image (prefix + AP at 0x200000, no analysis, fast):
  `tools/ghidra/run-headless.sh script data/ghidra-ram ram ram-installed.bin Dis.java 0x26fc9b:20`
- Analysed AP at 0x203800 (functions, xrefs): project `data/ghidra2 inst`, program `app-installed.bin`;
  full decompile in `data/ghidra2/inst.c` (search it with Python/grep instead of re-decompiling).
- Scripts: `Dis.java addr:count`, `DisDecomp.java [asm] addr`, `FindCalls.java addr`, `RefsInRanges.java lo-hi`.
- Remember: decompiler constants for 16/32-bit loads are byte-swapped (data is LE); jump tables are LE pointers.
- Never paste decompiled vendor code into tracked files; summarise behaviour instead.
