"""test_market_closed_log.py — uji log 'market CLOSED' tidak spam (paritas protraderbot).
Jalankan: ./.venv/Scripts/python.exe test_market_closed_log.py
"""
import sys, time
sys.path.insert(0, r'C:\Users\satri\code\profitsbot')
import profits_bot as P


class Stop(BaseException):
    """BaseException -> tidak tertangkap 'except Exception' di dalam run_loop."""


class FakeBot:
    live = False

    def __init__(self):
        self.logs = []
        self.scans = 0

    def log(self, *a):
        self.logs.append(" ".join(str(x) for x in a))

    def scan_signals(self, interval=None):
        self.scans += 1
        raise Stop()


# urutan: tutup, tutup, buka, buka  -> harus cetak CLOSED 1x + OPEN 1x
seq = [False, False, True, True, True]
state = {"i": 0}


def fake_market_open(*a, **k):
    v = seq[min(state["i"], len(seq) - 1)]
    state["i"] += 1
    return v


time.sleep = lambda _s: None       # jangan benar-benar tidur 60s
P.market_open = fake_market_open

b = FakeBot()
try:
    P.run_loop(b, cycle_minutes=1, interval="30m", auto_execute=False, min_score=1)
except Stop:
    pass

closed = [l for l in b.logs if "market CLOSED" in l]
opened = [l for l in b.logs if "market OPEN" in l]
print("log bot:")
for l in b.logs:
    print("   ", l)
print(f"\npanggilan market_open: {state['i']} (2 tutup + 1 buka), scan_signals: {b.scans}")

assert state["i"] == 3, f"harus 3 iterasi (2 tutup, 1 buka), dapat {state['i']}"
assert len(closed) == 1, f"'market CLOSED' harus 1x, dapat {len(closed)}"
assert len(opened) == 1, f"'market OPEN' harus 1x, dapat {len(opened)}"
assert b.scans == 1, f"scan harus jalan 1x, dapat {b.scans}"
assert closed[0].startswith("market CLOSED ("), f"format waktu hilang: {closed[0]}"
print("\nSEMUA TEST LULUS (3/3 assertion)")
