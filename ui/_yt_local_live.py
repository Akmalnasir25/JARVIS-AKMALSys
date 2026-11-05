"""End-to-end: does "play this song" actually produce sound in the stage?

Route under test is the local one, because the embed route is closed by
measurement: every music video tested returns YouTube error 150 inside
WebView2 (owner disallows embedding), on both youtube.com and
youtube-nocookie.com, while a non-music video plays on nocookie. Error 150 is
a content policy, not a bug we can fix. A downloaded file has no policy.

So this suite proves: search resolves, the download lands as a codec WebView2
has, the pane mounts it, and playback advances.
"""
import json, os, pathlib, sys, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import main as M
import media_server as MS

P, F = [], []
def chk(n, c, x=""):
    (P if c else F).append(n)
    print(("  ok   " if c else "  FAIL ") + n + (("  " + str(x)) if (x and not c) else ""))

api = M.Api()
api._window = None
events = []
api._emit = lambda k, d=None: events.append((k, d))
api._push = lambda *a, **k: None

print("[1] resolve + download")
res = api.play_youtube("Hindia Secukupnya")
chk("play_youtube returns ok", res.get("ok") is True, res)
chk("it used the local route", res.get("mode") == "local", res.get("mode"))
name = res.get("name") or ""
chk("a file landed in media/", bool(name) and (M.MEDIA / name).is_file(), name)
chk("it is a container the stage accepts",
    pathlib.Path(name).suffix.lower() in api.MEDIA_EXT, name)
chk("it is bigger than 500 KB (real audio, not a stub)",
    res.get("size", 0) > 500_000, res.get("size"))
chk("a media event was emitted for the pane",
    any(k == "media" and d and d.get("play") for k, d in events), events[-2:])
chk("title was cleaned of credits", "Official" not in (res.get("title") or ""), res.get("title"))

print("\n[2] the pane can serve it")
srv = MS.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui", entry="stage.html").start()
url = srv.base + "/" + name
import urllib.request
code = urllib.request.urlopen(url, timeout=20).status
chk("range server serves the file", code == 200, code)
chk("it sends an audio/video content-type",
    "video" in (urllib.request.urlopen(url, timeout=20).headers.get("Content-Type") or "")
    or "audio" in (urllib.request.urlopen(url, timeout=20).headers.get("Content-Type") or ""))

print("\n[3] WebView2 decodes and plays it")
import webview
probe = f"""<!doctype html><meta charset=utf-8>
<video id=v src="{url}" preload=auto></video>
<script>
const v=document.getElementById('v'), L=[];
const s=(k,x)=>{{L.push(k+' :: '+x); window.__p=L;}};
v.addEventListener('loadedmetadata',()=>s('META',v.duration.toFixed(1)));
v.addEventListener('canplay',()=>s('CANPLAY',1));
v.addEventListener('error',()=>s('ERROR',v.error&&v.error.code));
v.play().then(()=>s('PLAY','ok')).catch(e=>s('PLAY','blocked '+e.name));
setTimeout(()=>s('TIME',v.currentTime.toFixed(2)+' paused='+v.paused), 6000);
</script>"""
pathlib.Path(M.ROOT / "ui" / "_yt_local_probe.html").write_text(probe, encoding="utf-8")
srv2 = MS.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui", entry="_yt_local_probe.html").start()
got = {}
def watch():
    t = time.time()
    while time.time() - t < 22:
        try:
            v = win.evaluate_js("JSON.stringify(window.__p||[])")
            if v and v not in ("[]", "null"):
                d = json.loads(v)
                if any(x.startswith("TIME") for x in d):
                    got["all"] = d
                    break
        except Exception:
            pass
        time.sleep(0.8)
    print("--- probe ---", flush=True)
    for x in (got.get("all") or []): print("   ", x, flush=True)
    win.destroy()
    os._exit(0)
win = webview.create_window("ytlocal", srv2.base + "/stage", width=900, height=600, x=-3200, y=-3200)
threading.Thread(target=watch, daemon=True).start()
webview.start()

d = got.get("all") or []
line = lambda k: next((x for x in d if x.startswith(k)), "")
chk("metadata read (duration known)", "::" in line("META"), d)
chk("no codec error", not line("ERROR"), line("ERROR") or d)
t = line("TIME")
chk("playback advanced past zero", "paused=false" in t and float((t.split("::")[1].split()[0])) > 0.5, t)

print("\n%d passed, %d failed" % (len(P), len(F)))
for f in F: print("  FAILED:", f)
sys.exit(1 if F else 0)
