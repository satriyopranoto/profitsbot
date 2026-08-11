import struct

def probe(path, label):
    print(f"===== {label}: {path} =====")
    with open(path, "rb") as f:
        data = f.read(1_000_000)
    assert data[:2] == b"MZ", "bukan PE"
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe_off:pe_off+4] == b"PE\0\0", "PE header rusak"
    machine = struct.unpack_from("<H", data, pe_off+4)[0]
    nsec = struct.unpack_from("<H", data, pe_off+6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off+20)[0]
    opt = pe_off + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    print(f"  machine=0x{machine:04X} ({'x86' if machine==0x14C else 'x64' if machine==0x8664 else '?'}) sections={nsec} opt_magic=0x{magic:04X} ({'PE32' if magic==0x10B else 'PE32+' if magic==0x20B else '?'})")
    sec_off = opt + opt_size
    names = []
    for i in range(min(nsec, 12)):
        nm = data[sec_off + i*40: sec_off + i*40 + 8].rstrip(b"\0").decode("latin1", "replace")
        names.append(nm)
    print(f"  sections: {names}")
    blob = data.lower()
    for key in [b"mscoree", b".net framework", b"electron", b"app.asar", b"node.exe", b"upx", b"nullsoft", b"inno setup", b"python3", b"pyinstaller", b"nuitka", b"tcl", b"go build"]:
        if key in blob:
            print(f"  PENANDA: {key.decode()}")
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 128))
        tail = f.read(128)
    print(f"  size={size/1e6:.1f}MB, tail: {'NullsoftInst' if b'NullsoftInst' in tail else '-'}")

probe(r"C:\Users\satri\Downloads\profits.exe", "profits.exe (6.3MB)")
probe(r"C:\Users\satri\Downloads\profits-setup.exe", "profits-setup.exe (104MB)")
