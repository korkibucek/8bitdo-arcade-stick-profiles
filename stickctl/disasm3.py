import sys

import capstone
import pefile

DLL = r"C:\Users\rober\Downloads\8BitDo-Ultimate-Software-for-Windows\╛½╙ó╚φ╝■V2.16\8BitDoAdvance.dll"
pe = pefile.PE(DLL)
base = pe.OPTIONAL_HEADER.ImageBase
img = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

va = int(sys.argv[1], 16)
count = int(sys.argv[2]) if len(sys.argv) > 2 else 120
rva = va - base
data = img[rva : rva + count * 8]
print(f"; VA 0x{va:X} (RVA 0x{rva:X})")
n = 0
for insn in md.disasm(data, va):
    print(f"{insn.address - base:06X}  {insn.mnemonic:<7} {insn.op_str}")
    n += 1
    if n >= count or insn.mnemonic == "ret":
        break
