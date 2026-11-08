"""App fon (PWA) untuk Jarvis, melalui domain (Cloudflare Tunnel) atau Tailscale.

DOMAIN (utama): https://jarvis.akmalsys.com -> Cloudflare Tunnel `jarvis` ->
127.0.0.1:8765. HTTPS membolehkan mic di fon. Dua kunci, kedua-duanya wajib:
  1. Cloudflare Access di hadapan: hanya e-mel Tuan boleh log masuk, dan
     Cloudflare menghantar Cf-Access-Authenticated-User-Email ke pelayan ini.
     Tanpa pengepala itu (Access belum dipasang / tersalah konfigurasi), semua
     permintaan melalui tunnel ditolak 404 — gagal tertutup, bukan terbuka.
  2. Token rahsia (cookie) yang sama seperti laluan Tailscale.

Fon membuka http://<ip-tailscale-laptop>:8765 dari mana-mana — rumah, sekolah,
data mudah alih — kerana Tailscale ialah rangkaian peribadi yang disulitkan
antara peranti Tuan sahaja. Tiada port dibuka kepada internet.

Kunci:
  · pelayan hanya diikat pada alamat Tailscale (100.64.0.0/10), BUKAN 0.0.0.0:
    orang dalam WiFi yang sama atau internet tak boleh sampai langsung;
  · setiap permintaan perlu token rahsia (secrets.json `phone_web_token`).
    Lawatan pertama ?k=<token> menyimpannya sebagai cookie HttpOnly, dan
    pautan itu dipaparkan sebagai QR di HUD sahaja;
  · token salah = 404, supaya pelayan tak mengaku wujud.

Arahan dari fon ikut jalan yang sama dengan bot Telegram: kawalan pantas
(quick_control) dahulu, kemudian `onVoice('text')` — HUD laptop melaksanakan,
dan fon membaca suapan jawapan (/api/state) setiap saat.
"""
from __future__ import annotations

import collections
import hmac
import ipaddress
import json
import secrets as _rand
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TS_NET = ipaddress.ip_network("100.64.0.0/10")
_CERTS = {"at": 0.0, "keys": {}}


def _b64u(x: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))


def access_claims(token: str, team: str):
    """Sahkan Cf-Access-Jwt-Assertion (RS256) dengan kunci awam pasukan Cloudflare Access.
    Pulangkan claims jika sah (tandatangan, penerbit, belum luput); None jika tidak.
    Pengguna ada 'email'; Service Token (Shortcuts iPhone) ada 'common_name'."""
    if not token or not team or token.count(".") != 2:
        return None
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        h64, p64, s64 = token.split(".")
        head, claims = json.loads(_b64u(h64)), json.loads(_b64u(p64))
        if head.get("alg") != "RS256":
            return None
        iss = f"https://{team}.cloudflareaccess.com"
        if claims.get("iss") != iss or float(claims.get("exp", 0)) < time.time():
            return None
        if head.get("kid") not in _CERTS["keys"] and time.time() - _CERTS["at"] > 60:
            import urllib.request
            with urllib.request.urlopen(iss + "/cdn-cgi/access/certs", timeout=10) as r:
                ks = json.load(r).get("keys", [])
            _CERTS.update(at=time.time(), keys={
                k["kid"]: rsa.RSAPublicNumbers(int.from_bytes(_b64u(k["e"]), "big"),
                                               int.from_bytes(_b64u(k["n"]), "big")).public_key()
                for k in ks if k.get("kty") == "RSA"})
        key = _CERTS["keys"].get(head.get("kid"))
        if not key:
            return None
        key.verify(_b64u(s64), f"{h64}.{p64}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return claims
    except Exception:
        return None


def tailscale_ip() -> str:
    try:
        import psutil
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == 2:
                    try:
                        if ipaddress.ip_address(a.address) in TS_NET:
                            return a.address
                    except ValueError:
                        pass
    except Exception:
        pass
    return ""


class PhoneWeb:
    def __init__(self, api, secrets_path: Path, ui_dir: Path, port=8765, log=print, domain="", email="", team=""):
        self.api = api
        self.team = (team or "").strip()
        self.domain = (domain or "").strip()
        self.email = (email or "").strip().lower()
        self.httpd_local = None
        self.secrets_path = secrets_path
        self.ui_dir = ui_dir
        self.port = int(port)
        self.log = log
        self.ip = ""
        self.httpd = None
        self.err = ""
        self.seq = 0
        self.feed = collections.deque(maxlen=200)
        self._lock = threading.Lock()

    # ── token ────────────────────────────────────────────────
    def token(self) -> str:
        try:
            s = json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:
            s = {}
        t = str(s.get("phone_web_token") or "")
        if len(t) < 24:
            t = _rand.token_urlsafe(24)
            s["phone_web_token"] = t
            self.secrets_path.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        return t

    def url(self) -> str:
        if self.domain:
            return f"https://{self.domain}/?k={self.token()}"
        return f"http://{self.ip}:{self.port}/?k={self.token()}" if self.ip else ""

    # ── kitaran hayat ────────────────────────────────────────
    def start(self):
        """Cuba setiap 30 s: Tailscale mungkin disambung selepas Jarvis bermula."""
        if self.domain:
            self.httpd_local = self._serve("127.0.0.1", local=True)   # asal tunnel Cloudflare

        def loop():
            while True:
                ip = tailscale_ip()
                if ip and (not self.httpd or ip != self.ip):
                    self._serve(ip)
                elif not ip and not self.httpd:
                    self.err = "Tailscale tiada / belum log masuk"
                time.sleep(30)
        threading.Thread(target=loop, daemon=True).start()

    def _serve(self, ip, local=False):
        if self.httpd and not local:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
        web = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _authed(self):
                if local:
                    # melalui tunnel: Cloudflare Access mesti sudah mengesahkan sama ada e-mel Tuan
                    # (pelayar) atau Service Token (Shortcuts iPhone). JWT disahkan dengan kunci awam
                    # pasukan; pengepala e-mel ialah sandaran untuk pelayar jika kunci tak dapat diambil.
                    c = access_claims(self.headers.get("Cf-Access-Jwt-Assertion") or "", web.team)
                    who = ((c or {}).get("email") or self.headers.get("Cf-Access-Authenticated-User-Email") or "").strip().lower()
                    ok_user = bool(web.email) and hmac.compare_digest(who, web.email)
                    ok_service = bool(c and c.get("common_name"))
                    if not (ok_user or ok_service):
                        return False, ""
                tok = web.token()
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                got = (q.get("k") or [""])[0] or self.headers.get("X-Jarvis-Key", "")
                for c in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = c.strip().partition("=")
                    if k == "jk" and not got:
                        got = v
                return bool(got) and hmac.compare_digest(got, tok), (q.get("k") or [""])[0]

            def _send(self, code, body: bytes, ctype="application/json", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def do_GET(self):
                ok, via_q = self._authed()
                if not ok:
                    return self._send(404, b"not found", "text/plain")
                path = urllib.parse.urlparse(self.path).path
                if via_q:   # simpan token sebagai cookie, buang dari URL (tak tinggal dalam sejarah)
                    return self._send(302, b"", "text/plain", {
                        "Location": "/",
                        "Set-Cookie": f"jk={web.token()}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict"})
                if path == "/":
                    import base64
                    ico = "data:image/png;base64," + base64.b64encode(icon_png(192, web.ui_dir)).decode()
                    page = PAGE.replace("__ICON__", ico).replace("/*__ORB__*/", orb_js(web.ui_dir))
                    return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                if path == "/manifest.json":
                    return self._send(200, json.dumps(manifest(web.ui_dir)).encode(), "application/manifest+json")
                if path == "/ui/logo.png":                    # logo di tengah orb
                    return self._send(200, (web.ui_dir / "logo.png").read_bytes(), "image/png")
                if path == "/icon.png":
                    return self._send(200, icon_png(192, web.ui_dir), "image/png")
                if path == "/api/state":
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    since = int((q.get("since") or ["0"])[0] or 0)
                    return self._json(web.state(since))
                return self._send(404, b"not found", "text/plain")

            def do_POST(self):
                ok, _ = self._authed()
                if not ok:
                    return self._send(404, b"not found", "text/plain")
                path = urllib.parse.urlparse(self.path).path
                if path == "/api/voice":                      # rakaman mic dari fon (webm/ogg)
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > 8_000_000:
                        return self._json({"ok": False, "msg": "Audio too large"}, 413)
                    return self._json(web.voice(self.rfile.read(n)))
                n = min(int(self.headers.get("Content-Length") or 0), 20000)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    body = {}
                if path == "/api/say":
                    return self._json(web.say(str(body.get("text") or "")[:2000]))
                if path == "/api/tts":
                    r = web.api.tts(str(body.get("text") or "")[:1500], force=True)
                    return self._json({"ok": bool(r.get("ok")), "src": r.get("src", "")})
                if path == "/api/ask":                       # Shortcuts: hantar & tunggu jawapan
                    return self._json(web.ask(str(body.get("text") or "")[:2000]))
                if path == "/api/project":
                    name = body.get("name")
                    if name is not None:
                        r = web.api.set_project(str(name))
                        return self._json({"ok": bool(r.get("ok")), **web.project_state(), "msg": r.get("msg", "")})
                    return self._json(web.project_state())
                if path == "/api/diff":
                    return self._json(web.api.project_diff())
                if path == "/api/commit":
                    return self._json(web.api.project_commit(str(body.get("msg") or "")[:300]))
                if path == "/api/sessions":
                    return self._json(web.api.list_sessions())
                if path == "/api/session/open":
                    return self._json({k: v for k, v in web.api.open_session(str(body.get("id") or "")).items()
                                       if k != "history"})
                if path == "/api/session/delete":
                    return self._json(web.api.delete_session(str(body.get("id") or "")))
                if path == "/api/new":
                    web.api.new_session()
                    return self._json({"ok": True})
                if path == "/api/stop":
                    web.api.stop()
                    return self._json({"ok": True})
                return self._send(404, b"not found", "text/plain")

        try:
            srv = ThreadingHTTPServer((ip, self.port), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.log(f"phone web on {ip}:{self.port}" + (" (tunnel)" if local else ""))
            if local:
                return srv
            self.httpd, self.ip, self.err = srv, ip, ""
        except Exception as e:
            self.err = f"{type(e).__name__}: {e}"
            self.log(f"phone web gagal ({ip}): {self.err}")
            if not local:
                self.httpd = None
        return None

    def status(self):
        return {"up": bool(self.httpd or self.httpd_local), "ip": self.ip, "domain": self.domain,
                "port": self.port, "err": self.err}

    def voice(self, data: bytes):
        """Audio dari mic fon -> teks (laluan transkripsi yang sama dengan voice note) -> arahan."""
        import tempfile
        import phone
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(data)
            p = Path(f.name)
        try:
            audio = phone.decode_16k(p)
            if len(audio) < 16000 * 0.4:
                return {"ok": False, "msg": "Too short"}
            self.api.warm_whisper()
            text = (self.api._transcribe(audio, source="phone") or "").strip()
        except Exception as e:
            return {"ok": False, "msg": f"Transcription failed: {e}"}
        finally:
            try:
                p.unlink()
            except Exception:
                pass
        if not text:
            return {"ok": False, "msg": "Nothing heard"}
        r = self.say(text)
        return {"ok": True, "text": text, **{k: v for k, v in r.items() if k != "ok"}}

    # ── suapan ───────────────────────────────────────────────
    def push(self, kind, data):
        with self._lock:
            self.seq += 1
            self.feed.append({"seq": self.seq, "kind": kind, "at": int(time.time()), **data})

    def load_history(self, hist):
        """Sesi lama dibuka: fon kosongkan skrin dan tunjuk perbualan itu."""
        with self._lock:
            self.feed.clear()
        self.push("reset", {"text": ""})
        for m in hist or []:
            t = str(m.get("content") or "")
            if t:
                self.push("me" if m.get("role") == "user" else "jarvis", {"text": t[:6000]})

    def project_state(self):
        a = self.api
        try:
            cur = a.get_project() or {}
        except Exception:
            cur = {}
        try:
            names = [p["name"] for p in a.list_projects()][:40]
        except Exception:
            names = []
        return {"ok": True, "name": cur.get("name"), "projects": names}

    def ask(self, text, wait=150):
        """Untuk Shortcuts iPhone: satu permintaan, satu jawapan teks untuk Siri baca."""
        text = text.strip()
        if not text:
            return {"ok": False, "reply": "Tiada arahan."}
        with self._lock:
            start = self.seq
        r = self.say(text)
        if r.get("handled"):
            with self._lock:
                notes = [e["text"] for e in self.feed if e["seq"] > start and e["kind"] == "note"]
            return {"ok": True, "reply": (notes[-1] if notes else "Done").lstrip("✓ ")}
        t0 = time.time()
        a = self.api
        time.sleep(1.0)
        while time.time() - t0 < wait:
            busy = bool(getattr(a, "_chat_busy", False) or getattr(a, "_proc", None))
            with self._lock:
                said = [e["text"] for e in self.feed if e["seq"] > start and e["kind"] in ("jarvis", "error")]
            if said and not busy:
                return {"ok": True, "reply": "\n\n".join(said)}
            time.sleep(0.5)
        return {"ok": True, "reply": "Jarvis masih bekerja. Tengok app Jarvis untuk jawapan penuh."}

    def reset(self):
        """Sesi baru: kosongkan suapan dan beritahu fon supaya membersihkan skrinnya."""
        with self._lock:
            self.feed.clear()
        self.push("reset", {"text": ""})

    def on_emit(self, kind, data):
        """Dipanggil dari Api._emit: simpan hanya yang fon perlukan."""
        data = data or {}
        if kind == "text" and data.get("text"):
            self.push("jarvis", {"text": str(data["text"])[:6000]})
        elif kind == "tool":
            self.push("tool", {"text": f"{data.get('name', '')} · {str(data.get('detail', ''))[:80]}"})
        elif kind == "done":
            if not data.get("ok"):
                self.push("error", {"text": str(data.get("error") or "gagal")[:200]})
            self.push("done", {"text": ""})
        elif kind == "note" and data.get("text"):
            self.push("note", {"text": str(data["text"])[:300]})

    def state(self, since=0):
        a = self.api
        busy = bool(getattr(a, "_chat_busy", False) or getattr(a, "_proc", None))
        with self._lock:
            ev = [e for e in self.feed if e["seq"] > since]
        theme = "asal"
        try:
            theme = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8")).get("theme", "asal")
        except Exception:
            pass
        return {"seq": self.seq, "events": ev, "busy": busy, "theme": theme}

    def say(self, text):
        text = text.strip()
        if not text:
            return {"ok": False}
        self.push("me", {"text": text})
        a = self.api
        try:
            done = a.quick_control(text, allow_open=True) or {}
        except Exception:
            done = {}
        if done.get("handled"):
            a._voice_emit("control", {"text": text, "label": done.get("label", "")})
            self.push("note", {"text": "✓ " + (done.get("label") or "Done")})
            return {"ok": True, "handled": True}
        a._show_window()
        a._voice_emit("text", text)
        return {"ok": True, "handled": False}


_ICON_CACHE = {}
_ORB = {"mt": 0, "js": ""}


def orb_js(ui_dir: Path) -> str:
    """Kod orb HUD, diambil terus dari stage.html — orb fon sentiasa sama dengan orb laptop,
    tanpa salinan yang boleh tersimpang. Dibaca semula hanya bila stage.html berubah."""
    p = ui_dir / "stage.html"
    try:
        mt = p.stat().st_mtime
        if mt != _ORB["mt"]:
            src = p.read_text(encoding="utf-8")
            a = src.index("  const orb = document.getElementById('orb');")
            b = src.index("/* ── background dust ── */")
            _ORB.update(mt=mt, js=src[a:b].replace("</script", "<\\/script"))
    except Exception:
        pass
    return _ORB["js"]


def icon_png(size: int, ui_dir: Path) -> bytes:
    """Ikon skrin utama segi empat daripada ui/logo.png (140x99, bukan segi empat).

    Chrome menolak ikon < 144 px atau tak segi empat dan memaparkan huruf pertama
    nama app ('J') sebagai ganti. Latar gelap + cahaya ungu/emas, logo di tengah,
    dalam zon selamat 'maskable' (80% tengah) supaya tak terpotong oleh bentuk ikon fon."""
    if size in _ICON_CACHE:
        return _ICON_CACHE[size]
    import io
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGBA", (size, size), (7, 4, 15, 255))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    r = int(size * 0.36)
    d.ellipse((size // 2 - r, size // 2 - r, size // 2 + r, size // 2 + r), fill=(120, 60, 220, 150))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(size * 0.12)))
    d2 = ImageDraw.Draw(im)
    w = max(2, size // 64)
    rr = int(size * 0.40)
    d2.ellipse((size // 2 - rr, size // 2 - rr, size // 2 + rr, size // 2 + rr), outline=(255, 201, 58, 210), width=w)
    logo = Image.open(ui_dir / "logo.png").convert("RGBA")
    lw = int(size * 0.56)
    logo = logo.resize((lw, int(lw * logo.height / logo.width)), Image.LANCZOS)
    im.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG", optimize=True)
    _ICON_CACHE[size] = buf.getvalue()
    return _ICON_CACHE[size]


def manifest(ui_dir: Path) -> dict:
    """Ikon sebagai data: URI — fon tak perlu memuat turunnya melalui Cloudflare Access."""
    import base64
    m = dict(MANIFEST)
    m["icons"] = [{"src": "data:image/png;base64," + base64.b64encode(icon_png(n, ui_dir)).decode(),
                   "sizes": f"{n}x{n}", "type": "image/png", "purpose": p}
                  for n in (192, 512) for p in ("any", "maskable")]
    return m


MANIFEST = {
    "name": "Jarvis", "short_name": "Jarvis", "start_url": "/", "display": "standalone",
    "background_color": "#07040f", "theme_color": "#07040f",
    "icons": [{"src": "/icon.png", "sizes": "192x192", "type": "image/png"}],
}

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Jarvis</title><link rel="manifest" href="/manifest.json" crossorigin="use-credentials">
<link rel="icon" href="__ICON__"><link rel="apple-touch-icon" href="__ICON__">
<meta name="theme-color" content="#07040f">
<style>
:root{--a:272;--b:318;--bg:#0b0618;--ink:#e6f2fa;--dim:#8fa6b4}
html[data-theme=stark]{--a:196;--b:38;--bg:#06111b}
html[data-theme=inferno]{--a:26;--b:356;--bg:#170905}
html[data-theme=mark]{--a:356;--b:44;--bg:#180408}
*{box-sizing:border-box}html,body{margin:0;height:100%;width:100%;overflow-x:hidden}
body{background:radial-gradient(120% 70% at 50% 0%,hsl(var(--a) 90% 40%/.35),transparent 60%),var(--bg);
 color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:10px;padding:calc(10px + env(safe-area-inset-top)) 16px 8px}
header img{width:30px}header b{letter-spacing:.35em;font-size:15px}
header span{margin-left:auto;font-size:11px;color:var(--dim)}
#proj{background:none;border:1px solid hsl(var(--b) 90% 65%/.45);color:hsl(var(--b) 100% 78%);border-radius:14px;
 padding:4px 10px;font-size:12px;margin-left:8px;max-width:38vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#delta{display:none;background:hsl(38 100% 50%/.18);border:1px solid hsl(38 100% 60%/.6);color:hsl(38 100% 72%);
 border-radius:14px;padding:4px 10px;font-size:12px;margin-left:6px}
.sheet{position:fixed;inset:0;z-index:50;display:none;background:rgba(0,0,0,.55)}
.sheet.on{display:flex;align-items:flex-end}
.sheet>div{width:100%;max-height:82vh;display:flex;flex-direction:column;background:#0d0a18;border-top:1px solid hsl(var(--a) 80% 70%/.35);
 border-radius:18px 18px 0 0;padding:14px 14px calc(14px + env(safe-area-inset-bottom))}
.sheet h3{margin:0 0 10px;font-size:13px;letter-spacing:.2em;text-transform:uppercase;color:hsl(var(--b) 100% 74%);display:flex}
.sheet h3 button{margin-left:auto;background:none;border:0;color:var(--dim);font-size:18px}
.plist{overflow-y:auto}.plist div{padding:11px 6px;border-bottom:1px solid rgba(255,255,255,.06)}
.plist div.on{color:hsl(var(--b) 100% 74%);font-weight:600}
#dcode{flex:1;overflow:auto;margin:0;font:11px/1.5 ui-monospace,Consolas,monospace;white-space:pre;background:rgba(255,255,255,.03);
 border-radius:8px;padding:8px}
#dcode span{display:block}#dcode .a{color:#5ee6a0}#dcode .d{color:#ff7d8a}#dcode .h{color:#7fd0ff;margin-top:8px;font-weight:600}
#dcode .at{color:#c49bff}
.drow{display:flex;gap:8px;margin-top:10px}.drow input{flex:1}
.drow button{border:0;border-radius:22px;padding:0 16px;font-weight:600;color:#1a0d00;background:linear-gradient(135deg,#ffc93a,#ff8a3a)}
@media (max-width:430px){header{gap:6px;padding-left:10px;padding-right:10px}header b{letter-spacing:.12em;font-size:13px}
 #net{font-size:0}#net::first-letter{font-size:12px}#proj{max-width:30vw;margin-left:4px}#new{padding:4px 8px}}
#hist{background:none;border:1px solid hsl(var(--a) 80% 70%/.4);color:var(--ink);border-radius:14px;
 padding:4px 9px;font-size:12px;margin-left:6px}
.hlist{overflow-y:auto}.hrow{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid rgba(255,255,255,.06)}
.hrow .tx{flex:1;min-width:0}.hrow b{display:block;font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hrow small{display:block;font-size:11px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hrow button{flex:none;border:1px solid rgba(255,95,112,.5);background:rgba(255,95,112,.1);color:#ff8a96;border-radius:10px;
 padding:6px 10px;font-size:12px}.hrow button.armed{background:#d9283e;color:#fff}
#new{background:none;border:1px solid hsl(var(--a) 80% 70%/.4);color:var(--ink);border-radius:14px;
 padding:4px 11px;font-size:12px;margin-left:10px}
/* orb di bawah (dekat ibu jari), dilukis oleh kod orb HUD yang sama (stage.html) */
.dock{flex:none;display:flex;flex-direction:column;align-items:center;padding:4px 0 2px}
.orbbox{position:relative;width:min(62vw,250px);aspect-ratio:1;cursor:pointer;touch-action:none;user-select:none;
 -webkit-user-select:none;-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent;transition:transform .18s}
body.listen .orbbox{transform:scale(1.07)}
#orb,.orb-layer{position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none}
.orb-layer.sph{filter:var(--orb-core,none);transition:filter .8s}
:root{--orb-core:hue-rotate(-62deg) saturate(1.6)}
html[data-theme=stark]{--orb-core:none}
html[data-theme=inferno]{--orb-core:sepia(.5) saturate(3.6) hue-rotate(-50deg)}
html[data-theme=mark]{--orb-core:hue-rotate(155deg) saturate(1.3) brightness(1.15)}
.orbbox::after{content:"";position:absolute;inset:8%;border-radius:50%;pointer-events:none;
 box-shadow:0 0 0 0 rgba(255,59,78,0);transition:box-shadow .2s}
body.listen .orbbox::after{box-shadow:0 0 0 3px rgba(255,59,78,.55),0 0 40px 6px rgba(255,59,78,.45)}
#hint{text-align:center;font-size:10px;color:var(--dim);margin:1px 0 4px}
#st{text-align:center;font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:hsl(var(--b) 100% 72%);margin-top:-6px}
#log{flex:1;overflow-y:auto;padding:10px 14px;display:flex;flex-direction:column;gap:8px}
.m{max-width:88%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}
.me{align-self:flex-end;background:hsl(var(--a) 70% 40%/.55)}
.jarvis{align-self:flex-start;background:rgba(255,255,255,.07);border:1px solid hsl(var(--a) 80% 70%/.25)}
.tool,.note{align-self:center;font-size:11px;color:var(--dim);background:none;padding:2px}
.error{align-self:center;font-size:12px;color:#ff6b78}
.jarvis button{display:block;margin-top:6px;background:none;border:1px solid hsl(var(--b) 90% 65%/.5);color:var(--ink);
 border-radius:10px;padding:3px 10px;font-size:12px}
form{display:flex;gap:8px;padding:10px 12px calc(10px + env(safe-area-inset-bottom));background:rgba(0,0,0,.35)}
input{flex:1;min-width:0;background:rgba(255,255,255,.08);border:1px solid hsl(var(--a) 80% 70%/.3);color:var(--ink);
 border-radius:22px;padding:11px 16px;font-size:16px;outline:none}
form button{flex:none;border:0;border-radius:22px;padding:0 14px;min-width:44px;font-size:17px;font-weight:600;color:#fff;
 background:linear-gradient(135deg,hsl(var(--a) 90% 50%),hsl(var(--b) 90% 50%))}
#stop{display:none;background:#5a1820}body.busy #stop{display:block}
#mic{background:rgba(255,255,255,.1)}
@keyframes pu{50%{transform:scale(1.12);opacity:.8}}
#mic.rec{background:#c8101e;animation:pu 1s ease-in-out infinite}
</style></head><body>
<header><img src="__ICON__" alt=""><b>J.A.R.V.I.S</b><span id="net">…</span><button type="button" id="proj">📁 —</button><button type="button" id="delta">Δ</button><button type="button" id="hist">🕘</button><button type="button" id="new">＋ New</button></header>
<div class="sheet" id="hsheet"><div><h3>History<button type="button" data-x>✕</button></h3><div class="hlist" id="hlist"></div></div></div>
<div class="sheet" id="psheet"><div><h3>Projects<button type="button" data-x>✕</button></h3><div class="plist" id="plist"></div></div></div>
<div class="sheet" id="dsheet"><div><h3 id="dtitle">Changes<button type="button" data-x>✕</button></h3><pre id="dcode"></pre>
<div class="drow"><input id="dmsg" placeholder="Commit message"><button type="button" id="dcommit">Commit</button></div></div></div>
<div id="log"></div>
<div class="dock"><div class="orbbox" id="orbbox" role="button" aria-label="Press and hold to talk"><canvas id="orb"></canvas></div>
<div id="st">Standby</div><div id="hint">Press &amp; hold the orb to talk</div></div>
<form id="f"><input id="q" placeholder="Ask Jarvis…" autocomplete="off" enterkeyhint="send">
<button type="button" id="mic" aria-label="Talk">🎙</button><button type="button" id="stop" aria-label="Stop">■</button><button aria-label="Send">➤</button></form>
<script>
(function(){
/*__ORB__*/
})();
</script>
<script>
const orbSt=s=>window.orbState&&window.orbState(s);let speakingNow=false;
let seq=0,busy=false,timer=0,inflight=false;const log=document.getElementById('log');
const add=(kind,text)=>{const d=document.createElement('div');d.className='m '+kind;d.textContent=text;
 if(kind==='jarvis'){const b=document.createElement('button');b.textContent='🔊 Listen';
  b.onclick=async()=>{b.disabled=true;try{const r=await(await fetch('/api/tts',{method:'POST',body:JSON.stringify({text})})).json();
  if(r.ok){const au=new Audio(r.src);speakingNow=true;orbSt('speaking');
   au.onended=au.onerror=()=>{speakingNow=false;orbSt(busy?'thinking':'idle')};au.play()}}finally{b.disabled=false}};d.appendChild(b)}
 log.appendChild(d);log.scrollTop=log.scrollHeight};
async function poll(){if(inflight)return;inflight=true;clearTimeout(timer);try{const r=await(await fetch('/api/state?since='+seq)).json();
 document.getElementById('net').textContent='● online';
 if(r.theme&&r.theme!=='asal')document.documentElement.dataset.theme=r.theme;else delete document.documentElement.dataset.theme;
 for(const e of r.events){if(e.kind==='reset'){log.textContent='';continue}if(e.kind==='done'){projRefresh();continue}add(e.kind,e.text)}seq=r.seq;busy=r.busy;document.body.classList.toggle('busy',busy);
 if(!rec){document.getElementById('st').textContent=busy?'Thinking':'Standby';if(!speakingNow)orbSt(busy?'thinking':'idle')}}
 catch(e){document.getElementById('net').textContent='○ offline'}
 inflight=false;timer=setTimeout(poll,busy?900:2500)}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const q=document.getElementById('q');const t=q.value.trim();
 if(!t)return;q.value='';await fetch('/api/say',{method:'POST',body:JSON.stringify({text:t})});clearTimeout(timer);timer=setTimeout(poll,300)};
document.getElementById('stop').onclick=()=>fetch('/api/stop',{method:'POST'});
document.getElementById('new').onclick=async()=>{log.textContent='';await fetch('/api/new',{method:'POST'});
 clearTimeout(timer);timer=setTimeout(poll,300)};
// mic: tekan sekali untuk mula, sekali lagi untuk hantar (perlukan HTTPS — laluan domain)
// Rakaman suara: tahan orb untuk bercakap, lepas untuk hantar. Butang 🎙 = tekan sekali mula, sekali lagi hantar.
let rec=null,chunks=[],stream=null,t0=0,wantStop=false;
const mic=document.getElementById('mic'),orb=document.getElementById('orbbox'),stEl=document.getElementById('st'),hint=document.getElementById('hint');
let actx=null,lvlRaf=0;
function meter(st){try{actx=actx||new AudioContext();const an=actx.createAnalyser();an.fftSize=512;
 actx.createMediaStreamSource(st).connect(an);const buf=new Uint8Array(an.fftSize);
 const tick=()=>{an.getByteTimeDomainData(buf);let s=0;for(const v of buf){const x=(v-128)/128;s+=x*x}
  window.orbLevel&&window.orbLevel(Math.min(1,Math.sqrt(s/buf.length)*4));if(rec)lvlRaf=requestAnimationFrame(tick)};tick()}catch(e){}}
async function startRec(){
 if(rec)return;
 if(!navigator.mediaDevices){add('error','Microphone needs https://');return}
 wantStop=false;
 try{stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}})}
 catch(e){add('error','Mic: '+e.message);return}
 if(wantStop){stream.getTracks().forEach(t=>t.stop());return}   // dilepas sebelum kebenaran mic siap
 chunks=[];rec=new MediaRecorder(stream);rec.ondataavailable=e=>e.data.size&&chunks.push(e.data);
 rec.onstop=send;rec.start();t0=Date.now();
 document.body.classList.add('listen');mic.classList.add('rec');stEl.textContent='Listening…';hint.textContent='Release to send';
 orbSt('listening');meter(stream);
 if(navigator.vibrate)navigator.vibrate(25)}
function stopRec(){wantStop=true;if(rec&&rec.state==='recording')rec.stop()}
async function send(){
 const dur=Date.now()-t0;stream&&stream.getTracks().forEach(t=>t.stop());
 document.body.classList.remove('listen');mic.classList.remove('rec');rec=null;hint.textContent='Press & hold the orb to talk';
 cancelAnimationFrame(lvlRaf);window.orbLevel&&window.orbLevel(0);orbSt('thinking');
 if(navigator.vibrate)navigator.vibrate([15,40,15]);
 if(dur<500){stEl.textContent='Too short — hold while you talk';return}
 stEl.textContent='Processing voice…';
 try{const r=await(await fetch('/api/voice',{method:'POST',body:new Blob(chunks)})).json();
  if(!r.ok)add('error',r.msg||'failed')}catch(e){add('error','Could not send voice')}
 clearTimeout(timer);timer=setTimeout(poll,300)}
orb.addEventListener('pointerdown',e=>{e.preventDefault();orb.setPointerCapture&&orb.setPointerCapture(e.pointerId);startRec()});
['pointerup','pointercancel'].forEach(k=>orb.addEventListener(k,e=>{e.preventDefault();stopRec()}));
orb.addEventListener('contextmenu',e=>e.preventDefault());
mic.onclick=()=>rec?stopRec():startRec();
// ── projek: pilih, lihat perubahan, commit ──
const $=id=>document.getElementById(id);
const post=(u,b)=>fetch(u,{method:'POST',body:JSON.stringify(b||{})}).then(r=>r.json());
let projNames=[],projCur=null;
async function projRefresh(){try{const p=await post('/api/project');projCur=p.name;projNames=p.projects||[];
 $('proj').textContent='📁 '+(p.name||'No project');
 if(p.name){const d=await post('/api/diff');const n=d.ok?d.files.length:0;$('delta').style.display=n?'inline-block':'none';
  $('delta').textContent='Δ '+n;$('delta')._d=d}else $('delta').style.display='none'}catch(e){}}
document.querySelectorAll('.sheet').forEach(sh=>sh.addEventListener('click',e=>{if(e.target===sh||e.target.hasAttribute('data-x'))sh.classList.remove('on')}));
$('proj').onclick=()=>{const l=$('plist');l.textContent='';
 ['(No project)'].concat(projNames).forEach((n,i)=>{const d=document.createElement('div');d.textContent=(i?'📁 ':'')+n;
  if((i===0&&!projCur)||n===projCur)d.className='on';
  d.onclick=async()=>{$('psheet').classList.remove('on');await post('/api/project',{name:i?n:''});projRefresh()};l.appendChild(d)});
 $('psheet').classList.add('on')};
$('delta').onclick=async()=>{const d=await post('/api/diff');if(!d.ok)return;
 $('dtitle').firstChild.textContent='Changes · '+d.name+' · '+d.files.length+' files';
 const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
 $('dcode').innerHTML=esc(d.diff||'(no changes)').split('\n').map(l=>'<span class="'+(l.startsWith('diff --git')?'h':l.startsWith('@@')?'at':(l.startsWith('+')&&!l.startsWith('+++'))?'a':(l.startsWith('-')&&!l.startsWith('---'))?'d':'p')+'">'+(l||' ')+'</span>').join('');
 $('dsheet').classList.add('on')};
$('dcommit').onclick=async()=>{const r=await post('/api/commit',{msg:$('dmsg').value});
 add(r.ok?'note':'error',(r.ok?'✓ Committed: ':'Commit failed: ')+(r.msg||''));if(r.ok){$('dmsg').value='';$('dsheet').classList.remove('on')}projRefresh()};
// ── sejarah sesi: ketuk untuk buka (laptop ikut), 🗑 dua kali untuk padam ──
function when(t){const d=new Date(t*1000),n=new Date();return d.toDateString()===n.toDateString()?
 d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):d.toLocaleDateString([], {day:'numeric',month:'short'})}
async function histLoad(){const l=$('hlist');l.textContent='';let r={};try{r=await post('/api/sessions')}catch(e){}
 const rows=r.sessions||[];if(!rows.length){l.innerHTML='<div class="hrow"><small>No saved sessions yet. Tap ＋ New and the current chat is saved here.</small></div>';return}
 for(const s of rows){const row=document.createElement('div');row.className='hrow';
  const tx=document.createElement('div');tx.className='tx';const b=document.createElement('b');b.textContent=s.title;
  const sm=document.createElement('small');sm.textContent=when(s.updated)+' · '+s.count+' messages'+(s.project?' · '+s.project:'');
  tx.append(b,sm);const del=document.createElement('button');del.textContent='🗑';
  tx.onclick=async()=>{const o=await post('/api/session/open',{id:s.id});if(!o.ok){add('error',o.msg||'Could not open');return}
   $('hsheet').classList.remove('on');clearTimeout(timer);timer=setTimeout(poll,200);projRefresh()};
  del.onclick=async()=>{if(!del.classList.contains('armed')){del.classList.add('armed');del.textContent='Delete?';
   setTimeout(()=>{del.classList.remove('armed');del.textContent='🗑'},2500);return}
   await post('/api/session/delete',{id:s.id});histLoad()};
  row.append(tx,del);l.appendChild(row)}}
$('hist').onclick=()=>{$('hsheet').classList.add('on');histLoad()};
projRefresh();
poll();
</script></body></html>"""
