import sys, os
sys.path.insert(0, r"C:/Users/selie/AppData/Local/Temp/pdfdeps")
from PySquashfsImage import SquashFsImage

img = sys.argv[1]
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)
n = 0
with SquashFsImage.from_file(img) as image:
    for f in image:
        path = f.path.lstrip("/")
        dst = os.path.join(outdir, path)
        if f.is_dir:
            os.makedirs(dst, exist_ok=True)
        elif f.is_symlink:
            print("SYMLINK", f.path, "->", f.readlink())
        elif f.is_file:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                with open(dst, "wb") as out:
                    out.write(f.read_bytes())
                n += 1
            except Exception as e:
                print("ERR", f.path, e)
print("extracted files:", n)
