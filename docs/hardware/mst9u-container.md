# MST9U flash container (LC34G55T)

8 MB Winbond W25Q64. Offsets for installed firmware 1006.0 (`firmware/targets/lc34g55t/versions/1006.0.toml`).

| Region | Flash | Notes |
|---|---|---|
| PM 8051 / boot | `0x000000..0x010fff` | Stage 1 (AEON, runs from flash at 0x2000) picks the image bank (0 or 0x400000) and BDMA-copies stage 2 (flash `0x67cd`, 0x4ebc bytes) to 0x1000100. Never written by this project. |
| Descriptor | `0x011000` | u32 LE x10: ap_flash_start `0x31080`, ram_start `0x200000`, ram_end, ap_flash_end, 0, header CRC-32, 0, 0, filesize-4 (`0x2bfde8`), `0x11000` |
| AP prefix | `0x031080..0x034880` | 0x3800 bytes, uncompressed, loads at 0x200000 (entry 0x200100). Image info at +0x1100 (`55AA5678`), +0x1147 `DEADBE` marker, **+0x114a = region length** (prefix + stream + 6), +0x114e = 0x3800 |
| AP stream | `0x034880..` | raw DEFLATE (zlib wbits -15) of the body, which loads at 0x203800; then u32 LE decompressed size and an u16 check word (algorithm unknown, never checked at boot) |
| Gap | up to `0x160930` | zero padding; resources start here at fixed absolute offsets |
| Trailer | `0x2bfde8` | `55 AA AB CD`, then CRC-32 big-endian over `[0, 0x2bfde8)` |
| Bank 2 | `0x400000..` | empty (0xFF); stage 1 can boot an image here (A/B flashing not investigated yet) |

CRC-32: poly 0x04C11DB7, MSB first, init 0, no final XOR (`crc32_msb(b"123456789") == 0x89a1897f`).
Header CRC covers `[ap_flash_start, ap_flash_end)`. Stage 2 programs a BDMA CRC but does not compare it, inflates
the stream, and jumps to 0x200100 without checking the result.
