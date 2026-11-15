# Hardware-in-the-loop checklist

Run before tagging a firmware release; paste results into the release notes.

- [ ] Backup read twice, hashes equal, stored off the M: pool
- [ ] `mfw verify` passes; changed sectors only inside the AP region (+ trailer CRC sector)
- [ ] `flash.ps1 -Mode test` passes
- [ ] Flash completes; log kept with hashes
- [ ] Cold boot, picture on DP and on HDMI
- [ ] Looks identical to stock (brightness visibly responds: `tools/windows/hil/dark.ps1`)
- [ ] OSD works: brightness, input, picture mode
- [ ] Get `0x60` correct from both cables, both inputs (`hil/cycle.ps1`)
- [ ] `0xEA` reports ring 64 and the expected protocol version
- [ ] Events: input switch (DDC and OSD), signal loss, power off/on, OSD brightness change
- [ ] Switch verdict: success, and failure with the target unplugged
- [ ] Peek/poke/apply on brightness, value restored
- [ ] Standby and wake, 30 minutes idle
- [ ] Clock rate ~100/s against the host (`hil/clock.ps1`)
- [ ] Stock restore verified at least once per tool release
