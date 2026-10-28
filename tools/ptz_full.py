import sys, struct
sys.path.insert(0, r"C:/Users/selie/AppData/Local/Temp/pdfdeps")
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
elf = ELFFile(open(r"C:/Users/selie/Documents/analog-ptz-bridge/firmware/stock/res/ptz.ko","rb"))
symtab = elf.get_section_by_name(".symtab")
syms = {i:s.name for i,s in enumerate(symtab.iter_symbols())}
td = elf.get_section_by_name(".text").data()
rels={}
for sec in elf.iter_sections():
    if isinstance(sec,RelocationSection) and sec.name==".rel.text":
        for r in sec.iter_relocations():
            rels[r['r_offset']]=syms.get(r['r_info_sym'],f"s{r['r_info_sym']}")
def lit(a):
    return struct.unpack("<I",td[a:a+4])[0] if a+4<=len(td) else None
md=Cs(CS_ARCH_ARM,CS_MODE_THUMB+CS_MODE_LITTLE_ENDIAN)
for insn in md.disasm(td,0):
    ann=""
    if insn.mnemonic.startswith("ldr") and "[pc" in insn.op_str:
        try:
            off=int(insn.op_str.split("#")[1].rstrip("]"),0)
            base=(insn.address+4)&~3; la=base+off; v=lit(la)
            rn=rels.get(la)
            ann=f"   ; [0x{la:x}]=0x{v:x}({v})" + (f" ->{rn}" if rn else "")
        except: pass
    if insn.address in rels and insn.mnemonic in ("bl","blx"):
        ann=f"   ; -> {rels[insn.address]}"
    print(f"{insn.address:#06x}: {insn.mnemonic:8s} {insn.op_str}{ann}")
