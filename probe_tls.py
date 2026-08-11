path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

checks = {
    "rustls": b"rustls",
    "schannel": b"schannel",
    "sspicli": b"sspicli",
    "native-tls": b"native-tls",
    "aws-lc": b"aws-lc",
    "ring": b"ring-",
    "boring": b"boring",
    "openssl": b"openssl",
    "webpki": b"webpki",
    "reqwest": b"reqwest",
    "hyper": b"hyper-",
    "tokio": b"tokio",
    "winhttp": b"winhttp",
    "wininet": b"wininet",
}
for k, b in checks.items():
    print(f"{k:12s}: {data.count(b)} hits")
