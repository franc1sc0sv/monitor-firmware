# Ghidra scripts

Contributor tooling. End users do not need Ghidra: the committed golden listings are the assembled patches.

Pinned toolchain: `versions.env` (Ghidra 12.1.3, AEON R2 plugin identified by the SHA-256 of its SLEIGH files).
Install the plugin from https://github.com/eb4x/ghidra-plugin-aeon (`./gradlew buildExtension`, then unzip into
`$GHIDRA_HOME/Ghidra/Extensions/`). Make sure only one copy exists (a second copy in `~/.config/ghidra` collides).

Facts that bite: Ghidra shows AEON data as big-endian, but the CPU reads data words **little-endian** (jump
tables, pointers). The AP body loads at **0x203800**, the prefix at 0x200000 (see docs/adr/0004).

| Script | Purpose |
|---|---|
| `AsmPatch2.java` | Assembler: labels, `.le32`/`.bytes`, multi-pass layout, prefers encodings seen verbatim in the stock image, label branches use the longest form, fails on non-convergence. Writes the listing format read by `mfw`. |
| `Dis.java` | Linear disassembly `addr:count` |
| `DisDecomp.java` | Disassemble, create function, decompile (`asm` to also print the listing) |
| `Decomp.java`, `DecompAll.java` | Decompile given functions / every function to a file |
| `SeedDisasm.java`, `SeedPointers.java`, `SeedRange.java` | Seed disassembly from prologues (`9c 3x`) and from LE code pointers |
| `FindCalls.java` | Calls and jumps inside a function |
| `MnemLens.java` | Set of (mnemonic, length, opcode) used by the stock compiler; the encoding whitelist check |
| `RefsInRanges.java` | References into address ranges (to prove a cave is unused) |
| `FindScalars.java`, `FindVcpHandler.java` | Early helpers used to locate the DDC/CI handlers |

Use `run-headless.sh` instead of typing `analyzeHeadless` command lines.
