import sys

import capstone
import pefile

DLL = r"C:\Users\rober\Downloads\8BitDo-Ultimate-Software-for-Windows\╛½╙ó╚φ╝■V2.16\8BitDoAdvance.dll"
pe = pefile.PE(DLL)
base = pe.OPTIONAL_HEADER.ImageBase
img = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def export_rva(name):
    for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if e.name and e.name.decode().startswith(name):
            return e.address
    raise SystemExit(f"{name} not found")


def resolve_thunk(rva):
    # follow a single jmp rel32 thunk if present
    data = img[rva : rva + 5]
    insns = list(md.disasm(data, base + rva))
    if insns and insns[0].mnemonic == "jmp":
        target = int(insns[0].op_str, 16)
        return target - base
    return rva


name = sys.argv[1] if len(sys.argv) > 1 else "_readArcadeStick"
count = int(sys.argv[2]) if len(sys.argv) > 2 else 300
rva = resolve_thunk(export_rva(name))
print(f"; {name} real body @ RVA 0x{rva:X}")
data = img[rva : rva + count * 8]
n = 0
for insn in md.disasm(data, base + rva):
    print(f"{insn.address - base:06X}  {insn.mnemonic:<7} {insn.op_str}")
    n += 1
    if n >= count or insn.mnemonic == "ret":
        break
