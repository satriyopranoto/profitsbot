"""profits_client.py — klien API Profits (Phintraco) — READ-ONLY.

Auth flow (dari RE bundle JS + capture request asli app via CDP):
  1. POST /identity/login {username, password} -> {token:{accessToken, refreshToken, accessExpired}}
     - password DIENKRIPSI: CryptoJS.AES.encrypt(password, "1231231231231231")
       = OpenSSL salted: prefix "Salted__" + salt(8B) + AES-256-CBC, KDF EvpKDF
       D_i = MD5(D_{i-1} || password || salt), blok terakhir saja (32B key + 16B iv)
     - header authorization: "Bearer" TANPA spasi saat belum ada token!
  2. POST /identity/socket-token/market -> {data: <key>} (Bearer accessToken)
  3. WS  wss://stream.profits.co.id?key=<key>
"""
import base64
import hashlib
import json
import os
import time
import urllib.request
import urllib.error

from Crypto.Cipher import AES

API_BASE = "https://next-dev.profits.co.id/api"
SOCKET_URL = "wss://stream.profits.co.id"  # + path /market (harga) atau /trade (portfolio)
PASS_KEY = "1231231231231231"  # passphrase CryptoJS dari bundle (vA)


def crypto_js_encrypt(plaintext, passphrase):
    """Reproduce CryptoJS.AES.encrypt(plain, pass).toString() (OpenSSL salted).

    KDF CryptoJS EvpKDF (TERVERIFIKASI vs crypto-js asli + decrypt request app):
      D_i = MD5(D_{i-1} || password || salt), D_{-1} = b"", blok TERAKHIR saja.
    Salt acak 8 byte -> output "U2FsdGVkX1..." (base64 Salted__+salt+ct).
    """
    salt = os.urandom(8)
    d = b""
    last = b""
    pw = passphrase.encode()
    while len(d) < 48:  # 32 key + 16 iv
        last = hashlib.md5(last + pw + salt).digest()  # D_i = MD5(D_{i-1} || password || salt) — blok terakhir saja!
        d += last
    key, iv = d[:32], d[32:48]
    pad = 16 - len(plaintext) % 16
    data = plaintext.encode() + bytes([pad]) * pad
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(data)
    return base64.b64encode(b"Salted__" + salt + ct).decode()


def crypto_js_decrypt(cipher_b64, passphrase):
    """Decrypt OpenSSL salted ala CryptoJS (untuk verifikasi/riset)."""
    raw = base64.b64decode(cipher_b64)
    assert raw[:8] == b"Salted__", "bukan format OpenSSL salted"
    salt, ct = raw[8:16], raw[16:]
    d = b""
    last = b""
    pw = passphrase.encode()
    while len(d) < 48:
        last = hashlib.md5(last + pw + salt).digest()
        d += last
    key, iv = d[:32], d[32:48]
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    return pt[:-pt[-1]].decode()

_session = None  # {accessToken, refreshToken, accessExpired}


def load_env(path=".env"):
    """Parse .env sederhana -> os.environ (tanpa dependensi)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _req(method, path, payload=None, token=None, app_header=False):
    url = API_BASE + path
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-HEADER": "t",
        "X-APP-VERSION": "1.3.3",
        "X-APP-BUILD-REV": "8c9ca94.2026-08-10",
        "X-APP-PLATFORM": "windows",
    }
    # PENTING (capture request asli app): tanpa token -> "Bearer" (TANPA spasi);
    # dengan token -> "Bearer <token>".
    headers["Authorization"] = f"Bearer {token}" if token else "Bearer"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"success": False, "status": e.code, "message": body[:300]}
    except Exception as e:
        return {"success": False, "message": str(e)}


def login(username, password):
    """POST /identity/login -> simpan token session.

    Password DIENKRIPSI dulu: CryptoJS.AES.encrypt(password, PASS_KEY)
    (persis app — bundle vA()). Username polos.
    """
    global _session
    enc = crypto_js_encrypt(password, PASS_KEY)
    r = _req("POST", "/identity/login", {"username": username, "password": enc})
    # struktur: {"data": {"user":..., "token": {accessToken, refreshToken, accessExpired}}}
    tok = (r.get("data") or {}).get("token") or r.get("token")
    if not tok:
        return r
    _session = tok
    return r


def get_user_detail():
    if not _session:
        return {"success": False, "message": "belum login"}
    return _req("GET", "/identity/user-detail", token=_session.get("accessToken"))


def generate_market_token():
    """POST /identity/socket-token/market -> {data: <key>}"""
    if not _session:
        return {"success": False, "message": "belum login"}
    return _req("POST", "/identity/socket-token/market", token=_session.get("accessToken"))


def trade_login(pin):
    """POST /identity/trade/login {pin} — login trading (utk order nanti)."""
    if not _session:
        return {"success": False, "message": "belum login"}
    return _req("POST", "/identity/trade/login", {"pin": pin},
                token=_session.get("accessToken"))


if __name__ == "__main__":
    import sys
    load_env()
    u = os.environ.get("PROFITS_USERNAME") or sys.argv[1]
    p = os.environ.get("PROFITS_PASSWORD") or sys.argv[2]
    pin = os.environ.get("PROFITS_PIN") or (sys.argv[3] if len(sys.argv) > 3 else "")
    print("== login ==")
    r = login(u, p)
    if not _session:
        print("  GAGAL:", r)
        sys.exit(1)
    t = _session
    print(f"  OK: accessToken={str(t.get('accessToken'))[:24]}... "
          f"expires_in={t.get('accessExpired')} refresh={bool(t.get('refreshToken'))}")
    print("== user-detail ==")
    print(" ", json.dumps(get_user_detail(), ensure_ascii=False)[:600])
    print("== socket-token/market ==")
    st = generate_market_token()
    key = st.get("data") if st.get("success") else (st.get("data") or "")
    print("  key:", str(key)[:40], "... msg:", st.get("message"))
    if pin:
        print("== trade/login (PIN) ==")
        tr = trade_login(pin)
        print("  ", json.dumps(tr, ensure_ascii=False)[:400])
