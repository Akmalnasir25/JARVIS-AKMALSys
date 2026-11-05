"""Bukti hidup untuk dua suis di sebelah kotak taip, dan untuk orb yang mengikut suara.

Gejala:
  - "butang mic dan icon speaker sebelah chatbox tu macam tak berfungsi je"
  - "orb tu bila bercakap, mesti ada denyutan ikut gaya sebutan dan intonasi"

Puncanya: kedua-dua butang tiada id dan tiada listener; orb memakai sin(t*13)
sebagai degupan, satu metronom yang tidak tahu apa-apa tentang ayat yang dibaca.

Yang penting di sini: ujian ini TIDAK mempatch apa-apa dalam halaman kecuali
window.orbVoice (global biasa, selamat). Ia membaca kebenaran dari backend —
_listen_request, _listening, config.json — bukan dari rupa butang.
"""
import json
import os
import pathlib
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault(
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "--autoplay-policy=no-user-gesture-required")
import main as M
import media_server as MS
import webview

P, F = [], []
def chk(n, c, x=""):
    (P if c else F).append(n)
    print(("  ok   " if c else "  FAIL ") + n + (("  " + str(x)[:160]) if (x and not c) else ""), flush=True)

ORIG = M.CONFIG.read_bytes()   # his real settings, byte for byte
api = M.Api()
api._media = MS.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui", entry="stage.html").start()
url = api._media.stage_url
print("stage at", url, flush=True)
win = None


def go():
    time.sleep(2.5)
    js = win.evaluate_js
    def q(code):
        try:
            return js(code)
        except Exception as e:
            return "ERR " + str(e)

    def wait(expr, want=True, limit=10.0):
        end = time.time() + limit
        last = None
        while time.time() < end:
            last = q(expr)
            if bool(last) == bool(want):
                return last
            time.sleep(0.25)
        return last

    api._window = win

    print("\n[0] dua butang itu ada, dan bukan butang submit", flush=True)
    for bid in ("btnMic", "btnSpeak"):
        chk("butang %s ada" % bid, q("!!document.getElementById(%r)" % bid))
    chk("mic type=button", q("(document.getElementById('btnMic')||{}).type") == "button",
        q("(document.getElementById('btnMic')||{}).type"))

    print("\n[A] mic — satu tekan mesti sampai ke backend", flush=True)
    api._listen_request.clear()
    api._listening = False
    q("document.getElementById('btnMic').click(); true")
    time.sleep(1.2)
    chk("backend menerima permintaan mic (_listen_request)", api._listen_request.is_set(),
        "_listen_request=%r _listening=%r" % (api._listen_request.is_set(), api._listening))
    chk("UI menunjukkan ia sedang mendengar",
        q("(document.getElementById('act')||{}).textContent||''").find("Listening") >= 0,
        q("(document.getElementById('act')||{}).textContent||''"))
    api._listen_request.clear()

    print("\n[B] speaker — satu klik menukar tetapan sebenar", flush=True)
    q("window.stageSettings(api.get_settings_core()); true")
    time.sleep(0.5)
    was = q("document.getElementById('btnSpeak').getAttribute('aria-pressed')") == "true"
    cfg = json.loads(M.CONFIG.read_text(encoding="utf-8")).get("speak_replies", True)
    chk("keadaan butang ikut config semasa mula", was == bool(cfg), "btn=%r cfg=%r" % (was, cfg))

    q("document.getElementById('btnSpeak').click(); true")
    time.sleep(1.0)
    now = q("document.getElementById('btnSpeak').getAttribute('aria-pressed')") == "true"
    chk("klik menukar butang", now != was, "before=%r after=%r" % (was, now))
    cfg2 = json.loads(M.CONFIG.read_text(encoding="utf-8")).get("speak_replies")
    chk("config ditulis, bukan sekadar UI", bool(cfg2) == now, cfg2)
    chk("checkbox dalam sheet tidak bercanggah",
        bool(q("!!document.getElementById('setSpeak') && document.getElementById('setSpeak').checked")) == now)

    if not now:
        print("\n[B2] dengan ia mati, tiada satu pun laluan bersuara", flush=True)
        r = q("window.stageTtsProbe.reply('baris jawapan ujian')")
        time.sleep(1.2)
        chk("jawapan selesai: tiada audio", not q("window.stageTtsProbe.hasAudio()"))
        q("window.stageTtsProbe.speak('baris terus'); true")
        time.sleep(0.8)
        chk("speak() sendiri tidak memulakan apa-apa",
            q("document.body.dataset.orb") != "speaking" and not q("window.stageTtsProbe.hasAudio()"),
            q("document.body.dataset.orb"))
        chk("masih tiada audio", not q("window.stageTtsProbe.hasAudio()"))
        rb = api.tts("ujian backend")
        chk("backend juga menolak (muted)", rb.get("muted") is True, rb)

    print("\n[C] orb mengikut suara, bukan metronom", flush=True)
    if not now:
        q("document.getElementById('btnSpeak').click(); true")   # hidupkan semula
        time.sleep(1.0)
    chk("butang hidup sebelum ujian orb",
        q("document.getElementById('btnSpeak').getAttribute('aria-pressed')") == "true")
    # warm the synth path first: Google (4.5 s) or edge fallback (9 s) — the orb
    # must not be judged on the frames before audio exists
    q("window.stageTtsProbe.set(true); true")
    print("      (menyediakan laluan suara — sintesis mengambil beberapa saat)", flush=True)

    # rekod apa yang orb terima — global biasa, bukan monkeypatch objek bridge
    q("""window.__v = [];
         const _o = window.orbVoice;
         window.orbVoice = (b, w, r) => { window.__v.push([Array.from(b), r]); if (_o) _o(b, w, r); };
         true;""")
    q("window.stageTtsProbe.speak('Kamu sedang mendengar suara Jarvis yang bercakap perlahan dan jelas.'); true")
    wait("document.body.dataset.orb === 'speaking'", True, 20.0)
    time.sleep(2.5)
    n = q("window.__v.length") or 0
    chk("orb menerima bingkai spektrum", n > 20, "%r bingkai" % n)
    chk("orb dalam keadaan 'speaking'", q("document.body.dataset.orb") == "speaking",
        q("document.body.dataset.orb"))
    if n:
        rng = q("""(()=>{const v=window.__v; let mn=9,mx=-9;
                        for(const f of v) for(const b of f[0]) { if(b<mn)mn=b; if(b>mx)mx=b; }
                        return [mn,mx];})()""")
        try:
            mn, mx = rng
        except Exception:
            mn, mx = 0, 0
        chk("bar spektrum bergerak, bukan beku", (mx - mn) > 0.05, "min=%r max=%r" % (mn, mx))
        rm = q("""(()=>{const v=window.__v; let mx=0;
                       for(const f of v) if(f[1]>mx) mx=f[1]; return mx;})()""")
        chk("rms naik semasa bersuara", (rm or 0) > 0.02, rm)

    print("\n%d lulus, %d gagal" % (len(P), len(F)), flush=True)
    for x in F:
        print("  GAGAL:", x, flush=True)
    M.CONFIG.write_bytes(ORIG)     # never leave his config flipped
    win.destroy()
    time.sleep(0.4)
    os._exit(0 if not F else 1)


win = webview.create_window("speakprobe", url, js_api=api, width=1100, height=740)
threading.Thread(target=go, daemon=True).start()
webview.start()
