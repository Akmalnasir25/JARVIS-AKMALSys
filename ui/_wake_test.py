"""Suite for the wake mic switch: does "off" really close the stream?

The claim being tested is not "the setting changed" — it is "nothing is
listening". So the probe starts the real _mic_loop against a fake input
stream and counts how many times that stream was opened. With wake off the
count must be 0 while idle, and exactly 1 per mic-button press.
"""
import json, pathlib, sys, threading, time, types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import main as J

PASS, FAIL = [], []
def chk(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  " + str(extra)) if (extra and not cond) else ""))

# --- config round trip -------------------------------------------------------
def cfg():
    return json.loads(J.CONFIG.read_text(encoding="utf-8"))

orig = cfg().get("wake_word", True)
api = J.Api()
api._window = None
api._voice_emit = lambda *a, **k: None

r = api.set_wake(False)
chk("set_wake(False) returns ok", r.get("ok") is True, r)
chk("config written to disk", cfg().get("wake_word") is False)
st = api.wake_status()
chk("status.enabled false", st.get("enabled") is False, st)
chk("status.on false (not listening)", st.get("on") is False, st)

r = api.set_wake(True)
chk("set_wake(True) returns ok", r.get("ok") is True, r)
chk("config written back", cfg().get("wake_word") is True)
chk("status.enabled true", api.wake_status().get("enabled") is True)
chk("set_wake rejects nothing (bool coercion)", api.set_wake(0).get("enabled") is False)
api.set_wake(orig)

# --- does the loop actually stop opening the stream? ------------------------
import numpy as np

def run_loop(seconds, presses=0):
    """Run _mic_loop with wake off. Count InputStream opens."""
    config = cfg()
    config["wake_word"] = False
    J.load_json = lambda p, d=None: (config if str(p) == str(J.CONFIG) else
                                     json.loads(p.read_text(encoding="utf-8")))

    opened = {"n": 0, "closed": 0}
    class FakeStream:
        def __init__(self, **kw): opened["n"] += 1
        def __enter__(self): return self
        def __exit__(self, *a): opened["closed"] += 1; return False
        def read(self, n):
            time.sleep(0.01)
            return np.zeros((n, 1), dtype="int16"), None
    fake_sd = types.SimpleNamespace(InputStream=lambda **kw: FakeStream(**kw))
    sys.modules["sounddevice"] = fake_sd

    a = J.Api(); a._window = None
    a._voice_emit = lambda *x, **k: None
    th = threading.Thread(target=a._mic_loop, daemon=True)
    th.start()
    time.sleep(0.4)
    chk("wake off: stream never opened while idle", opened["n"] == 0, opened)
    chk("wake off: wake_ready is false", a._wake_ready is False)

    for _ in range(presses):
        a._listen_request.set()
        time.sleep(0.25)
    if presses:
        chk("mic button opens the stream exactly once", opened["n"] == 1, opened)
        # _capture waits up to 4 s for speech to begin and then gives up, so the
        # close lands after this point — poll for it rather than guessing a delay.
        deadline = time.time() + 12
        while time.time() < deadline and opened["closed"] == 0:
            time.sleep(0.15)
        chk("stream closed again after the capture", opened["closed"] >= 1, opened)
        chk("wake_ready false again after capture", a._wake_ready is False)
    return opened

print("\n[wake off, 0 presses]")
run_loop(1.0, presses=0)
print("\n[wake off, 1 press]")
run_loop(1.2, presses=1)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
