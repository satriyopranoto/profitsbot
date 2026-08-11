import struct, re, os

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

pe_off = struct.unpack_from("<I", data, 0x3C)[0]
nsec = struct.unpack_from("<H", data, pe_off+6)[0]
opt_size = struct.unpack_from("<H", data, pe_off+20)[0]
sec_off = pe_off + 24 + opt_size

target = None
for i in range(nsec):
    nm = data[sec_off + i*40: sec_off + i*40 + 8].rstrip(b"\0").decode("latin1")
    vsize = struct.unpack_from("<I", data, sec_off + i*40 + 8)[0]
    rawsize = struct.unpack_from("<I", data, sec_off + i*40 + 16)[0]
    rawptr = struct.unpack_from("<I", data, sec_off + i*40 + 20)[0]
    print(f"  {nm:10s} vsize={vsize:>9} rawsize={rawsize:>9} rawptr=0x{rawptr:X}")
    if nm == ".taubndl":
        target = (rawptr, rawsize)

if not target:
    print("  .taubndl tidak ketemu"); raise SystemExit
rawptr, rawsize = target
bundle = data[rawptr:rawptr+rawsize]
print(f"\n.taubndl: {rawsize} bytes")
os.makedirs(r"C:\Users\satri\code\profits_extract", exist_ok=True)
with open(r"C:\Users\satri\code\profits_extract\taubndl.bin", "wb") as f:
    f.write(bundle)

# 1) gzip magic?
gz = [m.start() for m in re.finditer(b"\x1f\x8b\x08", bundle)]
print(f"  gzip magic hits: {len(gz)}")
# 2) printable strings panjang (JS/HTML?)
strs = re.findall(rb"[ -~\t]{40,}", bundle)
print(f"  printable runs >=40: {len(strs)}")
for s in strs[:12]:
    print("   >", s[:90].decode("latin1", "replace"))
# 3) path-like strings
paths = re.findall(rb"[a-zA-Z0-9_./-]{6,60}\.(?:js|html|css|svg|png|woff2?|json|ico)", bundle)
print(f"  path-like: {len(paths)}")
for p in sorted(set(paths))[:20]:
    print("   >", p.decode("latin1"))
