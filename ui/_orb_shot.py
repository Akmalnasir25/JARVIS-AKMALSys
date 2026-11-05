import sys, threading, time, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\akmal\jarvis-desktop")
os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                      "--autoplay-policy=no-user-gesture-required")
import main as M, media_server as MS, webview

ORIG = M.CONFIG.read_bytes()
OUT = pathlib_out = os.path.join(r"C:\Users\akmal\jarvis-desktop\ui", "_orb_voice.png")

api = M.Api()
api._media = MS.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui", entry="stage.html").start()
win = None


def go():
    time.sleep(3.0)
    q = win.evaluate_js
    api._window = win
    q("""window.__v=[];
         const _o=window.orbVoice;
         window.orbVoice=(b,w,r)=>{window.__v.push([Array.from(b),r]); if(_o)_o(b,w,r);}; true;""")
    q("window.stageSettings(window.pywebview.api.get_settings_core()); true")
    time.sleep(0.5)
    print("aria before:", q("document.getElementById('btnSpeak').getAttribute('aria-pressed')"), flush=True)
    print("cfg before:", json.loads(M.CONFIG.read_text(encoding="utf-8")).get("speak_replies"), flush=True)
    q("document.getElementById('btnSpeak').click(); true")
    time.sleep(1.2)
    q("document.getElementById('btnSpeak').click(); true")   # back to OFF (his setting)
    time.sleep(0.8)
    print("aria after:", q("document.getElementById('btnSpeak').getAttribute('aria-pressed')"), flush=True)
    print("cfg after:", json.loads(M.CONFIG.read_text(encoding="utf-8")).get("speak_replies"), flush=True)
    q("window.stageTtsProbe.set(true); true")   # force ON just for the picture
    q("window.stageTtsProbe.speak('Selamat pagi Akmal. Cuaca hari ini cerah, suhu tiga puluh dua darjah, dan trafik ke Ipoh lancar sepanjang jalan utama.').then(()=>0); true")
    for i in range(50):
        time.sleep(0.5)
        st = q("document.body.dataset.orb")
        if i % 4 == 0:
            print("  t=%4.1f orb=%r frames=%r" % (i * 0.5, st, q("window.__v.length")), flush=True)
        if st == "speaking":
            time.sleep(1.3)
            from PIL import ImageGrab
            ImageGrab.grab(all_screens=True).save(OUT)
            print("SHOT", OUT, flush=True)
            break
    print("frames total:", q("window.__v.length"), flush=True)
    M.CONFIG.write_bytes(ORIG)
    win.destroy()
    os._exit(0)


win = webview.create_window("shot", api._media.stage_url, js_api=api, width=1280, height=800)
threading.Thread(target=go, daemon=True).start()
webview.start()
