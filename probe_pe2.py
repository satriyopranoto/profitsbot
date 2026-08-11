import struct

def probe(path, label):
    print(f"===== {label} =====")
    with open(path, "rb") as f:
        data = f.read(2_000_000)
    assert data[:2] == b"MZ", "bukan PE"
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    machine = struct.unpack_from("<H", data, pe_off+4)[0]
    nsec = struct.unpack_from("<H", data, pe_off+6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off+20)[0]
    opt = pe_off + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    print(f"  machine=0x{machine:04X} ({'x86' if machine==0x14C else 'x64' if machine==0x8664 else '?'}) sections={nsec} opt=0x{magic:04X}")
    sec_off = opt + opt_size
    names = []
    for i in range(min(nsec, 16)):
        nm = data[sec_off + i*40: sec_off + i*40 + 8].rstrip(b"\0").decode("latin1", "replace")
        names.append(nm)
    print(f"  sections: {names}")
    blob = data.lower()
    for key in [b"pyinstaller", b"pyi-", b"pyz", b"meipass", b"pyarmor", b"python3", b"python39", b"python310",
                b"mscoree", b"electron", b"app.asar", b"upx", b"inno", b"nullsoft", b"nuitka", b"go build"]:
        if key in blob:
            print(f"  PENANDA: {key.decode()}")
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
    print(f"  size={size/1e6:.2f}MB")

probe(r"C:\Users\satri\AppData\Local\Profits\profits.exe", "profits.exe ASLI (AppData, 19.7MB)")
