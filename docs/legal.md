# Legal notes (not legal advice)

- **Never committed:** vendor firmware, extracted parts, flash dumps, built images (they embed the unit's serial),
  Ghidra projects, decompiled vendor code, settings dumps. CI fails on binaries and serial patterns.
- **Published:** this project's own assembly, tools, listings of its own code, addresses, layouts, hashes of vendor
  files, and prose descriptions of how stock functions behave. Version maps store SHA-256 of stock bytes, not bytes.
- **Reproduction without redistribution:** users dump their own monitor and build from it; the result is theirs.
- **No protection is circumvented:** the application is plain DEFLATE, unsigned and unencrypted, and the boot loader
  checks no CRC. Re-check this for every new target before publishing work on it.
- **Interoperability:** the purpose is to make the monitor report its real state to the user's own computers over the
  standard DDC/CI channel (US 17 U.S.C. 1201(f); EU Directive 2009/24/EC arts. 5-6 for observation and
  interoperability).
- Samsung's firmware download terms may restrict modification; that is a matter for each user.
- Trademarks are used only to name compatibility; no logos.
