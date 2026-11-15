# Security

## Scope

- The patched firmware's DDC/CI interface (`docs/protocol/vcp-interface.md`).
- The local HTTP API and UI (`monitor-events serve`).
- The flashing tools.

## Threat model in short

- **Firmware:** any host connected to any input of a patched monitor can read the monitor's RAM (including the
  serial number in the settings block) and change settings. It cannot write code, hardware registers, the boot
  loaders or factory data. Do not use the patch where an untrusted machine is plugged into the monitor (ADR-0015).
- **HTTP API:** binds to loopback only, checks Host and Origin, requires JSON for POST (ADR-0013). Any local program
  can use it; web pages and other machines cannot.
- **Flashing:** refuses the boot area, requires a backup, verifies each sector, does not reset after a failure.

## Reporting

Use GitHub private vulnerability reporting (Security tab -> "Report a vulnerability"). Do not attach firmware
images or dumps, and redact serial numbers.
