import re

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

# cari HTML mentah / JS mentah
for pat in [rb"<!DOCTYPE", rb"<!doctype", rb"<html", rb"</html>", rb"<script", rb"</script>",
            rb"<body", rb"<div id", rb"<style", rb"type=\"module\"", rb"window\.__TAURI__"]:
    hits = [m.start() for m in re.finditer(pat, data)]
    print(f"{pat.decode():22s} -> {len(hits)} hits" + (f"  pertama@0x{hits[0]:X}" if hits else ""))

# path assets (dari konteks tadi: strings panjang dengan path)
paths = re.findall(rb"(?:assets/)?[A-Za-z0-9_./-]+\.(?:js|css|html|svg|png|woff2?|json|ico|wasm)", data)
uniq = sorted(set(p.decode("latin1") for p in paths))
print(f"\npath-like unik: {len(uniq)}")
for p in uniq[:40]:
    print("  >", p)

# cari potongan JS yang terbaca (function/const/arrow) — sampel
js_hints = re.findall(rb"(?:function\s+\w+|const\s+\w+\s*=|let\s+\w+\s*=|=>)", data)
print(f"\nJS syntax hints: {len(js_hints)}")
