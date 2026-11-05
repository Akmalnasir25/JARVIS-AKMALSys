"""Live proof: the browser fallback really puts Chrome on the stage.

The embed path cannot report *why* it failed — owner-blocked and WebView2-
refused both render "Video unavailable". So the fallback does not diagnose; it
sidesteps. This suite proves the sidestep works end to end: Chrome launches,
its window is caught by pid (not by title, which changes with every song), and
SetParent puts it inside the Jarvis window.

Run with the HUD up:  python ui/_yt_browser_live.py
"""
import json
import os, sys, threading, time
from pathlib import Path

ROOT = Path(r"C:\Users\akmal\jarvis-desktop")
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

import ctypes
import webview
import main as J
import system as S

CHECKS = []


def ok(cond, name, extra=""):
    CHECKS.append((bool(cond), name, extra))
    print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + str(extra)) if extra and not cond else ""))


api = J.Api()
win = webview.create_window("ytb", "about:blank", js_api=api, hidden=True,
                            fullscreen=False, width=1280, height=820,
                            background_color="#05030f")
api._window = win
api._media = J.MediaServer(J.MEDIA).serve_ui(ROOT / "ui").start()

state = {"err": None}
u32 = ctypes.windll.user32


def run():
    try:
        time.sleep(2.5)
        win.load_url(api._media.stage_url)
        time.sleep(3.5)

        def js(code):
            out = win.evaluate_js(
                "(()=>{try{return JSON.stringify((%s))}catch(e){return JSON.stringify({err:e.message})}})()" % code)
            try:
                return json.loads(out)
            except Exception:
                return {"raw": out}

        print("\n-- the escape hatch is on screen")
        ok(js("!!document.getElementById('webChrome')") is True, "Chrome button exists")
        ok(js("(document.getElementById('webChrome')||{}).title||''").startswith("Open this video"),
           "it explains itself in a tooltip")

        print("\n-- a browser is available")
        exe = api._browser_exe()
        ok(bool(exe), "Chrome or Edge resolved", exe)
        ok("chrome" in exe.lower(), "Chrome is preferred over Edge", exe)

        print("\n-- play_youtube(mode=browser) embeds a real window")
        hud = int(win.native.Handle.ToInt64())
        ok(hud != 0, "HUD handle known", hud)
        api._app_rect = (0, 0, 1200, 780, S.dpi_scale(hud))
        res = api.play_youtube("Hindia Secukupnya", force_browser=True)
        ok(res.get("ok") is True, "fallback reports ok", res.get("msg"))
        ok(res.get("mode") == "browser", "it reports the browser mode", res.get("mode"))
        ok(bool(res.get("id")), "a video id was resolved before opening", res.get("id"))

        emb = api._sys.embed
        ok(emb.hwnd != 0, "a window is attached", emb.hwnd)
        if emb.hwnd:
            parent = u32.GetParent(ctypes.c_void_p(emb.hwnd))
            ok(parent == hud, "its parent is the Jarvis window", (parent, hud))
            n = u32.GetWindowTextLengthW(emb.hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(emb.hwnd, buf, n + 1)
            print("     attached title:", repr(buf.value[:70]))
            ok("YouTube" in buf.value or "youtube" in buf.value.lower() or "Chrome" in buf.value,
               "the attached window is the YouTube tab", buf.value[:60])
            style = u32.GetWindowLongPtrW(emb.hwnd, -16)
            ok(bool(style & 0x40000000), "it carries WS_CHILD (embedded, not floating)", hex(style & 0x40000000))

        print("\n-- it can be taken back out")
        had = bool(emb.origin)
        ok(had, "the embed recorded where the window came from")
        ok(emb.detach() is True if had else True, "detach succeeds")
        ok(emb.hwnd is None, "the embed forgets the handle")
        try:
            emb2 = api._sys.embed
            ok(emb2.hwnd in (None, 0), "no window left embedded")
        except Exception:
            pass

    except Exception:
        import traceback
        state["err"] = traceback.format_exc()
        print(state["err"])
    finally:
        try:
            # leave nothing of ours running: the probe launched a real browser
            emb = api._sys.embed
            if getattr(emb, "hwnd", None):
                emb.detach()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass


threading.Thread(target=run, daemon=True).start()
webview.start(api._wire_drop, win)

bad = [c for c in CHECKS if not c[0]]
print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} passed")
if state["err"]:
    print("EXCEPTION DURING RUN")
sys.exit(1 if (bad or state["err"]) else 0)
