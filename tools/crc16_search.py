"""Brute-force CRC-16 parameters/ranges for the MST9U AP check word."""
import struct, sys
m = open('data/dumps/LC34G55T-full-1.bin', 'rb').read()
app = open('data/vendor/app-installed.bin', 'rb').read()
stored = struct.unpack_from('<H', m, 0x160827 + 4)[0]
targets = {stored, ((stored & 0xff) << 8) | (stored >> 8)}

def table(poly, refl):
    t = []
    for i in range(256):
        if refl:
            c = i
            for _ in range(8): c = (c >> 1) ^ poly if c & 1 else c >> 1
        else:
            c = i << 8
            for _ in range(8): c = ((c << 1) ^ poly) & 0xffff if c & 0x8000 else (c << 1) & 0xffff
        t.append(c)
    return t

def rev16(x): return int(f'{x:016b}'[::-1], 2)
polys = [0x1021, 0x8005, 0x3D65, 0x0589, 0x8BB7, 0xA097, 0xC867, 0x5935, 0x755B, 0x6F63, 0x2F15]
datas = {
    'decomp': app,
    'prefix+decomp': m[0x31080:0x34880] + app,
    'prefix': m[0x31080:0x34880],
}
import numpy  # noqa: speeds nothing, just ensure env
for name, d in datas.items():
    for poly in polys:
        for refl in (False, True):
            p = rev16(poly) if refl else poly
            t = table(p, refl)
            for init in (0, 0xffff):
                c = init
                if refl:
                    for b in d: c = (c >> 8) ^ t[(c ^ b) & 0xff]
                else:
                    for b in d: c = ((c << 8) & 0xffff) ^ t[((c >> 8) ^ b) & 0xff]
                for xo in (0, 0xffff):
                    if (c ^ xo) in targets: print('HIT', name, hex(poly), refl, hex(init), hex(xo))
    s = sum(d) & 0xffff
    if s in targets: print('HIT sum16', name)
print('done stored', hex(stored))
