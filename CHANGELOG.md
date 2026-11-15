# Changelog

## Unreleased (repository formalised)
- Repository structure, docs, ADRs, CI. `mfw` package with version gate and expected-byte guards (rebuilds the
  flashed v3.1 image byte-identically). Hardened flasher (no reset after failure, backup check, boot-area refusal).
- Client 0.3.0: localhost-only API with Host/Origin checks, serial masking, Linux display-bus/EDID gate, shared VCP
  table, `--simulate` fake monitor, tests.

## Firmware (LC34G55T 1006.0)
- **v3.1** memory read, settings write, menu apply, setting-changed events (scanner fix).
- **v2.2** switch verdict requires a locked picture; **v2.1** own 10 ms clock; **v2** event log.
- **v1** Get 0x60 reports the input on screen.
