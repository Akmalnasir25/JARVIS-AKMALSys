"""Verify the two fixes the way Akmal uses them: a real click, and real pixels."""
import json, sys, threading, time
from pathlib import Path
ROOT = Path(r"C:\Users\akmal\jarvis-desktop")
sys.path.insert(0, str(ROOT))
import webview, main as J

CHECKS = []
def ok(c, n, e=""):
    CHECKS.append((bool(c), n, e))
    print(("PASS  " if c else "FAIL  ") + n + (("  -> " + str(e)) if e and not c else ""))

api = J.Api()
api._media = J.MediaServer(J.MEDIA).serve_ui(ROOT / "ui").start()
win = webview.create_window("Jarvis", api._media.stage_url, js_api=api,
                            fullscreen=False, width=1500, height=950, background_color="#140d26")
api._window = win


def grab(hwnd, path):
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    u, gi = ctypes.windll.user32, ctypes.windll.gdi32
    r = wintypes.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0 or r.left < -10000:
        return False
    hdc = u.GetWindowDC(hwnd); mdc = gi.CreateCompatibleDC(hdc)
    bmp = gi.CreateCompatibleBitmap(hdc, w, h); gi.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, 2)
    class B(ctypes.Structure):
        _fields_ = [("s", wintypes.DWORD), ("w", wintypes.LONG), ("h", wintypes.LONG),
                    ("p", wintypes.WORD), ("b", wintypes.WORD), ("c", wintypes.DWORD),
                    ("si", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("u", wintypes.DWORD), ("i", wintypes.DWORD)]
    bi = B(ctypes.sizeof(B), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)
    gi.DeleteObject(bmp); gi.DeleteDC(mdc); u.ReleaseDC(hwnd, hdc)
    return True


def lum(path):
    from PIL import Image
    im = Image.open(path).convert("L")
    px = sorted(im.get_data() if hasattr(im, "get_data") else list(im.getdata()))
    return round(sum(px) / len(px), 1), px[len(px) // 2]


def run():
    try:
        time.sleep(6.0)
        win.evaluate_js("window.stageShow('comms')")
        time.sleep(2.0)
        hwnd = int(win.native.Handle.ToInt64())
        out = ROOT / "ui" / "_live"

        # ── brightness, measured on real pixels ──
        grab(hwnd, out / "13-bright-comms.png")
        mean, med = lum(out / "13-bright-comms.png")
        ok(mean > 38, f"screen mean luminance {mean}/255 (was 24.5)", mean)
        ok(med > 26, f"screen median luminance {med}/255 (was 16)", med)

        # panel fill must be a lifted colour, not near-black
        p = json.loads(win.evaluate_js("""(()=>{try{
          const el=document.querySelector('.glass');
          const cs=getComputedStyle(el);
          const m=cs.backgroundImage.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
          return JSON.stringify({rgb:m?[+m[1],+m[2],+m[3]]:null,
                                 panel:getComputedStyle(document.documentElement)
                                        .getPropertyValue('--panel').trim()});
        }catch(e){return JSON.stringify({err:e.message})}})()"""))
        rgb = p.get("rgb") or [0, 0, 0]
        ok(sum(rgb) / 3 > 22, f"panel fill is lifted, not black — {rgb}", rgb)

        # text must be legible against the panel: WCAG-style contrast on the dim token
        c = json.loads(win.evaluate_js("""(()=>{try{
          const L=h=>{const v=h.replace('#','').match(/../g).map(x=>{
            let c=parseInt(x,16)/255; return c<=.03928?c/12.92:Math.pow((c+.055)/1.055,2.4)});
            return .2126*v[0]+.7152*v[1]+.0722*v[2]};
          const cs=getComputedStyle(document.documentElement);
          const ink=L(cs.getPropertyValue('--ink').trim());
          const dim=L(cs.getPropertyValue('--ink-dim').trim());
          const faint=L(cs.getPropertyValue('--ink-faint').trim());
          const bg=0.045;   // panel luminance, measured
          const cr=(a,b)=>(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
          return JSON.stringify({ink:+cr(ink,bg).toFixed(1),
                                 dim:+cr(dim,bg).toFixed(1),
                                 faint:+cr(faint,bg).toFixed(1)});
        }catch(e){return JSON.stringify({err:e.message})}})()"""))
        ok(c.get("ink", 0) > 9, f"body text contrast {c.get('ink')}:1", c)
        ok(c.get("dim", 0) > 6, f"secondary text contrast {c.get('dim')}:1", c)
        ok(c.get("faint", 0) > 3, f"faint text contrast {c.get('faint')}:1", c)

        # ── minimize, through the button, not the API ──
        found = win.evaluate_js("""(()=>{try{
          const b=document.querySelector('.iconbar button.min');
          return !!b;
        }catch(e){return false}})()""")
        ok(found is True, "minimize button carries the .min class the binding looks for")

        win.evaluate_js("document.querySelector('.iconbar button.min').click()")
        time.sleep(1.2)
        v = win.evaluate_js("(()=>{try{return document.visibilityState}catch(e){return 'err'}})()")
        ok(v == "hidden", f"clicking the button actually minimizes — visibilityState {v}", v)

        win.restore()
        time.sleep(1.2)
        ok(win.evaluate_js("document.visibilityState") == "visible", "restore brings the HUD back")
        grab(hwnd, out / "14-restored.png")

        # ── other panels still paint (colour must combine, not go flat) ──
        for pane, shot in [("ana", "15-bright-ana.png"), ("docs", "16-bright-docs.png")]:
            win.evaluate_js("window.stageShow(%s)" % json.dumps(pane))
            time.sleep(1.0)
            grab(hwnd, out / shot)
            m, _ = lum(out / shot)
            ok(m > 30, f"{pane} pane still renders lit ({m}/255)", m)

    except Exception:
        import traceback
        print(traceback.format_exc())
        CHECKS.append((False, "no exception", ""))
    finally:
        try:
            win.destroy()
        except Exception:
            pass


threading.Thread(target=run, daemon=True).start()
webview.start(api._wire_drop, win)

bad = [c for c in CHECKS if not c[0]]
print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} passed")
sys.exit(1 if bad else 0)
