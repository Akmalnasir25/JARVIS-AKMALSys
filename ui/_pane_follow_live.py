"""Bukti peraturan tab: soalan baru -> COMMS, hasil -> ANA, tanya lagi -> COMMS.

Gejala: "aku dah suruh buat analisis, dia buka tab analisis... tapi bila aku
taip soalan tambahan, dia masih stay di tab analyse".

Peraturan yang diuji, dan ia satu-satunya peraturan:
  - satu pusingan bermula ('start')  -> stage ke COMMS, tempat jawapan muncul
  - dashboard tiba ('analysis')      -> stage ke ANA, dan kekal di situ
  - pusingan tamat tanpa dashboard   -> COMMS, kerana jawapan itu teks
  - pusingan tamat DENGAN dashboard  -> kekal ANA, kerana dashboard itu jawapannya
"""
import os
import pathlib
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import main as M
import media_server as MS
import webview

P, F = [], []
def chk(n, c, x=""):
    (P if c else F).append(n)
    print(("  ok   " if c else "  FAIL ") + n + (("  " + str(x)[:140]) if (x and not c) else ""), flush=True)

api = M.Api()
api._media = MS.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui", entry="stage.html").start()
win = None

DASH = {
    "title": "Analisis ujian", "summary": "ringkasan",
    "cards": [{"label": "Satu", "value": "1", "note": "nota"}],
    "charts": [], "points": [], "followups": [],
}


def go():
    time.sleep(2.5)
    q = win.evaluate_js
    api._window = win

    def pane():
        return q("document.body.dataset.pane")

    print("\n[1] dashboard sampai semasa jawapan -> ANALYSE, dan kekal", flush=True)
    q("window.stageShow('comms'); window.onClaude('start', {}); true")
    time.sleep(0.3)
    q("window.onClaude('analysis', %s); true" % __import__("json").dumps(DASH))
    time.sleep(0.5)
    chk("tab bertukar ke ana", pane() == "ana", pane())
    q("window.onClaude('done', {ok:true, secs:1}); true")
    time.sleep(0.5)
    chk("kekal di ana kerana dashboard itu jawapannya", pane() == "ana", pane())

    print("\n[2] soalan tambahan -> balik ke COMMS", flush=True)
    q("window.onClaude('start', {}); true")
    time.sleep(0.4)
    chk("stage pulang ke comms", pane() == "comms", pane())

    print("\n[3] jawapan teks biasa tamat -> kekal di COMMS", flush=True)
    q("window.onClaude('stream', {text:'ini jawapan'}); true")
    time.sleep(0.2)
    q("window.onClaude('done', {ok:true, secs:1}); true")
    time.sleep(0.5)
    chk("masih di comms", pane() == "comms", pane())

    print("\n[4] dari pane lain, jawapan baru tetap membawa ke COMMS", flush=True)
    q("window.stageShow('media'); true")
    time.sleep(0.3)
    chk("mula di media", pane() == "media", pane())
    q("window.onClaude('start', {}); true")
    time.sleep(0.4)
    chk("soalan baru menariknya ke comms", pane() == "comms", pane())

    print("\n[5] analisis kedua dalam pusingan yang sama -> ana semula", flush=True)
    q("window.onClaude('analysis', %s); true" % __import__("json").dumps(DASH))
    time.sleep(0.4)
    chk("ana sekali lagi", pane() == "ana", pane())
    q("window.onClaude('done', {ok:true, secs:1}); true")
    time.sleep(0.4)
    chk("kekal di ana", pane() == "ana", pane())

    print("\n%d lulus, %d gagal" % (len(P), len(F)), flush=True)
    for x in F:
        print("  GAGAL:", x, flush=True)
    win.destroy()
    time.sleep(0.3)
    os._exit(0 if not F else 1)


win = webview.create_window("paneprobe", api._media.stage_url, js_api=api, width=1100, height=740)
threading.Thread(target=go, daemon=True).start()
webview.start()
