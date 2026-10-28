import sys, struct
sys.path.insert(0, r"C:/Users/selie/AppData/Local/Temp/pdfdeps")
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

path = r"C:/Users/selie/Documents/analog-ptz-bridge/firmware/stock/res/ptz.ko"
elf = ELFFile(open(path, "rb"))
symtab = elf.get_section_by_name(".symtab")
syms = {i: s.name for i, s in enumerate(symtab.iter_symbols())}
text = elf.get_section_by_name(".text")
td = text.data()

rels = {}      # offset -> symname  (in .text)
for sec in elf.iter_sections():
    if isinstance(sec, RelocationSection) and sec.name == ".rel.text":
        for r in sec.iter_relocations():
            rels[r['r_offset']] = (syms.get(r['r_info_sym'], f"sym{r['r_info_sym']}"), r['r_info_type'])

def lit32(addr):
    if addr+4 <= len(td):
        return struct.unpack("<I", td[addr:addr+4])[0]
    return None

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB + CS_MODE_LITTLE_ENDIAN)
md.detail = True

regs = {}   # reg -> ("imm", val) or ("lit", litaddr, relocname)
GPIO = ("gpio_request","gpio_to_desc","gpiod_direction_output_raw",
        "gpiod_set_raw_value","gpiod_direction_input","gpio_free")

def rv(r):
    v = regs.get(r)
    if not v: return None
    if v[0]=="imm": return v[1]
    if v[0]=="lit":
        return lit32(v[1])
    return None

print("=== GPIO calls with resolved pin numbers ===")
for insn in md.disasm(td, 0):
    mn, ops = insn.mnemonic, insn.op_str
    if mn.startswith("ldr") and "[pc" in ops:
        rd = ops.split(",")[0].strip()
        # imm
        try:
            off = int(ops.split("#")[1].rstrip("]").strip(), 0)
        except:
            off = None
        if off is not None:
            base = (insn.address + 4) & ~3
            lit = base + off
            regs[rd] = ("lit", lit)
    elif mn in ("mov","movs","movw") and "#" in ops:
        p = ops.split(",")
        if len(p)==2:
            rd=p[0].strip()
            try: regs[rd]=("imm", int(p[1].strip().lstrip("#"),0))
            except: pass
    if mn in ("bl","blx"):
        info = rels.get(insn.address)
        tgt = info[0] if info else None
        if tgt and any(g==tgt for g in GPIO):
            r0 = rv("r0"); r1 = rv("r1")
            # resolve label pointer if r1 is a lit with a reloc at that lit addr
            label = None
            v1 = regs.get("r1")
            if v1 and v1[0]=="lit":
                rl = rels.get(v1[1])
                if rl: label = rl[0]
            print(f"  @{insn.address:#06x} {tgt:28s} pin(r0)={r0}  r1={r1} label={label}")
