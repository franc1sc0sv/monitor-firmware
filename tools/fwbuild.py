"""Rebuild an LC34G55T (MST9U) flash image with a patched AP.

Layout (installed 1006.0 dump):
  0x11000  descriptor u32 LE: [ap_flash_start, ram_start, ram_end, ap_flash_end, 0, hdr_crc32, 0, 0, filesize-4, 0x11000]
  0x31080  AP prefix (0x3800 bytes, uncompressed, loads at 0x200000); prefix+0x114a = u32 compressed-region length
  0x34880  raw DEFLATE of the AP body (loads at 0x203800), then u32 LE decompressed size, then u16 check
  tail     resources at fixed absolute offsets (not moved), trailer 55 AA AB CD .. CRC-32 BE at filesize-4
Boot (stage 2) inflates without checking the u16 or the CRCs; we still keep every checksum consistent.
"""
import argparse, hashlib, re, struct, sys, zlib

DESC = 0x11000
PREFIX_LEN = 0x3800
LEN_FIELD = 0x114a        # inside the prefix
TAIL_LIMIT = 0x160930     # first non-zero byte after the original AP region; never write at or past it

def crc32_msb(data, crc=0):
    table = crc32_msb.t
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ table[(crc >> 24) ^ b]
    return crc
crc32_msb.t = []
for i in range(256):
    c = i << 24
    for _ in range(8):
        c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    crc32_msb.t.append(c)

def parse(img):
    d = list(struct.unpack_from('<10I', img, DESC))
    fstart, ram, ram_end, fend, _, hcrc, _, _, fsz4, _ = d
    sstart = fstart + PREFIX_LEN
    send = fend - 6
    size, chk = struct.unpack_from('<IH', img, send)
    return dict(desc=d, fstart=fstart, fend=fend, sstart=sstart, send=send, size=size, chk=chk, hcrc=hcrc, fsz4=fsz4)

def verify(img, label):
    p = parse(img)
    ok = True
    raw = zlib.decompressobj(-15).decompress(img[p['sstart']:p['send']])
    if len(raw) != p['size']: print(f'[{label}] size mismatch {len(raw):#x} != {p["size"]:#x}'); ok = False
    h = crc32_msb(img[p['fstart']:p['fend']])
    if h != p['hcrc']: print(f'[{label}] header crc {h:#010x} != {p["hcrc"]:#010x}'); ok = False
    t = crc32_msb(img[:p['fsz4']]); ts = struct.unpack_from('>I', img, p['fsz4'])[0]
    if t != ts: print(f'[{label}] trailer crc {t:#010x} != {ts:#010x}'); ok = False
    ln = struct.unpack_from('<I', img, p['fstart'] + LEN_FIELD)[0]
    if ln != p['fend'] - p['fstart']: print(f'[{label}] prefix len {ln:#x} != {p["fend"]-p["fstart"]:#x}'); ok = False
    if p['desc'][2] - p['desc'][1] != p['fend'] - p['fstart']: print(f'[{label}] ram_end inconsistent'); ok = False
    print(f'[{label}] {"OK" if ok else "FAIL"}  stream {p["sstart"]:#x}..{p["send"]:#x} ({p["send"]-p["sstart"]:#x})  fend {p["fend"]:#x}  '
          f'hdr {p["hcrc"]:#010x}  trailer {ts:#010x}  sha256 {hashlib.sha256(img).hexdigest()[:16]}')
    return ok, raw

def deflate(raw, engine):
    if engine == 'zopfli':
        import zopfli.zopfli as z
        d = z.compress(bytes(raw), numiterations=5)   # zlib container: strip 2-byte header and Adler-32
        return d[2:-4]
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 8)
    return c.compress(raw) + c.flush()

def build(img, raw, stream=None, engine='zlib', prefix=None):
    p = parse(img)
    out = bytearray(img)
    if prefix is not None:
        out[p['fstart']:p['fstart'] + PREFIX_LEN] = prefix
    if stream is None:
        stream = deflate(raw, engine)
    if zlib.decompressobj(-15).decompress(stream) != raw:
        sys.exit('deflate round-trip failed')
    send = p['sstart'] + len(stream)
    fend = send + 6
    if fend > TAIL_LIMIT:
        sys.exit(f'new AP region ends at {fend:#x}, past the fixed tail at {TAIL_LIMIT:#x} ({fend-TAIL_LIMIT} bytes over)')
    # clear the old region (stream + size + check + gap) to zero, as in the original padding
    for i in range(p['sstart'], TAIL_LIMIT): out[i] = 0
    out[p['sstart']:send] = stream
    struct.pack_into('<IH', out, send, len(raw), p['chk'])   # u16 check kept: boot never verifies it, algorithm unknown
    length = fend - p['fstart']
    struct.pack_into('<I', out, p['fstart'] + LEN_FIELD, length)
    d = p['desc'][:]
    d[2] = d[1] + length
    d[3] = fend
    d[5] = crc32_msb(bytes(out[p['fstart']:fend]))
    struct.pack_into('<10I', out, DESC, *d)
    struct.pack_into('>I', out, p['fsz4'], crc32_msb(bytes(out[:p['fsz4']])))
    return bytes(out)

def apply_patch(raw, listing, prefix=None, base=0x203800):
    """Apply an assembler listing. Addresses >= base go into the AP body; [0x200000, base) into the prefix."""
    raw = bytearray(raw)
    n = 0
    for line in open(listing):
        if line.startswith('----'): break
        m = re.match(r'ram:([0-9a-f]+) ([0-9a-f]+) ;', line)
        if not m: continue
        addr, hx = int(m.group(1), 16), bytes.fromhex(m.group(2))
        if addr >= base:
            if addr - base + len(hx) > len(raw): sys.exit(f'patch at {addr:#x} beyond AP image')
            raw[addr - base: addr - base + len(hx)] = hx
        elif 0x200000 <= addr and addr + len(hx) <= base:
            if prefix is None: sys.exit('prefix patch needs prefix buffer')
            prefix[addr - 0x200000: addr - 0x200000 + len(hx)] = hx
        else: sys.exit(f'patch address {addr:#x} out of range')
        n += len(hx)
    return bytes(raw), n

def region_diff(a, b):
    runs, i = [], 0
    while i < len(a):
        if a[i] != b[i]:
            j = i
            while j < len(a) and a[j] != b[j]: j += 1
            runs.append((i, j)); i = j
        else: i += 1
    return runs

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('--patch', action='append', default=[])
    ap.add_argument('--engine', default='zlib', choices=['zlib', 'zopfli']); ap.add_argument('--out')
    a = ap.parse_args()
    img = open(a.dump, 'rb').read()
    ok, raw = verify(img, 'original')
    if not ok: sys.exit('original does not verify')
    p = parse(img)
    rt = build(img, raw, stream=img[p['sstart']:p['send']])
    print('round-trip with original stream:', 'IDENTICAL' if rt == img else 'DIFFERENT')
    if rt != img: sys.exit(1)
    prefix = bytearray(img[p['fstart']:p['fstart'] + PREFIX_LEN])
    for pf in a.patch:
        raw, n = apply_patch(raw, pf, prefix); print(f'applied {pf}: {n} bytes')
    new = build(img, raw, engine=a.engine, prefix=prefix)
    verify(new, 'patched')
    np = parse(new)
    print(f'stream size {np["send"]-np["sstart"]:#x} (orig {p["send"]-p["sstart"]:#x}), headroom {TAIL_LIMIT-np["fend"]} bytes')
    for s, e in region_diff(img, new)[:12]: print(f'  diff {s:#08x}..{e:#08x} ({e-s} bytes)')
    if a.out: open(a.out, 'wb').write(new); print('wrote', a.out)
