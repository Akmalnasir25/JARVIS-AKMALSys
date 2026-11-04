"""Ujian hidup Jarvis — boot WebView2 sebenar, pandu setiap panel, rakam skrin.

Bezanya dengan _sys_e2e.py: itu uji logik dengan _window=None. Fail ini
memulakan HUD sebenar. Driver dijalankan melalui webview.start(func), jadi ia
berada dalam thread yang sama dengan GUI dan boleh evaluate_js terus.

Jalankan:  python ui/_live.py
Hasil:     ui/_live/*.png  +  ui/_live/report.txt
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\Users\akmal\jarvis-desktop")
import main as M
import system as S
import webview

OUT = M.ROOT / "ui" / "_live"
OUT.mkdir(parents=True, exist_ok=True)

LOG = []


REPORT = OUT / "report.txt"


def note(ok, label, detail=""):
    """Tulis ke cakera serta-merta.

    Versi pertama kumpul dalam senarai dan tulis pada penghujung. Bila
    win.destroy() tergantung, proses tak pernah sampai ke baris itu dan
    seluruh hasil ujian hilang — cuma lapan PNG tanpa satu pun keputusan.
    Satu baris, satu flush.
    """
    LOG.append((bool(ok), label, str(detail)))
    line = ("ok   " if ok else "FAIL ") + label + ("  · " + str(detail) if detail else "")
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    # Konsol Windows cp1252: satu ✔ dalam label membunuh seluruh ujian.
    sys.stdout.write(line.encode("ascii", "replace").decode("ascii") + "\n")
    sys.stdout.flush()


# ── tangkap tetingkap melalui PrintWindow ────────────────────────────────────
_u32 = ctypes.windll.user32
_gdi = ctypes.windll.gdi32


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def grab(hwnd, path, max_w=1600):
    """PrintWindow dengan PW_RENDERFULLCONTENT (2) — ImageGrab memberi hitam untuk WebView2."""
    from PIL import Image
    rect = wt.RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w < 40 or h < 40:
        return False
    hdc = _u32.GetWindowDC(hwnd)
    mdc = _gdi.CreateCompatibleDC(hdc)
    bmp = _gdi.CreateCompatibleBitmap(hdc, w, h)
    old = _gdi.SelectObject(mdc, bmp)
    try:
        _u32.PrintWindow(hwnd, mdc, 2)
        bi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        _gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)))
        img.save(str(path))
        return True
    finally:
        _gdi.SelectObject(mdc, old)
        _gdi.DeleteObject(bmp)
        _gdi.DeleteDC(mdc)
        _u32.ReleaseDC(hwnd, hdc)


# ── Api sebenar ─────────────────────────────────────────────────────────────
api = M.Api()
api._media = M.MediaServer(M.MEDIA).start()
win = webview.create_window("Jarvis", str(M.ROOT / "ui" / "stage.html"),
                            js_api=api, fullscreen=True, background_color="#05030f")
api._window = win


def js(code):
    try:
        return win.evaluate_js(code)
    except Exception as e:
        return "ERR " + str(e)


def wait_ready(timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if js("typeof window.onClaude") == "function":
            return True
        time.sleep(0.4)
    return False


def pane(name, settle=0.9):
    """Tukar panel dan pastikan ia benar-benar bertukar.

    `show()` pulang senyap kalau nama panel tiada dalam peta — jadi menulis
    "web" bukan "browse" menghasilkan ujian yang lulus tanpa menguji apa-apa.
    """
    got = js("(()=>{window.stageShow(%s);return document.body.dataset.pane})()" % json.dumps(name))
    if got != name:
        note(False, "panel %s tak wujud" % name, got)
    time.sleep(settle)
    return got


def hud():
    """HWND HUD sebenar. FindWindowW boleh memilih salah satu daripada puluhan
    HWND bertajuk sama yang dihasilkan satu tetingkap pywebview, jadi pemegang
    Python adalah satu-satunya sumber yang tepat."""
    h = api.hud_hwnd()
    return h or S.hud_hwnd("Jarvis")


def shot(tag, title=None):
    hwnd = hud()
    if not hwnd and title:
        hwnd = S.hud_hwnd(title)
    if not hwnd:
        note(False, "shot " + tag, "hwnd tak dijumpai")
        return
    p = OUT / (tag + ".png")
    note(grab(hwnd, p), "shot " + tag, p.name)


def vis(hwnd):
    """IsWindowVisible — FindWindowW menjumpai tetingkap tersembunyi juga."""
    if not hwnd:
        return False
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def driver():
    time.sleep(2.0)
    try:
        _run()
    except Exception:
        note(False, "driver crash", traceback.format_exc()[-600:])
        (OUT / "report.txt").write_text(
            "\n".join(("ok  " if o else "FAIL") + " | " + l + (" | " + d if d else "")
                      for o, l, d in LOG), encoding="utf-8")
    finally:
        time.sleep(0.5)
        try:
            api.app_detach()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass


def _run():
    note(wait_ready(), "HUD boot, bridge hidup")
    time.sleep(1.5)
    shot("01-boot")

    # ── statistik hidup ──
    st = api.get_stats()
    note(st.get("cpu") is not None, "get_stats hidup",
         "cpu %s%% ram %s%% bat %s" % (st.get("cpu"), st.get("ram"), st.get("battery")))

    # ── MEDIA: main video sebenar, uji seek ──
    pane("media")
    items = api.media_list()["items"]
    vid = next((i for i in items if i["kind"] == "video"), None)
    note(bool(vid), "media_index jumpa video", vid["name"] if vid else "tiada .mp4")
    if vid:
        i = js("window.stageMedia && window.stageMedia.open(%s)" % json.dumps(vid["name"]))
        note(i not in (None, -1) and not str(i).startswith("ERR"), "stageMedia.open", i)
        time.sleep(1.8)
        js("(()=>{const v=document.querySelector('#mediaScreen video');if(v){v.currentTime=4.2;v.play();}})()")
        time.sleep(1.8)
        t = js("(()=>{const v=document.querySelector('#mediaScreen video');return v?[v.currentTime,v.duration,v.readyState,v.paused]:null})()")
        note(isinstance(t, list) and t and float(t[0] or 0) > 1.0, "video seek + main", t)
        shot("02-media")
        # tukar panel mesti pause
        pane("comms")
        time.sleep(0.8)
        p = js("(()=>{const v=document.querySelector('#mediaScreen video');return v?v.paused:null})()")
        note(p in (True, "true", None), "tukar panel pause audio", p)

    # ── DOK: pdf sebenar ──
    pdf = next(iter(sorted((M.HOME / "Documents").glob("*.pdf"))), None)
    if pdf:
        r = api._open_doc_in_stage(str(pdf))
        note(r.get("handled"), "buka pdf melalui suara-path", r.get("label"))
        time.sleep(1.6)
        n = js("(()=>{const i=document.querySelector('#docBody img');return i?[i.naturalWidth,i.naturalHeight]:null})()")
        note(isinstance(n, list) and n and (n[0] or 0) > 100, "imej pdf render", n)
        shot("03-docs")

    # ── EDITOR: tulis fail sebenar ──
    pane("editor")
    probe = M.ROOT / "_live_edit_probe.py"
    probe.write_text("# ujian hidup\nprint('hello')\n", encoding="utf-8")
    try:
        js("window.stageEditor && window.stageEditor.open(%s)" % json.dumps(str(probe)))
        time.sleep(2.2)
        r = js("(()=>{const e=document.getElementById('edMeta');return e?e.textContent:null})()")
        note(isinstance(r, str) and "probe" in r, "editor buka fail", r)
        shot("04-editor")
    finally:
        probe.unlink(missing_ok=True)

    # ── APP: embed notepad sebenar, melalui JS seperti pengguna ──
    ok, info = S.launch_app("notepad")
    note(ok, "lancar notepad", info)
    time.sleep(2.2)
    pane("native", settle=1.6)
    js("window.stageApp && window.stageApp.scan()")
    time.sleep(1.0)
    got = js("window.stageApp ? window.stageApp.attach(%s) : 'no stageApp'" % json.dumps("notepad"))
    time.sleep(2.4)
    got = js("window.stageApp ? window.stageApp.title : 'no stageApp'")
    note(isinstance(got, str) and "otepad" in got, "stageApp.attach melalui JS", got)
    rect = js("(()=>{const h=document.getElementById('appHost');if(!h)return null;const b=h.getBoundingClientRect();return[b.x,b.y,b.width,b.height]})()")
    note(isinstance(rect, list) and (rect[2] or 0) > 200, "rect host diukur", rect)
    emb = js("(()=>{const h=document.getElementById('appHost');return h?h.hidden:null})()")
    note(emb is False, "host stage kelihatan", emb)
    shot("05-app")
    js("window.stageApp && window.stageApp.detach()")
    time.sleep(1.0)
    note(js("window.stageApp ? window.stageApp.title : null") in ("", None),
         "stageApp.detach melalui JS")

    # ── WEB: create_window sebenar ──
    # Identiti HWND tidak berguna di sini: satu tetingkap pywebview meninggalkan
    # puluhan HWND bertajuk sama, dan show() mencipta semula handle asli kerana
    # pywebview menulis Text pada Form. Jadi ujian memeriksa pemegang Python
    # (api.web_hwnd()) dan keadaan _web_open, bukan gelintar tajuk.
    pane("browse")
    time.sleep(0.6)
    js("window.stageWeb && window.stageWeb.open('example.com')")
    time.sleep(5.0)
    wh = api.web_hwnd()
    note(bool(wh), "stageWeb.open -> create_window hidup", wh)
    if not wh:
        r = api.web_open("example.com")
        note(r.get("ok"), "web_open langsung", r.get("msg") or r.get("url"))
        time.sleep(4.0)
        wh = api.web_hwnd()
        note(bool(wh), "tetingkap web hidup (laluan langsung)", wh)
    if wh:
        note(grab(wh, OUT / "06-web.png"), "shot 06-web")
        h1 = api.web_hide()
        time.sleep(0.8)
        note(not vis(api.web_hwnd()), "web_hide -> tetingkap tak kelihatan",
             (h1, api.web_hwnd(), vis(api.web_hwnd())))
        h2 = api.web_show()
        time.sleep(1.5)
        w2 = api.web_hwnd()
        note(bool(h2.get("ok")) and vis(w2), "web_show -> tetingkap kembali",
             (h2, w2, vis(w2)))
        # Tukar panel: stage.html memanggil web_hide(), bukan web_close().
        pane("comms", settle=1.6)
        note(not vis(api.web_hwnd()), "tukar panel -> tetingkap web diparkir",
             (api.web_hwnd(), vis(api.web_hwnd())))
        pane("browse", settle=1.8)
        w3 = api.web_hwnd()
        note(vis(w3), "balik ke WEB -> tetingkap kembali", (w3, vis(w3)))
        r = api.web_close()
        time.sleep(1.0)
        note(api.web_hwnd() == 0 and not api._web_open,
             "web_close musnahkan tetingkap", (r, api.web_hwnd(), api._web_open))

    # ── prompt pengesahan: mint token, jangan laksana ──
    pane("comms", settle=0.6)
    r = api._sys.do("shutdown")
    note(r.get("need_confirm"), "shutdown gated", r.get("ask"))
    api._pending_token = r.get("token")
    js("window.jarvisConfirm(%s)" % json.dumps(r))
    time.sleep(1.2)
    btn = js("(()=>{const r=[...document.querySelectorAll('#talk button')];return r.filter(b=>/Ya, buat|Tak/.test(b.textContent)).length})()")
    note(isinstance(btn, int) and btn >= 2, "butang prompt muncul", btn)
    shot("07-confirm")
    # tekan "Tak" supaya jalan UI betul-betul diuji, bukan cuma cancel_system()
    js("(()=>{const b=[...document.querySelectorAll('#talk button')].find(x=>x.textContent==='Tak');if(b)b.click();})()")
    time.sleep(0.8)
    note(api._pending_token is None, "butang Tak batalkan token", api._pending_token)
    api.cancel_system(r.get("token"))
    time.sleep(0.6)

    # ── kawalan hidup: volume, kecerahan, tetingkap ──
    before = S.volume_get()
    res = api.resolve_system("volume 33")
    note(res.get("handled") and S.volume_get() == 33, "volume 33 melalui resolver", S.volume_get())
    S.volume_set(before)
    res = api.resolve_system("status laptop")
    note(res.get("handled"), "status laptop", (res.get("label") or "")[:100])
    wins = api.app_windows(8)["windows"]
    note(len(wins) > 0, "senarai tetingkap", "%d tetingkap" % len(wins))

    # ── TTS hidup ──
    t = api.tts("Ujian suara Jarvis.")
    note(t.get("ok"), "TTS", t.get("via"))

    # ── CHAT model hidup: tool round-trip ──
    s = M.load_json(M.SECRETS, {})
    t0 = time.time()
    try:
        rep = api._chat_call(s, [{"role": "user", "content": "Balas satu perkataan sahaja: siap"}])
        txtx = (rep.get("content") or "").strip().replace("\n", " ")
        note(bool(txtx), "chat model hidup", "%s | %.1fs" % (txtx[:40], time.time() - t0))
    except Exception as e:
        note(False, "chat model hidup", "%s %s" % (type(e).__name__, str(e)[:80]))

    # ── fail + editor melalui laluan model ──
    lst = api.fs_list("")
    note(lst.get("ok"), "fs_list workdir", "%d entri" % len(lst.get("entries", [])))

    shot("08-akhir")


webview.start(driver)

total = len(LOG)
passed = sum(1 for o, _, _ in LOG if o)
with REPORT.open("a", encoding="utf-8") as f:
    f.write("\n%d ok, %d gagal daripada %d\n" % (passed, total - passed, total))
print("\n%d ok, %d gagal daripada %d" % (passed, total - passed, total))
