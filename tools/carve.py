import sys, os
src = sys.argv[1]
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)
data = open(src, 'rb').read()
assert len(data) == 0x800000, f"unexpected size {len(data):#x}"
# (name, offset, size)
parts = [
    ("0-boot.bin",      0x000000, 0x020000),
    ("1-env.bin",       0x020000, 0x010000),
    ("2-kernel.bin",    0x030000, 0x1C0000),
    ("3-rootfs.sqsh",   0x1F0000, 0x300000),
    ("4-usr.bin",       0x4F0000, 0x800000 - 0x4F0000),
]
def magic(b):
    if b[:4] == b'hsqs': return "squashfs LE (hsqs)"
    if b[:4] == b'sqsh': return "squashfs BE (sqsh)"
    if b[:2] == bytes([0x85,0x19]) or b[:4]==b'\x19\x85': return "jffs2"
    if b[:4] == b'\x27\x05\x19\x56': return "uImage (legacy)"
    if b[:4] == b'\xd0\x0d\xfe\xed': return "FDT/DTB"
    if b[0:4] == b'UBI#': return "UBI"
    return "0x" + b[:4].hex()
for name, off, size in parts:
    chunk = data[off:off+size]
    open(os.path.join(outdir, name), 'wb').write(chunk)
    print(f"{name:16s} off={off:#08x} size={size:#08x} ({size//1024}K)  magic={magic(chunk)}")
