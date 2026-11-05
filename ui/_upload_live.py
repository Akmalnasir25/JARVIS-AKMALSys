"""Live proof: a folder picked in the HUD becomes a drawn report + a listing.

Drives the real Api against a real fixture folder, then reads the DOM back.
The File… dialog cannot be automated, so this calls analyse_path — the exact
method the dialog handler and the drop bridge both land on.
"""
import json
import os, shutil, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(r"C:\Users\akmal\jarvis-desktop")
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

import webview
import main as J

CHECKS = []
def ok(cond, name, extra=""):
    CHECKS.append((bool(cond), name, extra))
    print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + str(extra)) if extra and not cond else ""))


def fixture(tmp: Path) -> Path:
    d = tmp / "Projek Report Ujian"
    (d / "src" / "utils").mkdir(parents=True)
    (d / "assets" / "img").mkdir(parents=True)
    (d / "reports").mkdir()
    for i in range(12):
        (d / "src" / f"mod_{i:02d}.py").write_text("x = %d\n" % i * 30, encoding="utf-8")
    for i in range(8):
        (d / "src" / "utils" / f"helper_{i}.js").write_text("export const a=%d;\n" % i, encoding="utf-8")
    for i in range(6):
        (d / "assets" / "img" / f"shot_{i}.png").write_bytes(b"\x89PNG" + bytes([i]) * 40000)
    (d / "reports" / "laporan.pdf").write_bytes(b"%PDF-1.4" + b"p" * 900000)
    (d / "reports" / "data.xlsx").write_bytes(b"PK\x03\x04" + b"x" * 200000)
    (d / "README.md").write_text("# Projek\n\nContoh.\n", encoding="utf-8")
    (d / "notes.txt").write_bytes(b"")
    blob = os.urandom(90000)
    (d / "assets" / "dupe-1.bin").write_bytes(blob)
    (d / "assets" / "dupe-2.bin").write_bytes(blob)
    (d / "node_modules" / "x").mkdir(parents=True, exist_ok=True)
    (d / "node_modules" / "x" / "ignore.js").write_text("no", encoding="utf-8")
    return d


def grab(hwnd, path):
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0 or rect.left < -10000:
        return False
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)
    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(hwnd, hdc)
    return True


api = J.Api()
api._media = J.MediaServer(J.MEDIA).serve_ui(ROOT / "ui").start()
win = webview.create_window("Jarvis", api._media.stage_url, js_api=api,
                            fullscreen=False, width=1600, height=1000,
                            background_color="#05030f")
api._window = win

tmp = Path(tempfile.mkdtemp(prefix="upload_fix_"))
target = fixture(tmp)

state = {"err": None}


def run():
    try:
        time.sleep(3.0)
        win.evaluate_js("(()=>{try{window.stageShow('docs');return 'ok'}catch(e){return e.message}})()")
        time.sleep(0.7)

        shot_dir = ROOT / "ui" / "_live"
        shot_dir.mkdir(exist_ok=True)
        hwnd = int(win.native.Handle.ToInt64())

        def js(code, tag):
            out = win.evaluate_js("(()=>{try{return JSON.stringify((%s))}catch(e){return JSON.stringify({err:e.message})}})()" % code)
            try:
                v = json.loads(out)
            except Exception:
                v = {"raw": out}
            if isinstance(v, dict) and "err" in v:
                print(f"    js[{tag}] error: {v['err']}")
            return v

        # ---- folder ----
        res = api.analyse_path(None, [str(target)])
        time.sleep(1.4)
        ok(res.get("ok"), "folder analyse_path returns ok", res.get("msg"))
        ok("Projek Report Ujian" in (res.get("title") or ""), "report titled after the folder",
           res.get("title"))

        ok(js("document.querySelectorAll('.ana-card').length", "cards") == 4,
           "four cards drawn", js("document.querySelectorAll('.ana-card').length", "cards2"))
        charts = js("document.querySelectorAll('.achart').length", "charts")
        ok(1 <= charts <= 4, "charts drawn", charts)
        ok(js("document.querySelectorAll('.achart .adonut svg').length", "donut") >= 1,
           "donut chart present")
        ok(js("document.querySelectorAll('.achart .arow').length", "bars") >= 3,
           "bar rows present")
        ok(js("document.querySelectorAll('.aline svg').length", "line") >= 0, "line probe does not throw")
        ok(js("document.querySelectorAll('.ana-point').length", "points") >= 3,
           "narration points rendered", js("document.querySelectorAll('.ana-point').length", "p2"))
        ok(js("document.querySelector('.ana-title')?.textContent||''", "t").startswith("Report"),
           "pane title says Report")

        lit = js("document.querySelectorAll('.achart.lit').length", "lit")
        ok(lit == charts, "every chart revealed itself without narration", (lit, charts))

        # ---- listing in the docs pane ----
        rows = js("document.querySelectorAll('#docBody .feed-row:not(.head)').length", "rows")
        ok(rows == 32,  "listing shows every real file", rows)
        ok(js("document.querySelectorAll('#docBody .feed-row.head').length", "head") == 1,
           "listing has exactly one header row")
        ok(js("(()=>{const n=[...document.querySelectorAll('#docBody .feed-row .nm')].map(e=>e.textContent);return n.some(x=>x.indexOf('node_modules')>=0)})()", "nm") is False,
           "node_modules excluded from the listing")

        # ---- content checks on the measured facts ----
        facts = json.loads(js("document.querySelector('.ana-sum')?.textContent||'{}'", "sum") or '"{}"') \
            if False else None
        cards = js("[...document.querySelectorAll('.ana-card')].map(c=>c.textContent)", "ct")
        flat = " ".join(cards) if isinstance(cards, list) else str(cards)
        ok("32" in flat, "measured file count appears in a card", flat[:200])

        # folder screenshot
        api._push("window.stageShow('docs')")
        time.sleep(0.5)
        grab(hwnd, shot_dir / "11-upload-listing.png")
        api._push("window.stageShow('ana')")
        time.sleep(0.6)
        grab(hwnd, shot_dir / "12-upload-report.png")

        # ---- single file ----
        res2 = api.analyse_path(str(target / "src" / "mod_03.py"))
        time.sleep(1.2)
        ok(res2.get("ok"), "single file analyse_path returns ok", res2.get("msg"))
        ok(js("document.querySelectorAll('.ana-card').length", "c") == 4, "file report draws four cards")
        fc = js("[...document.querySelectorAll('.ana-card')].map(c=>c.textContent).join(' | ')", "fc")
        ok("py" in str(fc), "file report names the extension", str(fc)[:160])

        # ---- multiple files ----
        res3 = api.analyse_path(None, [str(target / "README.md"), str(target / "reports" / "laporan.pdf")])
        time.sleep(1.0)
        ok(res3.get("ok"), "multi-select analyse_path returns ok", res3.get("msg"))
        ok(js("document.querySelectorAll('.ana-card').length", "m") == 4, "multi report draws four cards")

        # ---- guards ----
        bad = api.analyse_path("C:\\Windows\\System32\\drivers\\etc\\hosts")
        ok(not bad.get("ok"), "path outside the workspace is refused", bad.get("msg"))
        miss = api.analyse_path(str(target / "does-not-exist.txt"))
        ok(not miss.get("ok"), "missing path is refused with a reason", miss.get("msg"))
        many = api.analyse_path(None, [str(target / "README.md")] * 20)
        ok(not many.get("ok"), "more than twelve targets is refused", many.get("msg"))

        # ---- drop bridge is wired, not just present ----
        ok(js("typeof window.stagePick === 'function'", "sp") is True, "drop bridge hook exists")
        ok(js("typeof window.stageFeed === 'function'", "sf") is True, "listing hook exists")
        ok(js("!!document.getElementById('dropVeil')", "dv") is True, "drop veil element exists")
        ok(js("!!document.getElementById('docPickFile') && !!document.getElementById('docPickDir')", "bt") is True,
           "File and Folder buttons exist")
        ok(js("(()=>{const v=document.getElementById('dropVeil');v.classList.add('on');const r=getComputedStyle(v).display;v.classList.remove('on');return r})()", "veil") == "grid",
           "veil actually shows when armed")

    except Exception as e:
        import traceback
        state["err"] = traceback.format_exc()
        print(state["err"])
    finally:
        try:
            win.destroy()
        except Exception:
            pass


threading.Thread(target=run, daemon=True).start()
webview.start(api._wire_drop, win)
shutil.rmtree(tmp, ignore_errors=True)

bad = [c for c in CHECKS if not c[0]]
print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} passed")
if state["err"]:
    print("EXCEPTION DURING RUN")
sys.exit(1 if (bad or state["err"]) else 0)
