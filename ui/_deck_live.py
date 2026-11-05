"""Deck follow test — does "next slide" move the doc pane with the projector?

Uses the real PowerPoint path but with a deck we build here, so the result does
not depend on anything Akmal happens to have open. Checks the state machine and
the DOM, not whether PowerPoint itself is running.
"""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\Users\akmal\jarvis-desktop")
import main as M
import webview

OUT = M.ROOT / "ui" / "_live"
OUT.mkdir(parents=True, exist_ok=True)
LOG = []


def note(ok, label, detail=""):
    LOG.append(ok)
    print(("ok   " if ok else "FAIL ") + label + ("  ? " + str(detail) if detail else ""), flush=True)


def make_deck(path):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    pr = Presentation()
    for i in range(8):
        s = pr.slides.add_slide(pr.slide_layouts[5])
        s.shapes.title.text = f"Slide {i + 1} heading"
        tb = s.shapes.add_textbox(Inches(1), Inches(2.4), Inches(6), Inches(2))
        tb.text_frame.text = f"Body line for slide {i + 1}"
    pr.save(str(path))


def run(win):
    api = _API
    api._window = win
    js = lambda c: win.evaluate_js(c)
    try:
        time.sleep(1.6)
        deck = OUT / "_probe_deck.pptx"
        make_deck(deck)

        r = api.docs_open(str(deck))
        note(r.get("ok") and r.get("kind") == "pptx", "deck opens", f'{r.get("total")} slides')
        note(api._deck.get("total") == 8, "deck state knows the total", api._deck)
        note(r.get("page") == 1, "opens on slide 1", r.get("page"))

        js("window.stageShow('docs')")
        time.sleep(0.7)
        js("window.stageDocs && window.stageDocs.open(%s, 1)" % json.dumps(str(deck)))
        time.sleep(0.9)
        note(js("document.querySelectorAll('#docBody .doc-slide').length") == 8, "8 slides painted",
             js("document.querySelectorAll('#docBody .doc-slide').length"))
        note(js("!!document.querySelector('#docBody .doc-slide.on')"), "slide 1 marked as current")
        note(js("!!document.querySelector('#docBody .doc-follow.on')"), "follow banner is visible")
        note(js("document.getElementById('docPage').textContent") == "1 / 8", "page tag reads 1 / 8",
             js("document.getElementById('docPage').textContent"))

        # "next slide" as the voice path reaches it
        out = api.quick_control("next slide")
        note(out.get("handled") and out.get("label") == "Next slide · slide 2/8", "next -> 2/8", out)
        time.sleep(0.5)
        note(js("document.querySelector('#docBody .doc-slide.on').dataset.n") == "2", "pane on slide 2",
             js("document.querySelector('#docBody .doc-slide.on').dataset.n"))
        js("window.stageAnalysis && null")
        # caption travels with the slide, that is the point of the feature
        cap = js("""(()=>{
          const n=document.querySelector('#docBody .doc-slide.on');
          return n ? n.querySelector('h4 span').textContent + ' | ' + (n.querySelector('li')||{}).textContent : '';
        })()""")
        note("Slide 2 heading" in str(cap) and "slide 2" in str(cap), "caption follows the slide", cap)

        out = api.quick_control("slide seterusnya")
        note("3/8" in str(out.get("label")), "malay phrasing also steps", out)
        out = api.quick_control("previous slide")
        note("2/8" in str(out.get("label")), "previous -> 2/8", out)

        # a spoken number is ground truth, not a step
        out = api.quick_control("pergi slide 7")
        note(out.get("handled") and "7/8" in str(out.get("label")), "jump to slide 7", out)
        time.sleep(0.5)
        note(js("document.querySelector('#docBody .doc-slide.on').dataset.n") == "7", "pane on slide 7",
             js("document.querySelector('#docBody .doc-slide.on').dataset.n"))

        out = api.quick_control("slide 2")
        note("2/8" in str(out.get("label")), "bare 'slide 2' jumps back", out)

        # end of deck must clamp, not run off
        api.quick_control("pergi slide 8")
        out = api.quick_control("next slide")
        note("8/8" in str(out.get("label")), "clamps at the last slide", out)
        api.quick_control("pergi slide 1")
        out = api.quick_control("previous slide")
        note("1/8" in str(out.get("label")), "clamps at the first slide", out)

        # invalid numbers are ignored rather than clamped silently
        before = dict(api._deck)
        out = api.quick_control("pergi slide 99")
        note(not out.get("handled"), "out-of-range number is not handled", out)
        note(api._deck["slide"] == before["slide"], "state untouched by a bad number", api._deck)

        # no deck open -> slide commands must still reach PowerPoint
        api._deck = {"path": None, "slide": 0, "total": 0}
        out = api.quick_control("next slide")
        note(out.get("handled") and out.get("label") == "Next slide", "no deck: label stays plain", out)

        win_shot(api, "10-deck.png")
        deck.unlink(missing_ok=True)
    except Exception:
        note(False, "crash", traceback.format_exc()[-500:])
    finally:
        print(f"\n{sum(LOG)} ok, {len(LOG) - sum(LOG)} gagal daripada {len(LOG)}")
        win.destroy()


def win_shot(api, name):
    try:
        import ctypes, ctypes.wintypes as wt
        from PIL import Image
        u32, gdi = ctypes.windll.user32, ctypes.windll.gdi32

        class BMIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        h = api.hud_hwnd()
        if not h:
            return
        rect = wt.RECT()
        u32.GetWindowRect(h, ctypes.byref(rect))
        w, hh = rect.right - rect.left, rect.bottom - rect.top
        if w < 40:
            return
        hdc = u32.GetWindowDC(h); mdc = gdi.CreateCompatibleDC(hdc)
        bmp = gdi.CreateCompatibleBitmap(hdc, w, hh); old = gdi.SelectObject(mdc, bmp)
        u32.PrintWindow(h, mdc, 2)
        bi = BMIH(ctypes.sizeof(BMIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * hh * 4)
        gdi.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
        img = Image.frombuffer("RGB", (w, hh), buf, "raw", "BGRX", 0, 1)
        if img.width > 1400:
            img = img.resize((1400, int(img.height * 1400 / img.width)))
        img.save(str(OUT / name))
        gdi.SelectObject(mdc, old); gdi.DeleteObject(bmp); gdi.DeleteDC(mdc); u32.ReleaseDC(h, hdc)
    except Exception:
        pass


if __name__ == "__main__":
    _API = M.Api()
    srv = M.MediaServer(M.MEDIA).serve_ui(M.ROOT / "ui").start()
    w = webview.create_window("deck-probe", srv.stage_url, js_api=_API, width=1400, height=900)
    webview.start(run, w, gui="edgechromium", debug=False)
