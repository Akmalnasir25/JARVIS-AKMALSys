"""Launch-gate logic, no GUI.

The bug this locks down: `already_running()` used a named mutex as its only
evidence that Jarvis was up. A mutex outlives the window — it lives as long as
*anyone* who created it is still breathing. On 5 Nov a pythonw from 1:22 PM sat
at 1468 s of CPU with zero windows, holding that mutex, so every click on the
Desktop shortcut exited at the first line of `main()` and looked like nothing
happened, forever.

Run:  python ui/_launch_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as M

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))


def temp_lock():
    d = Path(tempfile.mkdtemp(prefix="jarvis_lock_"))
    M.LOCK = d / "jarvis.lock"
    M.STARTUP_LOG = d / "startup.log"
    return d


print("\n-- _note / startup log")
temp_lock()
M._note("probe line")
txt = M.STARTUP_LOG.read_text(encoding="utf-8")
check("startup.log written", "probe line" in txt, txt[:80])
check("startup.log carries the pid", ("pid=%d" % os.getpid()) in txt, txt[:80])
M.STARTUP_LOG.write_text("x" * (300 * 1024), encoding="utf-8")
M._note("after rotate")
check("oversized log is truncated, not grown",
      M.STARTUP_LOG.stat().st_size < 4096, M.STARTUP_LOG.stat().st_size)

print("\n-- _alive")
check("pid 0 is not alive", M._alive(0) is False)
check("a wildly absent pid is not alive", M._alive(999_999_999) is False)
check("this process counts as alive", M._alive(os.getpid()) is True)

dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
check("a reaped child is not alive", M._alive(dead.pid) is False, dead.pid)

scratch = Path(tempfile.mkdtemp(prefix="jarvis_impostor_"))
(scratch / "main.py").write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
impostor = subprocess.Popen([sys.executable, str(scratch / "main.py")])
time.sleep(0.6)
bystander = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
time.sleep(0.6)
try:
    check("a live process running main.py counts as Jarvis", M._alive(impostor.pid) is True, impostor.pid)
    check("a live process NOT running main.py does not", M._alive(bystander.pid) is False, bystander.pid)

    print("\n-- lock file")
    temp_lock()
    check("missing lock reads as no owner", M._lock_owner() == 0)
    ok, old = M._take_lock()
    check("take on an empty slot succeeds", ok is True)
    check("take returns no old pid", old == 0)
    check("lock names this process", M._lock_owner() == os.getpid())
    ok2, old2 = M._take_lock()
    check("a second take by the same pid is idempotent", ok2 is True and old2 == 0)

    # stale by death
    M.LOCK.write_text(json.dumps({"pid": dead.pid}), encoding="utf-8")
    check("a dead owner is not an owner", M._lock_owner() == 0, dead.pid)
    ok, old = M._take_lock()
    check("a stale lock can be taken over", ok is True)

    # stale by pid reuse — the lock says a pid that now belongs to something else
    M.LOCK.write_text(json.dumps({"pid": bystander.pid}), encoding="utf-8")
    check("a reused pid does not own the lock", M._lock_owner() == 0, bystander.pid)
    ok, old = M._take_lock()
    check("a reused-pid lock can be taken over", ok is True)

    # genuinely live
    M.LOCK.write_text(json.dumps({"pid": impostor.pid}), encoding="utf-8")
    check("a live Jarvis pid owns the lock", M._lock_owner() == impostor.pid)
    ok, old = M._take_lock()
    check("a live lock blocks the take", ok is False)
    check("the blocked take names the blocker", old == impostor.pid, old)

    # garbage
    M.LOCK.write_text("not json at all", encoding="utf-8")
    check("corrupt lock is treated as no lock", M._lock_owner() == 0)

    print("\n-- _drop_lock")
    M.LOCK.write_text(json.dumps({"pid": impostor.pid}), encoding="utf-8")
    M._drop_lock()
    check("drop leaves someone else's lock alone", M.LOCK.exists())
    M.LOCK.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    M._drop_lock()
    check("drop removes our own lock", not M.LOCK.exists())

    print("\n-- _hud_hwnd / already_running")
    temp_lock()
    # Scoped to a pid that owns no window, so the result does not depend on
    # whether Manuel happens to have the HUD open while this runs. Asking
    # "is any Jarvis window on screen" would pass or fail by luck.
    check("no HUD window for a windowless pid", M._hud_hwnd([bystander.pid]) == 0,
          M._hud_hwnd([bystander.pid]))
    check("no HUD window for an absent pid", M._hud_hwnd([999_999_999]) == 0)
    if M._hud_hwnd() == 0:
        check("already_running is False when nothing is on screen",
              M.already_running() is False)
    else:
        check("already_running is True when a HUD is already up",
              M.already_running() is True)
        print("     (a HUD was open during this run — restore path taken)")

    print("\n-- the real corpse (informational)")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process pythonw -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=25).stdout.split()
        pids = [int(x) for x in out if x.strip().isdigit()]
        if pids:
            for p in pids:
                print("     pythonw pid=%s alive=%s" % (p, M._alive(p)))
        else:
            print("     no pythonw running")
    except Exception as e:
        print("     skipped:", e)
finally:
    for p in (impostor, bystander):
        try:
            p.kill()
        except Exception:
            pass

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  failed:", f)
sys.exit(1 if FAIL else 0)
