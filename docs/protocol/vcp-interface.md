# DDC/CI interface of the patched firmware

Contract between the patched firmware and any client. Everything is plain MCCS **Get VCP** (opcode 0x01) and
**Set VCP** (opcode 0x03) on I2C address 0x37, so stock OS APIs work: Windows dxva2, Linux i2c-dev, macOS IOAVService.
Each Get reply carries four data bytes: MH ML (the "maximum" field) and CH CL (the "current" field).

Protocol version: **2** (reported in Get 0xEA ML). Firmware release v3.1 implements everything below.

## Codes

| VCP | Dir | Meaning | Since |
|---|---|---|---|
| `0x60` | Get | Input on screen (Samsung encoding: `0x09` DisplayPort, `0x06` HDMI), not the port the query came in on | v1 |
| `0x60` | Set | Switch input (`0x09`, `0x06`); logs a `ddc-switch-request` and starts a verdict | stock + v2 |
| `0xEA` | Get | MH = ring size (`0x40`), ML = protocol version (`2`), CH:CL = newest sequence number | v2 |
| `0xEB` | Set/Get | Read cursor (sequence number of the record to read) | v2 |
| `0xEC` | Get | Record at cursor: MH = id, ML = old, CH = new, CL = sequence low byte | v2 |
| `0xED` | Get | Record time: MH = sequence low byte, ML:CH:CL = time in 10 ms since boot (24 bits) | v2 |
| `0xEE` | Get | Live: MH = input port, ML = source select, CH = power flags (bit0 on), CL = signal present | v2 |
| `0xEF` | Get | Clock: 32 bits, 10 ms units since boot (wraps after ~497 days) | v2 |
| `0xF0`, `0xF1` | Set/Get | Memory address, high and low 16-bit halves | v3 |
| `0xF2` | Get | 4 bytes at the address (only `0x200000..0x7fffff`, else `FF FF FF FF`), then address += 4 | v3 |
| `0xF4` | Set | Write one byte at the address (only `0x204000..0x2043ff`, the settings block), then address += 1 | v3 |
| `0xF6` | Set | Apply menu item `0..0x6e` through the stock menu routine (applies and saves) | v3 |

Stock codes keep their stock behaviour (`0x10` brightness, `0x12` contrast, `0x14` color preset, `0x16/18/1A` RGB,
`0x87` sharpness, `0xD6` power, `0xF7` Samsung energy mode, ...). See `client/src/monitor_events/protocol.py`.

## Event ids

| id | Name | old | new |
|---|---|---|---|
| `0x00` | boot | 0 | 0 |
| `0x01` | input-port | previous port | new port (0 DP, 1 HDMI) |
| `0x02` | source-select | previous `cfg[0xde]` | new |
| `0x03` | power-flags | previous `cfg[0xd7]` | new (bit0 = power on, bit6 = DDC/CI enabled) |
| `0x04` | powersave-flags | low byte of `0x4ca78c` | new |
| `0x05` | sync-flags | active port struct `+0x1c` | new (`0x0a` = picture locked) |
| `0x06` | signal | 0/1 | 0 lost, 1 present (horizontal frequency non-zero) |
| `0x07` | system-state | low byte of `0x4cebe4` | new. Observed: `0x01` normal, `0x1b` OSD menu open, `0x03` source list, `0x1c` input banner |
| `0x08` | window-port | `0x4ec92d` | new |
| `0x10` | ddc-switch-request | current port | requested VCP value |
| `0x11` | switch-done | target port | port (target active **and** sync flags `0x0a`) |
| `0x12` | switch-failed | target port | port (no locked picture on the target within 8 s) |
| `0x13` | ddc-power-request | current port | requested `0xD6` value |
| `0x20`, `0x21` | setting-changed | offset low byte (offset bit 8 = id bit 0) | new value of `0x204000 + offset` |

The first poll after boot logs every watched value once with `old = 0xEE` (initial state).

## Rules clients rely on

- Sequence numbers are 16-bit and wrap. A record is valid only if `0xEC` CL **and** `0xED` MH both equal the
  cursor's low byte; otherwise re-read.
- A gap larger than the ring size between two reads of `0xEA` means events were lost.
- After a block of `0xF2` reads, read `0xF0`/`0xF1` back: the address must have advanced exactly 4 per read.
- Wait 50-150 ms between a request and reading its reply; retry on a bad checksum. Writes have no acknowledgement:
  read back when the code is readable.
- Clients must ignore unknown event ids and codes.
- Manual input changes (OSD/buttons) show as `input-port` without a preceding `ddc-switch-request`.

## Compatibility

New codes and event ids are minor changes. Changing the meaning or layout of an existing code bumps the version
in `0xEA` ML. Planned: an identity/capability read (ADR-0018). Changes are listed in `CHANGELOG.md` next to this file.

## Security

Any host connected to any input can read RAM (including the serial number in the settings block) and change
settings. Do not use the patched firmware where an untrusted machine is connected. See `SECURITY.md`.
