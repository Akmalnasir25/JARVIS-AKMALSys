"""Does the wake switch take effect WITHOUT a restart?

The first version of this switch only wrote config.json. _mic_loop read that
file once, at startup — so turning "Hey Jarvis" on would have done nothing
until the next launch. This probe runs the real loop and flips the setting
underneath it.
"""
import json, pathlib, sys, threading, time, types
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import main as J
import numpy as np

PASS, FAIL = [], []
def chk(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("  ok   " if c else "  FAIL ") + n + (("  " + str(x)) if (x and not c) else ""))

def setcfg(on):
    c = json.loads(J.CONFIG.read_text(encoding="utf-8")); c["wake_word"] = on
    J.CONFIG.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")

opened = {"n": 0}
class FakeStream:
    def __init__(self, **kw): opened["n"] += 1
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n):
        time.sleep(0.02)
        return np.zeros((n, 1), dtype="int16"), None
sys.modules["sounddevice"] = types.SimpleNamespace(InputStream=lambda **k: FakeStream(**k))

# A stand-in model: build() imports openwakeword, which may not be installed.
# Patching the import site keeps the probe about the loop's gating, not the
# model's weights.
class StubModel:
    def __init__(self, **kw): pass
    def predict(self, x): return {"hey_jarvis": 0.0}
    def reset(self): pass
fake_mod = types.ModuleType("openwakeword")
fake_mod.model = types.SimpleNamespace(Model=StubModel)
sys.modules["openwakeword"] = fake_mod
sys.modules["openwakeword.model"] = fake_mod.model

setcfg(False)
a = J.Api(); a._window = None
a._voice_emit = lambda *x, **k: None
threading.Thread(target=a._mic_loop, daemon=True).start()
time.sleep(1.2)
chk("starts closed: no stream opened", opened["n"] == 0, opened)
chk("starts closed: wake_ready false", a._wake_ready is False)

print("\n[switch on, no restart]")
setcfg(True)
t = time.time()
while time.time() - t < 6 and not a._wake_ready:
    time.sleep(0.1)
chk("turning it on opens the stream by itself", opened["n"] >= 1, opened)
chk("wake_ready becomes true", a._wake_ready is True)
chk("it reacted in under 3 s", time.time() - t < 3, round(time.time() - t, 2))

print("\n[switch off, no restart]")
setcfg(False)
t = time.time()
while time.time() - t < 6 and a._wake_ready:
    time.sleep(0.1)
chk("turning it off releases the mic", a._wake_ready is False)
chk("it reacted in under 2 s", time.time() - t < 2, round(time.time() - t, 2))
n_after = opened["n"]
time.sleep(1.5)
chk("no stream reopened itself once off", opened["n"] == n_after, opened)

setcfg(False)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
for f in FAIL: print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
