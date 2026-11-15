"""Independent checks on an AsmPatch2 listing:
1. instructions inside each block are contiguous (addr + len == next addr)
2. every branch/call target in the disassembly is an instruction start in the listing or an allowed external target
3. the disassembly text matches the source line (modulo hex formatting)
"""
import re, sys
lst = open(sys.argv[1]).read()
external = {int(x, 16) for x in sys.argv[2:]}
body = lst.split('---- labels')[0]
rows = []
for line in body.splitlines():
    m = re.match(r'ram:([0-9a-f]+) ([0-9a-f]+) ; (.*)', line)
    if m: rows.append((int(m.group(1), 16), len(m.group(2)) // 2, m.group(3)))
starts = {a for a, n, s in rows}
ok = True
for (a, n, s), (b, _, _) in zip(rows, rows[1:]):
    if a + n != b and b > a and b - (a + n) < 0x40:
        print(f'gap/overlap: {a:#x}+{n} -> next {b:#x}  ({s})'); ok = False
dis = lst.split('---- disassembly check')[1].split('---- encoding notes')[0]
for line in dis.splitlines():
    m = re.match(r'([0-9a-f]{8})\s+(\S+)\s*(.*?)\s*(<--.*)?$', line)
    if not m: continue
    addr, mn, ops, flag = int(m.group(1), 16), m.group(2), m.group(3), m.group(4)
    if flag: print('text differs:', line.strip()); ok = False
    if mn in ('b.j', 'b.jal', 'b.bf', 'b.bnf') or mn in ('b.beq', 'b.bne', 'b.beqi', 'b.bnei', 'b.bgtui', 'b.bleui'):
        t = int(ops.split(',')[-1], 16)
        if t not in starts and t not in external:
            print(f'bad target {addr:#x} {mn} {ops} -> {t:#x}'); ok = False
print('LISTING OK' if ok else 'LISTING HAS PROBLEMS', f'({len(rows)} rows)')
sys.exit(0 if ok else 1)
