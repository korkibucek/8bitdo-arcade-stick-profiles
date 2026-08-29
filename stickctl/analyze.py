import sys

blob = open(sys.argv[1] if len(sys.argv) > 1 else "config_dump.bin", "rb").read()
print(f"{len(blob)} bytes\n")

# hex dump with offsets
for i in range(0, len(blob), 16):
    row = blob[i : i + 16]
    hexs = " ".join(f"{b:02x}" for b in row)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
    print(f"{i:03x} ({i:3d})  {hexs:<48}  {asc}")

print("\n--- u32 LE scan for 0x20xxxxxx enable flags ---")
for i in range(0, len(blob) - 3):
    v = int.from_bytes(blob[i : i + 4], "little")
    if v & 0xFFFF0000 == 0x20190000 or v == 0x20190911:
        print(f"  @0x{i:03x} ({i}): {v:08x}")
