# DDC/CI on the inactive HDMI input (LC34G55T, 1006.0)

Research note, 2026-11-20. Static analysis of the installed 1006.0 AP (stock RAM image and the analysed Ghidra
project, both local under `data/`). No hardware was touched for this note. Addresses are real RAM addresses (AP at
`0x203800`). Registers are given as the RIU byte offset used by the code (`RIU+0x7c19`) and, where useful, as the
8051-style register number the helper functions take (`reg 0x3E0D`; offset = reg*2 - (reg & 1)).

Evidence levels follow ADR-0001: **confirmed** = read in the bytes or observed on hardware, *inferred* = reasoning.

## Question

The PC drives the monitor over DisplayPort. A MacBook on HDMI needs a DDC/CI channel at all times: live state (Get
`0xEE`, `0x60`), events (`0xEB..0xED`) and input-switch requests. On 2026-11-15, with the monitor showing DP, every
request sent on HDMI came back as RC=01 or garbage (journal). On 2026-11-19, with HDMI active, the Mac's
IOAVService got a channel and the `0xEA` probe answered (hardware observation reported by the user). Why does the
inactive HDMI not answer, and can a patch fix it?

## Result of the experiment (2026-11-20): H5, nothing to patch

**Confirmed on hardware.** Monitor showing DP (PC on DP, confirmed from the PC: `status` reports `input:
DisplayPort, signal: true`, Get `0x60` = `0x09`), MacBook on HDMI with its display of the 34" listed by macOS
(IOAVService `Location = External`). From the Mac, raw IOAVService I2C, one write then one read per request:

| Request (Mac, HDMI) | Write | Read | Reply |
|---|---|---|---|
| Get `0x10` | OK | OK | `6e 88 02 00 10 00 00 64 00 63`: valid, max 100, current 99 |
| Get `0xEA` | OK | OK | `6e 88 02 00 ea 00 40 02 00 1c`: valid, the v3.x probe answers |
| Get `0x60` | OK | OK | `6e 88 02 00 60 00 00 0e 00 09`: valid, input 9 = DP, the input actually shown |

Every request answered on the first try, twice in a row. So the DDC2Bi path serves the inactive HDMI input: H5.

- The 2026-11-15 failure was a test artefact. The likely cause (*inferred*): on 2026-11-20 the first attempt found
  the HDMI cable unplugged from the Mac, and macOS then lists **no** external IOAVService at all; earlier tools that
  still sent something got RC=01 or garbage. With the cable in, the inactive port answers.
- The ISR-only RAM fields did not change between snapshots. That does not contradict H5: identical requests leave
  the ISR's pointer copies and the HW-port byte at the same values (`+4 = 0x0c`, `+12 = 0x01` = HDMI, already set
  by the macOS hot-plug probe when the cable went in, while the first snapshots after boot read all zero). The
  method can only detect the first HDMI message after a reset, not repeated ones.
- Consequence: no firmware patch. The shared request buffer and the global event cursor (section "Consequences for
  Tandem") still hold, so one host at a time must talk DDC/CI.

## Short answer (before the experiment)

- **Verdict before the experiment: unknown.** (Resolved: see the result above, H5.) Nothing in the AP's DDC/CI software path depends on the
  active input (**confirmed in bytes** for every function listed below). So there is no software gate to remove; the
  break is either below the ISR (DDC engine, interrupt delivery, PHY) or in how the 2026-11-15 test was done.
- The reply recorded on the inactive port (`88 02 01 10 01 FF FF 00 00`) **was not built by the 1006.0 Get handler**
  (**confirmed in bytes**: the handler always sets TP = 0 for codes above `0x0F` and answers `0x10` with RC = 0). This
  supports the journal's inference that the request was never processed, not processed and refused.
- A zero-flash experiment over DP (section "Experiment") tells whether the DDC2Bi ISR runs at all for HDMI while DP is
  shown. Its result picks the patch, or shows that no firmware patch can help (section "Patch options").
- Independent of the fix: DP and HDMI share one request buffer, one pending flag and one reply length in RAM
  (**confirmed in bytes**). Two hosts talking DDC/CI at the same time can receive each other's replies (*inferred*
  impact). That keeps "the PC owns the monitor, the Mac asks through Tandem" as the right design.

## The DDC/CI path in 1006.0

| Stage | Address | What it does | Depends on active input? |
|---|---|---|---|
| IRQ attach | `0x24dba9` | Attaches IRQ `0x6E` to `0x24d65c` and enables it | No |
| IRQ handler | `0x24d65c` | If the DDC group status bit (`RIU+0x5670` bit 2, reg `0x2B38`) is set, calls the DDC2Bi dispatcher; then runs the DP-AUX dispatch (`0x2145d7`); re-enables IRQ `0x6E` | No |
| DDC2Bi dispatcher | `0x212c6f` | Picks HW port 6, 0 or 1 from status `RIU+0x7c20/0x7c24/0x7c25` (bits `0x18`), calls the ISR, clears the status | No |
| DDC2Bi ISR | `0x2126dd(hwport)` | Write events copy bytes from the DDC SRAM RX window into `0x4ec618`; a complete message sets pending `0x4c19e3 = 5`, logical port `0x4c19d0`, HW port `0x4c19da`. Read events feed the reply bytes into the TX window | No |
| DDC service | `0x212fc6` | Called by the main loop on every pass (v3 calls it from `poll`); runs the processor when pending = 5 | No |
| Processor | `0x212ea5` | Needs the byte count `0x4c92fc` != 0; calls the parser, then the reply writer | No |
| Parser / Get / Set | `0x270eb3` / `0x26fc1c` / `0x270b45` | Opcode dispatch; Get uses the jump table `0x377410` | No. Only the capabilities opcode (port type) and the timing report (that port's timing) read the source port's entry |
| Reply writer | `0x212d39` | Sets reply length `0x4c19c8`; writes the DDC SRAM TX window unless the source port is a DP port (flag `0x20`) | Only DP vs not-DP |
| DP-AUX MCCS ISR | `0x21a8df` | Same buffer `0x4ec618`, count `0x4c92fc`, pending `0x4c19e3`, port `0x4c19d0`, reply length `0x4c19c8`; replies through the AUX registers | No |

Port table `0x3c3440` (stride `0x8c`, byte 0 = DDC id, word at +4 = type flags), **confirmed in bytes**:

| Logical port | DDC id | Type flags | Meaning |
|---|---|---|---|
| 0 | 6 | `0x20` | DisplayPort (MCCS over AUX) |
| 1 | 2 | `0x0408` | HDMI, served by DDC2Bi **HW port 1** (`0x2122f3`: id = hwport + 1) |
| 2 | 5 | `0x20` | second DP entry, not wired on this model |

So the HDMI DDC/CI engine is HW port 1: status `RIU+0x7c25` (reg `0x3E13`), interrupt mask `RIU+0x7c2d` (reg
`0x3E17`), enable `RIU+0x7c19` (reg `0x3E0D`), pointer `RIU+0x7d98` (reg `0x3ECC`), control `RIU+0x7d9c` (reg
`0x3ECE`), discard flag `RIU+0x7de0` bit 0 (reg `0x3EF0`). HW ports 6 and 0 have no port-table entry.

### Who touches the HDMI engine, its interrupt and its pins

All **confirmed in bytes** for direct RIU accesses and for the register helpers (`0x2492c9`, `0x24933e`,
`0x249432`, `0x249566`, `0x2496d5`), searched over all 9124 decompiled functions, plus a raw scan of every `jal` in
the image for the call sites named here:

- **Init `0x2130d8`** runs once at boot (main-loop prologue, after forcing `cfg[0xd7] |= 0x40`) and at power-off
  (`0x26f620`). It enables the three engines (`0xB7`; HW ports 0 and 1 only when `cfg[0xd7] & 0x40`), unmasks their
  status (`0x67`), gives all three the **same** SRAM windows (RX `0x700`, TX `0x740`) and unmasks the DDC group
  interrupt (reg `0x2B28` bit 2). The only other writer of the group mask is the boot-time interrupt init `0x21387e`.
- **EDID reload `0x28c5ba` / `0x28c472`** turn the HDMI engine off, drop the EDID/HPD bits in regs `0x488/0x489`,
  reload, then restore the engine. Called from the factory opcodes, the power-off path and menu code (*inferred*:
  settings that change the EDID), not from the input switch.
- **IRQ masking**: the mask call `0x2c7283` is used only for IRQs `0x40`, `0x41`, `0x44`. IRQ `0x6E` is masked only
  by the generic dispatcher while its handler runs (*inferred* from the handler re-enabling it at its end).
- **HPD and RX termination** (`0x214c2d`, `0x2141fa`, *inferred* names): lowered only as timed pulses on the port
  being **selected** (`0x2736d7` -> `0x24a75e` / `0x24a7d0`, restored by the 1 ms timer task `0x22b971`). No path
  was found that leaves the inactive HDMI's HPD low.
- Per-port DDC toggles at `0x217da7` / `0x217e23` (bits `0x80` / `0x20` of regs `0x3E45/49/4D/58/A8`) have no call
  and no pointer reference: unused library code.
- The input switch (`0x26e064` -> `0x24b2f4`, and `0x269ffc`) touches none of the above.

### Why the recorded reply is not from the Get handler

The Get handler zeroes MH and CH, writes `88 02 00 <code>`, then TP = `(code > 0x0F) ? 0 : 1`
(`b.sfgtui r7,0xf` / `b.cmovri r7,r0,0x1` at `0x26fc71..0x26fc77`; `cmovri` semantics from the pinned AEON
SLEIGH spec). Code `0x10` jumps to `0x26ff01`, which returns RC = 0 with the brightness value. The default
(unsupported) case gives `88 02 01 <code> <TP> FF FF 00 00`. For `0x10` that is TP = 0, so the logged
`88 02 01 10 01 FF FF 00 00` cannot come from this handler (it relies on the bytes recorded in the journal; no raw log
of that test is kept).

## What remains (all inferred)

| Hypothesis | What it means | Firmware fix? |
|---|---|---|
| H1 | HW port 1 does not latch host writes while HDMI is not the selected input (DDC engine clock or routing tied to the HDMI receiver) | No, short of keeping the HDMI receiver selected/powered: breaks the active input |
| H2 | The engine latches the write and sets its status, but the group interrupt is not raised for it | Yes: service the status from the main loop |
| H3 | The ISR runs but drops the message (reg `0x3EF0` bit 0, reg `0x3EEA` bits 2-3, or a length/checksum mismatch) | Probably, once the failing check is known |
| H4 | A reply is built but the TX side never delivers it on HDMI (pointer reset or TX-ready bit) | Probably |
| H5 | The 2026-11-15 result came from the host side (AMD ADL raw I2C) or from a concurrent DP client | Nothing to fix |

On the Mac there is a second, separate condition: macOS must keep the HDMI display (and its IOAVService) while the
monitor shows DP. Static analysis says HPD stays high on the inactive HDMI (*inferred*), but macOS's behaviour is
not known. BetterDisplay reported "DDC channel: Unavailable" in Tandem's 2026-10-15 notes without saying which input
was active.

## Experiment (read-only, no flash)

It decides between {H1, H2} and {H3, H4, H5}. It uses the v3.1 peek: Set `0xF0/0xF1` only move the peek pointer
inside the patch's RAM block, Get `0xF2` reads RAM. No setting, no flash and no input is changed.

These RAM bytes are written **only** by the DDC2Bi ISR `0x2126dd` (**confirmed in bytes**, all references listed by
the analysed project); DP traffic never changes them:

| Address | Size | Meaning |
|---|---|---|
| `0x4c19ce` | u8 | ISR state flag |
| `0x4c19d2` | u16 | copy of the engine pointer at the last ISR pass |
| `0x4c19d8` | u16 | previous pointer |
| `0x4c19da` | u8 | HW port of the last complete message (1 = HDMI) |
| `0x4c19dc` | u16 | second pointer field |
| `0x4c92fd` | u8 | length byte of the message being received |

Steps (PC on DP with the 34" alone, monitor showing DP, the Mac on HDMI):

1. PC: `uv run monitor-events peek 4c19ce 0x10` and `uv run monitor-events peek 4c92fc 4`, twice, a few seconds
   apart. Compare **only** the fields in the table (offsets +0, +4..+5, +10..+12 and +14..+15 of the first dump,
   +1 of the second): the other bytes in those windows change with the peek's own DP traffic. The ISR-only fields must match between
   the two snapshots; if they differ, something is already talking on HDMI: stop and find it.
2. Mac: send a few Get requests on HDMI with the tool that answered the `0xEA` probe on 2026-11-19 (Tandem's
   `monitor-ddc` crate or `uv run monitor-events vcp get 0x10`; both use IOAVService). Write down exactly what the Mac
   reports (no display / no channel / error / a reply and its bytes).
3. PC: the same two peeks again.
4. Positive control, whenever HDMI is the active input anyway (do not switch inputs just for this): repeat 1-3. The
   fields must change, which proves the method.

| Result | Reading |
|---|---|
| The Mac has no display or no IOAVService in step 2 | The Mac side blocks first; the firmware question stays open. A PC-side sender (AMD iGPU HDMI with `tools/windows/vcp.ps1`) can repeat step 2 |
| The Mac sent, ISR-only fields unchanged | The ISR never ran for HDMI: H1 or H2. Next: the diagnostic build below, or stop here |
| ISR-only fields changed, the Mac got no reply or garbage | The ISR ran for HDMI: H3 or H4 (the diagnostic build tells which) |
| ISR-only fields changed, the Mac got valid replies | H5: the 2026-11-15 result was a test artefact; nothing to patch |

## Patch options

Cave: `0x399820..0x39a000`, v3.1 ends at `0x399dbf`, so **577 bytes free** (measured from the golden listing).
RAM block: `0x4fe6b0 + 0x239..0x3ff` is unused (about 450 bytes) for diagnostic state.

| Outcome | Patch | Sites and guards | Size | Risk |
|---|---|---|---|---|
| Ambiguous H1/H2 | **Diagnostic only**: in the existing `poll` hook, copy HW port 1 status, pointer, control, discard flag, the enable/mask registers and the DDC group status into `EV+0x240..` and count passes where the status stays set; read them with `peek` over DP | Cave only; no new stock site; existing `code_cave` guard | ~80 B | Low: read-only register loads in the main loop. An unexpected bus fault in a register read is the only new failure mode |
| H2 | **Main-loop service**: in `poll`, if `RIU+0x7c25 & 0x18` is set, call the stock dispatcher `0x212c6f` with IRQ `0x6E` masked around the call (`0x2c7283(0x6e)` / `0x2c7295(0x6e)`, the firmware's own functions), so it cannot race the real interrupt | Cave only; no new stock site | ~60-80 B | Medium: a mistake leaves DDC/CI broken on every input (recoverable over ISP, which needs HDMI on the AMD iGPU). Boot path untouched. EDID, HDCP and auto-detect untouched because nothing outside the DDC engine is written |
| H3 | Skip or clear the failing check for HW port 1 only | One stock site in `0x2126dd`, SHA-256 guard in `1006.0.toml` | ~20-40 B | Medium: same failure mode as above |
| H4 | Force the TX pointer reset / TX-ready for HW port 1 after the reply is written | Hook the `0x212d39` tail or wrap the processor call in `poll` | ~40 B | Medium |
| H1 | None that keeps the active input intact | - | - | Not recommended |

Common to all: the patch must stay inside the DDC engine and RAM; it never touches EDID SRAM, HPD (regs
`0x488/0x489`, `0x214c2d`), the HDMI PHY or the input-switch code. Every built image goes through `mfw build`,
`mfw verify` and the golden-listing check before any flash decision.

**Why no patch is in this branch:** any of the patches above would be written blind until the experiment says which
hypothesis holds; the wrong one costs a flash for nothing.

## Alternatives

1. **Keep the current design** (works today, no firmware change): the PC owns DDC/CI over DP, which answers whatever
   the monitor shows; the Mac sends its requests through Tandem's control plane to the PC agent and gets state and
   events back the same way.
2. **The real gap is "PC off or asleep while the monitor shows DP"**: nobody can switch back to HDMI. A firmware-only
   answer is an auto-fallback in `poll` (DP has no signal for N seconds and HDMI has a source, then switch to HDMI).
   That needs a way to see a source on the inactive HDMI (the OSD's "HDMI connected" message suggests a cable/5 V
   detect exists; not mapped yet). Tandem's notes say Samsung's own Auto Source Switch does not cover this case.
3. **Answering only Get `0x60`/`0xEE` on HDMI "from the same reply path"** adds nothing on this firmware: there is
   one reply path for all codes and it has no input gate. If HDMI requests reach the processor, every code already
   answers; if they do not, no code can.

## Consequences for Tandem (both inputs talking at once)

- One request buffer (`0x4ec618`), one pending flag, one reply length (`0x4c19c8`) serve DP and HDMI (**confirmed in
  bytes**). After an HDMI reply is produced, a DP read can receive it, and the reverse (*inferred* from the code).
  Clients must check the echoed VCP code, and one host at a time should talk DDC/CI.
- The event cursor (Set `0xEB`, kept at `EV+0x06`) is global. Two readers interleaving `0xEB`/`0xEC` read each
  other's records. One reader only (the PC agent) is the safe rule.

## If a patch is built later: what flashing needs

The user's explicit go-ahead in that session, for that exact image, then the `flash-monitor` skill:

1. Move the monitor's HDMI cable from the Mac to the PC's AMD iGPU HDMI and make HDMI the active input (MStar ISP only
   answers there). Keep the DP link to the RTX card.
2. Verified backup (two equal dumps, `data/dumps/`), `uv run mfw build` and `uv run mfw verify` clean, golden listing
   regenerated and `uv run pytest` green; the write range comes from `mfw build`.
3. Copy image and backup to a Windows path, compare SHA-256, run `tools\windows\flash.ps1 -Mode test`, then
   `flash.ps1 -Mode write -Image <img> -Backup <backup> -Start <s> -End <e> -Log <log>` (about 10 minutes).
4. On a non-zero exit: no power cycle, restore the backup at once (`restore-stock` skill).
5. After success: `uv run monitor-events status`, the visible brightness check, the HIL checklist, then the cable goes
   back to the Mac and the experiment above is repeated.
