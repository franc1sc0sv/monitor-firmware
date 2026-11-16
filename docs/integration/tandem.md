# Integration with Tandem (two monitors, two computers)

State on 2026-11-16. This is the contract between `monitor-firmware` (firmware + `monitor-events` client/API) and
**Tandem** (`~/projects/personal-projects/apps/tandem`, Rust, Mac + Windows PC as one workstation). Goal set by the
user: plan the tandem setup now so that, once the 32" G5 is repaired, plugging it back in makes it appear in Tandem
and in the app **with no code change** — only data (profiles) and runtime detection.

Confidence per ADR-0001: **confirmed** = bytes or hardware observation, **inferred** otherwise.

## 1. Physical setup

```
            DisplayPort (DDC lives here, also while the monitor shows HDMI)
   PC (Windows) ───────────────┬──────────────────────────────┐
   RTX 5080 DP x2              │                              │
   AMD iGPU HDMI (lab only)    ▼                              ▼
                        34" LC34G55T                    32" G5 "FALCON"
                        (MStar, patched v3.1)           (Novatek NT68500)
                               ▲                              ▲
   Mac (MacBook Pro M5) ───────┴──────────────────────────────┘
            HDMI (one native, one USB-C→HDMI)
```

| | 34" LC34G55T | 32" Odyssey G5 FALCON |
|---|---|---|
| Platform | MStar MST9U, AEON R2 | Novatek NT68500 (8051 + SPARC V8) |
| Firmware | v3.1 patched, protocol 2 (confirmed) | **bricked 2026-11-16**; after SPI recovery: whatever we write (see §4) |
| EDID product | see `docs/targets/lc34g55t/overview.md` (to record in the profile from hardware) | `0x7489` on DP, `0x748A` on HDMI (confirmed) |
| Inputs | DP = port 0, HDMI = port 1 | DP, HDMI (single HDMI) |
| Set 0x60 → HDMI | `0x06` (also `0x03`) (confirmed) | `0x06` (confirmed) |
| Set 0x60 → DP | `0x09` (confirmed; `0x0F` also seen to work) | **unknown** — try `0x0F`, `0x09`, `0x10`; earlier HDMI-side test ignored `0x09/0x0F/0x11/0x12` but that was asked over HDMI while on HDMI, retest from DP |
| Get 0x60 truthful? | **yes** (v1 patch, ADR-0009) | stock: inferred **no** (Novatek likely reports the queried port, same as stock MStar) |
| Events / switch verdict | yes (ring 0xEA..0xEF, switch-done/failed) | no (until a G5 patch adds them) |
| DDC from the Mac (HDMI) | only while HDMI is the active input; inactive HDMI returns RC=01 (confirmed) | untested |

**Rule that follows from the table:** the PC owns all monitor control, over DP, because DP DDC stays alive whatever
the monitor shows (confirmed on the 34"). The Mac asks the PC through Tandem's control plane. `monitor-events serve`
stays loopback-only (ADR-0013); Tandem's PC agent is its only client on the network path.

## 2. What Tandem needs from monitor-firmware

1. **List of monitors** with a stable id, model, capabilities and current input — one call.
2. **Switch** a given monitor to `dp`/`hdmi` and get a verdict: `confirmed` (firmware said so), `assumed` (no
   firmware truth; state tracked by the client), or `failed`.
3. **Events** per monitor (SSE), each tagged with the monitor id, including "input changed" whether caused by DDC
   or by the user's OSD/buttons (only firmware-truth monitors can report the latter).
4. **Hot-plug**: a monitor that appears (power on, cable, repaired G5) is detected and profiled automatically.

Tandem's own docs are behind on this (as of 2026-11-16): `DESIGN.md §8` says "the monitor does not report its input;
the agent keeps the state". That is now false for the 34" (patched firmware reports the real input and switch
verdicts) and still true for a stock 32". The design should consume `input_truth` from the API (below) instead of
assuming either.

## 3. Proposed client/API changes (monitor-firmware side) — the "no code change" part

Everything model-specific goes in **data**, so a new or repaired monitor needs at most a profile file.

### 3.1 Monitor profiles (data files)

`client/src/monitor_events/profiles/*.toml`, one per model, matched by EDID manufacturer + product id (DP and HDMI
ids both listed):

```toml
# lc34g55t.toml
name = "Odyssey G5 34 (LC34G55T)"
edid = { mfg = "SAM", product = [0x....] }      # fill from hardware
inputs = { dp = 0x09, hdmi = 0x06 }
probe = "mstar-v3"           # driver to try first; falls back to "mccs"

# g5-falcon.toml
name = "Odyssey G5 32 (FALCON)"
edid = { mfg = "SAM", product = [0x7489, 0x748A] }
inputs = { dp = 0x0F, hdmi = 0x06 }   # dp value unconfirmed: verify after repair, edit this file only
probe = "mccs"
```

Unknown monitors get the generic `mccs` driver with MCCS standard input values.

### 3.2 Drivers chosen at runtime by probing, never by assumption

| Driver | Detected by | input_truth | Switch verdict |
|---|---|---|---|
| `mstar-v3` | Get `0xEA` ML = protocol `2`+ **and** profile says MStar | `firmware` | `confirmed`/`failed` from events 0x11/0x12 |
| `mccs` (stock / unknown) | fallback | `tracked` (last value the client set; unknown at start) | `assumed` |
| `novatek-dev` (later) | G5 profile **and** Get `0xF2` = magic `EF DE BE AD` | `firmware` once the G5 input address is mapped; `tracked` before | `assumed` until a G5 patch adds verdicts |

**Hard rule: never send the MStar v3 codes (`0xF0..0xF6`) to the G5 or the G5 dev-hook codes to the 34".** The two
patches reuse the same VCP codes with different meanings (on the G5 hook, `0xF4`/`0xF5`/`0xF8` write memory or call
functions). The driver is picked from profile + probe, and only then are vendor codes used. The probe itself uses only
Get, never Set.

### 3.3 API v2 (additive; current endpoints stay as aliases of the first monitor)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/monitors` | `[{id, name, profile, driver, input, input_truth, connected, capabilities:[...]}]` |
| GET | `/api/monitors/<id>/status` | same as today's `/api/status`, per monitor |
| POST | `/api/monitors/<id>/input` | `{"target":"dp"\|"hdmi"}` → `{ok, verdict: confirmed\|assumed\|failed, elapsed_s}` |
| GET | `/api/monitors/<id>/vcp/<hex>` | per monitor |
| GET | `/api/stream` | SSE, every event carries `"monitor": <id>`; new `event: monitor-added` / `monitor-removed` |

**Monitor id:** `<profile>-<short hash of EDID serial>` (hash only; never the serial — repo hygiene rule). Stable
across reboots and cable changes. This also implements ADR-0018 without a firmware change; a firmware identity read
can still be added later.

**Hot-plug:** the poll loop re-enumerates displays every few seconds; a new handle is profiled and probed, and a
`monitor-added` event is emitted. A repaired G5 therefore shows up by itself.

### 3.4 Tests that make "no code change" verifiable without hardware

- `FakeMonitor` gains a `stock-mccs` personality (Get 0x60 echoes the queried port, no 0xEA) next to the existing
  patched one.
- Simulator with **two** monitors (one patched, one stock); tests for `/api/monitors`, per-monitor switch verdicts,
  event tagging, hot-plug add/remove, and the "no vendor codes before probe" rule.

## 4. The 32" G5 before it joins

Recovery and backup come first; the tandem work does not depend on any of this because the stock/MCCS path is enough
to switch it.

1. SPI programmer (CH341A + SOIC-8 clip) on IC901 (W25Q64JV, 3.3 V), monitor unpowered: **read the full 8 MB first**,
   keep it as the permanent backup. Details and the expected damage: `docs/targets/g5-falcon/firmware-re.md`,
   section "INCIDENT".
2. Repair only what the dump shows broken (expected: sector `0x01F000`; the replacement is built locally, never
   committed).
3. Choose what runs on it: stock 1008.3 (simplest, `mccs` driver) or the 1021.x dev image (`novatek-dev`, memory
   read over DDC → lets us map the real-input address and make `input_truth = firmware` later).
4. After it boots: from the PC over DP, record EDID product, Get 0x60 on both inputs, and find which Set 0x60 value
   returns to DP. Write the result into `g5-falcon.toml` — that file is the only change.

## 5. Order of work

**monitor-firmware (this repo):**
1. Profiles + driver probe + `/api/monitors` + SSE tagging + hot-plug, with the two-monitor simulator (no hardware).
2. Verify on the PC with the 34" alone (patched driver) — the 32" missing must be a normal state.
3. When the G5 is back: fill `g5-falcon.toml` from the §4 step 4 measurements; no code change expected.
4. Later: G5 real-input address via the dev hook → `novatek-dev` gives `input_truth = firmware`.

**Tandem (other repo, other chat):** consume `/api/monitors` from the PC agent; carry Mac requests over the control
plane; treat `input_truth = tracked` monitors as "assumed" in the UI; update `DESIGN.md §2/§8` and
`docs/research/ddc-34-LC34G55T.md` with the facts in §1 (34" reports its real input now; 32" is the Novatek FALCON).

## 6. Safety for anything that switches inputs

Same rule as Tandem's: every hardware test that changes an input must switch back automatically (the user can lose
the PC's picture). Switching inputs is a plain MCCS Set and never touches flash. The G5 flasher work stays separate and
keeps its own rules (firmware-re.md and project memory): no flash writes without the user's OK in the moment.
