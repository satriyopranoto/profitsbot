import re

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

pats = [rb'<div id="root"', rb'type="module" crossorigin', rb'<html lang=', rb'<link rel="stylesheet"',
        rb'<!DOCTYPE html>', rb'id="app"', rb'<main', rb'__vite__', rb'vite/preload-helper']
for p in pats:
    hits = [m.start() for m in re.finditer(p, data)]
    if hits:
        print(f"{p.decode():28s} -> {len(hits)} hits, pertama @0x{hits[0]:X}")
        for h in hits[:3]:
            print(f"      konteks: {data[h:h+120].decode('utf-8','replace')!r}")

# cari JS bundle: pola khas akhir Vite: '/*! ... */' atau sourceMappingURL
for p in [rb"sourceMappingURL", rb"//# sourceMappingURL", rb"produced by", rb"webpack"]:
    hits = [m.start() for m in re.finditer(p, data)]
    print(f"{p.decode():28s} -> {len(hits)} hits" + (f" pertama @0x{hits[0]:X}" if hits else ""))
