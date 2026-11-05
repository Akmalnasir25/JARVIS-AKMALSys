"""Bukti bahawa suis "baca jawapan" benar-benar menutup suara.

Dua gejala yang dilaporkan:
  1. "aku dah off baca jawapan tapi masih ada"  — laluan lain terus bersuara
  2. "kadang2 tu dah lama jawapan dah papar baru baca" — baris lama memainkan
     giliran kemudian, sebab setiap baris disintesis dahulu

Yang diuji di sini ialah backend: dengan speak_replies false, tts() mesti
menolak SEBELUM menyentuh rangkaian, jadi tiada audio yang boleh tiba lewat.
Font UI diuji berasingan oleh _speak_off_live.py, kerana ia perlu halaman hidup.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config.json"
ORIG = CONFIG.read_bytes()

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  — " + detail if detail else ""))
    if not cond:
        fails.append(name)


def setcfg(**kv):
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    cfg.update(kv)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


try:
    from main import Api
    api = Api()

    print("[1] speak_replies false — backend mesti menolak sebelum rangkaian")
    setcfg(speak_replies=False)
    t0 = time.time()
    r = api.tts("Ini satu ayat yang sepatutnya tidak dibaca langsung.")
    dt = time.time() - t0
    check("ia pulang ok=False", r.get("ok") is False, repr(r)[:110])
    check("ia ditanda muted, bukan gagal", r.get("muted") is True, repr(r.get("note")))
    check("tiada audio dikembalikan", not r.get("src"))
    check("ia serta-merta (<0.05 s, tiada panggilan rangkaian)", dt < 0.05, "%.4f s" % dt)

    print("[2] speak_replies true — laluan suara hidup semula")
    setcfg(speak_replies=True)
    t0 = time.time()
    r2 = api.tts("Ujian satu dua tiga.")
    dt2 = time.time() - t0
    check("ia tidak lagi ditanda muted", not r2.get("muted"))
    check("ia memulangkan audio atau sebab yang jelas",
          bool(r2.get("src")) or bool(r2.get("msg")), repr(r2)[:110])
    print("        %.2f s, via=%s" % (dt2, r2.get("via")))

    print("[3] force=True menembusi suis (untuk suara sistem yang memang diminta)")
    setcfg(speak_replies=False)
    t0 = time.time()
    r3 = api.tts("Paksa.", force=True)
    dt3 = time.time() - t0
    check("ia tidak ditanda muted", not r3.get("muted"))
    check("ia benar-benar mencuba sintesis", dt3 > 0.05, "%.2f s" % dt3)

    print("[4] tetapan dibaca setiap panggilan, bukan sekali semasa mula")
    setcfg(speak_replies=False)
    a = api.tts("satu").get("muted")
    setcfg(speak_replies=True)
    b = api.tts("dua").get("muted")
    check("off kemudian on berubah serta-merta", a is True and not b, "%r -> %r" % (a, b))

finally:
    CONFIG.write_bytes(ORIG)

print()
if fails:
    print("FAILED %d: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL GREEN")
