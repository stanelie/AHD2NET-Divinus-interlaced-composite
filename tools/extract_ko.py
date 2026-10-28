import sys, struct, os
cam = open(r"C:/Users/selie/Documents/analog-ptz-bridge/firmware/stock/usr_jffs2/sbin/camapp","rb").read()
outdir = r"C:/Users/selie/Documents/analog-ptz-bridge/firmware/stock/res"
os.makedirs(outdir, exist_ok=True)

# find tar 'ustar' headers
members = []
i = 0
while True:
    k = cam.find(b"ustar", i)
    if k < 0: break
    i = k + 1
    if k < 257: continue
    hdr = k - 257
    name = cam[hdr:hdr+100].split(b"\x00",1)[0]
    try:
        size = int(cam[hdr+124:hdr+136].split(b"\x00")[0].strip() or b"0", 8)
    except Exception:
        continue
    if 0 < len(name) < 100 and all(32 <= c < 127 for c in name):
        members.append((hdr, name.decode('latin-1','replace'), size))

print("=== tar members found ===")
for hdr, name, size in members:
    print(f"  @{hdr:#x} size={size:8d}  {name}")

# extract any ptz.ko member
for hdr, name, size in members:
    if name.endswith("ptz.ko") or name.endswith("ptz.ko".lstrip("/")):
        data = cam[hdr+512:hdr+512+size]
        dst = os.path.join(outdir, os.path.basename(name))
        open(dst,"wb").write(data)
        print(f"\nEXTRACTED {name} -> {dst} ({len(data)} bytes), magic={data[:4]!r}")
