"""Launch gate, live — against a real running HUD.

Covers the two faults that made the Desktop shortcut look dead:
  1. a lock whose owner has no window used to block every launch forever
  2. a second launch could not see the first instance's window, because the
     lookup only searched its own pid

Run with a HUD already up:  python ui/_launch_live.py
"""
import ctypes
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
u32 = ctypes.windll.user32


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))


def window_title(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


print("\n-- a real HUD is on screen")
hwnd = M._hud_hwnd()
check("_hud_hwnd finds a window", hwnd != 0, hwnd)
if hwnd:
    print("     hwnd=%s title=%r old_owner=%s" % (hwnd, window_title(hwnd), M._lock_owner()))

print("\n-- _jarvis_pids sees other instances, not just itself")
pids = M._jarvis_pids()
check("at least two pids considered (self + HUD)", len(pids) >= 2, pids)
check("self is always included", os.getpid() in pids, pids)
check("the lock owner is included", M._lock_owner() in pids or M._lock_owner() == 0, pids)

print("\n-- already_running restores rather than blocks")
before = len([p for p in M._jarvis_pids()])
r = M.already_running()
check("already_running is True while a HUD exists", r is True, r)
check("restoring spawns nothing new", len(M._jarvis_pids()) <= before + 1)

print("\n-- minimized HUD is restored to the foreground")
if hwnd:
    u32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    time.sleep(0.7)
    check("window is minimized", bool(u32.IsIconic(hwnd)))
    M.already_running()
    time.sleep(0.9)
    check("window is no longer minimized", not u32.IsIconic(hwnd))
    check("window is visible", bool(u32.IsWindowVisible(hwnd)))

print("\n-- stale lock with no window: the reap path")
scratch = Path(tempfile.mkdtemp(prefix="jarvis_stale_"))
(scratch / "main.py").write_text("import time\ntime.sleep(300)\n", encoding="utf-8")
orphan = subprocess.Popen([sys.executable, str(scratch / "main.py")])
time.sleep(1.0)
try:
    check("the orphan is recognized as a Jarvis pid", M._alive(orphan.pid) is True, orphan.pid)
    check("the orphan has no window", M._hud_hwnd([orphan.pid]) == 0)
    gone = M._reap([orphan.pid])
    check("_reap ends it", orphan.pid in gone, gone)
    orphan.wait(timeout=8)
    check("the orphan really exited", orphan.poll() is not None)
    check("a reaped pid is not alive", M._alive(orphan.pid) is False)
finally:
    try:
        orphan.kill()
    except Exception:
        pass

print("\n-- _reap refuses to kill itself")
self_gone = M._reap([os.getpid()])
check("self is never in the reap list", os.getpid() not in self_gone, self_gone)
check("still alive after asking to reap self", M._alive(os.getpid()) is True)

print("\n-- crash path is visible, not silent")
d = Path(tempfile.mkdtemp(prefix="jarvis_log_"))
M.STARTUP_LOG = d / "startup.log"
M.LOCK = d / "jarvis.lock"
M._note("CRASH\nTraceback (most recent call last):\n  File \"x\"\nAttributeError: boom")
txt = M.STARTUP_LOG.read_text(encoding="utf-8")
check("traceback lands in the log", "AttributeError: boom" in txt, txt[:120])
check("log line is timestamped and pid-stamped", "pid=" in txt and "2026-" in txt)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  failed:", f)
sys.exit(1 if FAIL else 0)
