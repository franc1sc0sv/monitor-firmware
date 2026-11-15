# ADR-0003: Repack the AP as raw DEFLATE; keep every checksum consistent

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

The application (AP) is stored as a raw DEFLATE stream (zlib wbits -15) after a 0x3800-byte uncompressed prefix, followed by the decompressed size (u32 LE) and an u16 check word of unknown algorithm. A header CRC-32 covers the AP flash region and a trailer CRC-32 covers the file. Stage 2 of the boot loader inflates without checking the u16 or either CRC. Re-deflating with zlib level 9 overflows the 259 free bytes before the fixed resource tail.

## Decision

`mfw` round-trips the unmodified dump byte-identically before anything else, then re-deflates with zopfli (27 KB headroom on 1006.0), recomputes the prefix length field, descriptor (ram_end, ap_flash_end, header CRC-32) and the trailer CRC-32. The u16 word is copied unchanged. Resources are never moved (`tail_limit`).

## Consequences

A patched image differs from vendor output even with no logical change, so validity is proven by verify + guards + golden listings, not by comparison with the vendor file. The stale u16 is a known unknown: a vendor updater or service tool might check it. The trailer CRC sector (0x2bf000) must be written too, or the chip keeps a stale trailer CRC (it did up to v3.1).
