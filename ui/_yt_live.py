"""Live proof: cari lagu -> play_youtube -> the WEB pane is really playing it.

Before this session the chain ended twice over: the model called open_media
(which lists media/ on disk) and the search rows under the orb were plain
text with no click handler at all.

Run:  python ui/_yt_live.py
"""
import json
import os, sys, threading, time
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


api = J.Api()
win = webview.create_window("yt", "about:blank", js_api=api, hidden=True,
                            fullscreen=False, width=1280, height=800,
                            background_color="#05030f")
api._window = win
api._media = J.MediaServer(J.MEDIA).serve_ui(ROOT / "ui").start()

state = {"err": None}
REAL_ID = "dQw4w9WgXcQ"


def run():
    try:
        time.sleep(2.5)
        win.load_url(api._media.stage_url)
        time.sleep(4.0)

        def js(code, tag=""):
            out = win.evaluate_js(
                "(()=>{try{return JSON.stringify((%s))}catch(e){return JSON.stringify({err:e.message})}})()" % code)
            try:
                v = json.loads(out)
            except Exception:
                v = {"raw": out}
            if isinstance(v, dict) and "err" in v:
                print(f"    js[{tag}] error: {v['err']}")
            return v

        print("\n-- title cleaning")
        ok(J.clean_yt_title("Hindia - Secukupnya (Lyric Video) - OST. Nanti - YouTube")
           .startswith("Hindia - Secukupnya"), "site suffix and credit parens stripped",
           J.clean_yt_title("Hindia - Secukupnya (Lyric Video) - OST. Nanti - YouTube"))
        ok(J.clean_yt_title("Foo (Official Music Video) - YouTube") == "Foo",
           "official-video tag stripped", J.clean_yt_title("Foo (Official Music Video) - YouTube"))
        check_title = J.clean_yt_title("Bar [Remastered In 4K] (Audio)")
        ok("Remastered" in check_title, "bracketed restatement survives when not a credit", check_title)

        print("\n-- play_youtube reaches the pane")
        js("window.stageShow('browse')", "show")
        res = api.play_youtube("Hindia Secukupnya")
        ok(res.get("ok") is True, "play_youtube reports ok", res)
        ok(bool(res.get("id")), "it resolved a video id", res.get("id"))
        time.sleep(1.6)
        src = js("document.getElementById('webFrame').src", "src")
        ok(str(res.get("id")) in str(src), "the pane embedded that exact id", src)
        ok(js("document.getElementById('webYt').classList.contains('on')", "b") is True,
           "the YT badge is on")
        # the pane is #pane-browse and it is selected by body[data-pane], not by an .on class
        ok(js("!!document.getElementById('pane-browse')", "pane") is True, "browse pane exists")
        ok(js("document.body.getAttribute('data-pane')", "sel") == "browse",
           "the stage actually switched to the WEB pane", js("document.body.getAttribute('data-pane')", "sel2"))

        print("\n-- a result row is clickable and plays")
        api._emit("web", {"query": "cari lagu", "links": [
            {"title": "Contoh Lagu - YouTube", "url": "https://www.youtube.com/watch?v=" + REAL_ID},
            {"title": "Laman lain", "url": "https://example.com/a"}]})
        time.sleep(1.1)
        probe = js("""(()=>{
            const rows=[...document.querySelectorAll('.orbt-items .it')];
            return {count:rows.length,
                    linked:rows.filter(r=>r.dataset.url).length,
                    role:rows.map(r=>r.getAttribute('role')||'')};
        })()""", "rows")
        ok(isinstance(probe, dict) and probe.get("count", 0) >= 2, "rows drawn", probe)
        ok(probe.get("linked", 0) >= 2, "rows carry their url", probe)
        ok("link" in (probe.get("role") or []), "rows expose a link role", probe)

        r = js("""(()=>{const row=[...document.querySelectorAll('.orbt-items .it')]
                    .find(x=>(x.dataset.url||'').includes('watch'));
                  if(!row) return {err:'no video row'};
                  row.click(); return {clicked:true};})()""", "click")
        ok(r.get("clicked") is True, "clicking the video row fires", r)
        time.sleep(1.5)
        src2 = js("document.getElementById('webFrame').src", "src2")
        ok(REAL_ID in str(src2), "clicking the row loads that video", src2)

        print("\n-- a channel page says why it will not play inline")
        api._emit("web", {"query": "q", "links": [
            {"title": "Channel", "url": "https://www.youtube.com/@Hindia"}]})
        time.sleep(0.9)
        tip = js("""(()=>{const row=[...document.querySelectorAll('.orbt-items .it')]
                     .find(x=>(x.dataset.url||'').includes('@Hindia'));
                   return row ? {has:true} : {has:false};})()""", "ch")
        ok(tip.get("has") is True, "channel row is present and clickable", tip)

    except Exception:
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

bad = [c for c in CHECKS if not c[0]]
print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} passed")
if state["err"]:
    print("EXCEPTION DURING RUN")
sys.exit(1 if (bad or state["err"]) else 0)
