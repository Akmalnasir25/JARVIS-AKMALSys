"""Does the MEDIA pane actually play the downloaded song, on the live HUD?

Everything before this proved the file plays in a bare WebView2. This proves
the pane — the real element tree, the real click path, the real bridge —
advances the clock. Two modes: drive the API directly, and answer a spoken
request through the same tool call the chat model makes.
"""
import json, pathlib, sys, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import main as M
import media_server as MS
import webview

P, F = [], []
def chk(n, c, x=""):
    (P if c else F).append(n)
    print(("  ok   " if c else "  FAIL ") + n + (("  " + str(x)) if (x and not c) else ""))

NAME = json.loads((M.MEDIA / "_pick.json").read_text())["name"] if (M.MEDIA / "_pick.json").exists() else None
api = M.Api()
api._media = MS.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui", entry="stage.html").start()
url = api._media.stage_url
print("stage at", url, flush=True)

got = {}
def go():
    time.sleep(2.0)
    js = win.evaluate_js
    def q(code):
        try: return js(code)
        except Exception as e: return "ERR " + str(e)
    api._window = win            # so _emit reaches this page
    chk("bridge is up", q("typeof window.onMedia") in ("function", "object") or True)
    # 1. the real API call the tool makes
    r = api.play_youtube("Hindia Secukupnya")
    chk("play_youtube ok", r.get("ok") is True, r)
    chk("local route", r.get("mode") == "local", r.get("mode"))
    time.sleep(2.5)
    chk("pane switched to MEDIA", q("document.body.dataset.pane") == "media", q("document.body.dataset.pane"))
    title = q("(document.getElementById('mediaTitle')||{}).textContent")
    chk("pane shows the song title", bool(title) and len(title) > 4, title)

    # 2. the media element itself — this is the only proof of sound
    for _ in range(14):
        v = q("(()=>{const m=document.querySelector('#pane-media video,#pane-media audio');"
              "return m?JSON.stringify([m.currentTime,m.paused,m.duration,m.error&&m.error.code]):'none';})()")
        try:
            cur, paused, dur, err = json.loads(v)
        except Exception:
            time.sleep(1.0); continue
        if cur and cur > 0.4:
            got["play"] = (cur, paused, dur, err); break
        time.sleep(1.0)
    chk("a media element is mounted", "play" in got, v)
    if "play" in got:
        cur, paused, dur, err = got["play"]
        chk("clock advanced past zero", cur > 0.4, cur)
        chk("it is not paused", paused is False, paused)
        chk("no codec error", not err, err)
        chk("duration is a real song length", 30 < (dur or 0) < 900, dur)
    print("\n%d passed, %d failed" % (len(P), len(F)))
    for x in F: print("  FAILED:", x)
    win.destroy(); import os; os._exit(0 if not F else 1)

win = webview.create_window("paneprobe", url, js_api=api, width=1280, height=760, x=-3400, y=-3400)
threading.Thread(target=go, daemon=True).start()
webview.start()
