import re, os

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

def printable_ratio(b):
    if not b:
        return 0
    return sum(1 for x in b if 9 <= x <= 13 or 32 <= x < 127) / len(b)

targets = [b"/assets/index-BUMcGDRC.js", b"/assets/index-CbZLwW9f.css",
           b"/index.html", b"/favicon.ico"]
for t in targets:
    idx = data.find(t)
    if idx < 0:
        print(f"{t.decode():35s} TIDAK ADA")
        continue
    print(f"\n=== {t.decode()} @ 0x{idx:X} ===")
    # coba: data di BEKALANG path: [len][data][path\0] -> len di idx-4
    ln = int.from_bytes(data[idx-4:idx], "little")
    blob = data[idx-ln:idx]
    print(f"  [A] len@idx-4={ln} printable={printable_ratio(blob):.2f} head={blob[:40]!r}")
    # coba: [len][path\0][data] -> data setelah path\0
    after = idx + len(t) + 1
    ln2 = int.from_bytes(data[after:after+4], "little")
    blob2 = data[after+4:after+4+ln2]
    print(f"  [B] len@path+1={ln2} printable={printable_ratio(blob2):.2f} head={blob2[:40]!r}")
    # coba: data di BELAKANG dengan len 8-byte
    ln3 = int.from_bytes(data[idx-8:idx], "little")
    blob3 = data[idx-ln3:idx]
    print(f"  [C] len8@idx-8={ln3} printable={printable_ratio(blob3):.2f}")
    # coba: cari </script> atau <style di dekat path (dalam 2MB)
    for pat in [b"</script>", b"<style", b"function", b"const ", b"(()=>", b"exports"]:
        j = data.find(pat, idx - 2_000_000, idx)
        print(f"  [D] {pat.decode():10s} sebelum path: {'@0x%X' % j if j != -1 else '-'}")
