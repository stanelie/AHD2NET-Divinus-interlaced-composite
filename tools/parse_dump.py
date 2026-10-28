import re, sys
src, dst = sys.argv[1], sys.argv[2]
base = 0x42000000
size = 0x800000
buf = bytearray(size)
seen = bytearray(size)  # 1 = filled
line_re = re.compile(r'^([0-9a-fA-F]{8}):\s+((?:[0-9a-fA-F]{2}\s+){1,16})', re.M)
txt = open(src, 'r', encoding='latin-1', errors='replace').read()
nlines = 0
for m in line_re.finditer(txt):
    addr = int(m.group(1), 16)
    toks = m.group(2).split()
    off = addr - base
    if off < 0 or off >= size:
        continue
    for j, t in enumerate(toks):
        if off + j < size:
            buf[off + j] = int(t, 16)
            seen[off + j] = 1
    nlines += 1
filled = sum(seen)
# find gaps
gaps = []
i = 0
while i < size:
    if not seen[i]:
        s = i
        while i < size and not seen[i]:
            i += 1
        gaps.append((base + s, base + i - 1))
    else:
        i += 1
open(dst, 'wb').write(buf)
print(f"lines parsed: {nlines}")
print(f"filled: {filled} / {size} ({100.0*filled/size:.3f}%)")
print(f"gap ranges: {len(gaps)}")
for g in gaps[:40]:
    print(f"  MISSING {g[0]:#010x}-{g[1]:#010x}  ({g[1]-g[0]+1} bytes)")
