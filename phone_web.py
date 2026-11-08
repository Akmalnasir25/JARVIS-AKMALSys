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
        self.runtime = Path(secrets_path).parent / "runtime"
        self._last_reply = ""
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

            def _file(self, raw, dl=False):
                import mimetypes
                p = web._allowed(raw)
                if not p or not p.is_file():
                    return self._send(404, b"not found", "text/plain")
                size = p.stat().st_size
                ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                start, end = 0, size - 1
                rng = self.headers.get("Range") or ""
                if rng.startswith("bytes="):
                    a, _, b = rng[6:].split(",")[0].partition("-")
                    start = int(a) if a else max(0, size - int(b or 0))
                    end = min(int(b), size - 1) if (a and b) else end
                self.send_response(206 if rng else 200)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if rng:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                disp = "attachment" if dl else "inline"
                self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{urllib.parse.quote(p.name)}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(p, "rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(262144, left))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except OSError:                 # fon tutup sambungan (lompat video, batal)
                            return
                        left -= len(chunk)

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
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                arg = (q.get("path") or [""])[0]
                if path == "/sw.js":
                    return self._send(200, SW.encode(), "text/javascript", {"Service-Worker-Allowed": "/"})
                if path == "/api/files":
                    return self._json(web.files(arg))
                if path == "/api/preview":
                    return self._json(web.preview(arg))
                if path == "/api/file":
                    return self._file(arg, (q.get("dl") or [""])[0] == "1")
                if path == "/api/screen":
                    try:
                        return self._send(200, web.screen(), "image/jpeg")
                    except Exception as e:
                        return self._send(500, str(e).encode(), "text/plain")
                if path == "/api/brief":
                    try:
                        return self._json(web.api.brief_last())
                    except Exception as e:
                        return self._json({"ok": False, "msg": str(e)})
                if path == "/api/push/key":
                    return self._json(web.push_key())
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
                if path == "/api/upload":                     # fail/gambar dari fon -> laptop
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > 60_000_000:
                        return self._json({"ok": False, "msg": "File too large (max 60 MB)"}, 413)
                    return self._json(web.upload((q.get("name") or ["upload"])[0], self.rfile.read(n),
                                                 (q.get("ask") or [""])[0] == "1"))
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
                if path == "/api/open":
                    return self._json(web.open_on_laptop(str(body.get("path") or "")))
                if path == "/api/control":
                    return self._json(web.control(str(body.get("action") or "")))
                if path == "/api/push/sub":
                    return self._json(web.subscribe(body.get("sub")))
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

    # ════════ fail laptop: BACA SAHAJA (layar, pratonton, muat turun, buka di laptop) ════════
    TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".html", ".htm", ".css",
                ".php", ".log", ".yml", ".yaml", ".xml", ".ini", ".sql", ".bat", ".ps1", ".sh", ".env.example",
                ".vue", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".kt", ".swift", ".blade.php", ".toml"}

    def _roots(self):
        try:
            return [(n, Path(p).resolve()) for n, p in self.api.web_roots() if Path(p).is_dir()]
        except Exception:
            return []

    SECRET_NAMES = {"secrets.json", "sessions.json", "cache.json", "chat_history.json", "push_subs.json",
                    "id_rsa", "id_ed25519", "known_hosts", "authorized_keys", ".npmrc", ".pypirc", ".netrc",
                    "cookies", "cookies.sqlite", "login data", "web data"}
    SECRET_EXT = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".keystore", ".jks", ".ppk", ".ovpn", ".sqlite"}
    SECRET_DIRS = {".git", ".ssh", ".cloudflared", ".aws", ".azure", ".gnupg", ".docker", "runtime", "appdata",
                   ".vscode", ".claude", "node_modules"}

    def _sensitive(self, p: Path) -> bool:
        """Fail rahsia tak pernah keluar ke fon, walaupun di dalam folder yang dibenarkan
        (cth secrets.json dalam folder projek jarvis-desktop, .env dalam projek web)."""
        n = p.name.lower()
        if n in self.SECRET_NAMES or p.suffix.lower() in self.SECRET_EXT or n.startswith(".env"):
            return True
        if any(w in n for w in ("credential", "secret", "token", "password", "passwd", "service-account", "serviceaccount")):
            return True
        return any(part.lower() in self.SECRET_DIRS for part in p.parts)

    def _allowed(self, raw):
        """Laluan mesti di dalam salah satu folder yang dibenarkan, tiada '..' melepasi sempadan,
        dan bukan fail/folder rahsia."""
        try:
            p = Path(raw).resolve()
        except Exception:
            return None
        for _, r in self._roots():
            if (p == r or r in p.parents) and not self._sensitive(p.relative_to(r.parent) if r.parent != r else p):
                return p
        return None

    def files(self, raw=""):
        if not raw:
            return {"ok": True, "path": "", "parent": "", "items": [
                {"name": n, "path": str(p), "dir": True, "size": 0, "mtime": 0} for n, p in self._roots()]}
        p = self._allowed(raw)
        if not p or not p.is_dir():
            return {"ok": False, "msg": "Folder not allowed"}
        items = []
        try:
            for c in p.iterdir():
                if c.name.startswith((".", "~$")) or c.name in ("desktop.ini", "Thumbs.db", "node_modules", "__pycache__")                         or self._sensitive(Path(c.name)):
                    continue
                try:
                    st = c.stat()
                except OSError:
                    continue
                items.append({"name": c.name, "path": str(c), "dir": c.is_dir(),
                              "size": 0 if c.is_dir() else st.st_size, "mtime": int(st.st_mtime)})
        except OSError as e:
            return {"ok": False, "msg": str(e)}
        items.sort(key=lambda x: (not x["dir"], -x["mtime"]))
        top = any(p == r for _, r in self._roots())
        return {"ok": True, "path": str(p), "parent": "" if top else str(p.parent), "items": items[:600]}

    def preview(self, raw):
        p = self._allowed(raw)
        if not p or not p.is_file():
            return {"ok": False, "msg": "File not allowed"}
        name = p.name.lower()
        if any(name.endswith(e) for e in self.TEXT_EXT) and p.stat().st_size < 400_000:
            return {"ok": True, "kind": "text", "text": p.read_text(encoding="utf-8", errors="replace")}
        if p.suffix.lower() in (".docx", ".xlsx", ".xlsm", ".pptx"):
            try:
                msg, _ = self.api._tool_read(str(p))
                return {"ok": True, "kind": "text", "text": msg}
            except Exception as e:
                return {"ok": False, "msg": str(e)}
        return {"ok": True, "kind": "file"}

    def open_on_laptop(self, raw):
        import os
        p = self._allowed(raw)
        if not p:
            return {"ok": False, "msg": "File not allowed"}
        os.startfile(str(p))
        self.push("note", {"text": f"✓ Opened on laptop: {p.name}"})
        return {"ok": True}

    # ════════ hantar fail dari fon ════════
    def upload(self, name, data: bytes, ask=False):
        import re as _re
        name = _re.sub(r'[\\/:*?"<>|]+', "_", (name or "upload").strip())[:120] or "upload"
        d = self.api.upload_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        n = 1
        while p.exists():
            p = d / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        p.write_bytes(data)
        self.push("note", {"text": f"✓ Saved on laptop: {p}"})
        if ask:
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"):
                threading.Thread(target=self._describe_image, args=(p,), daemon=True).start()
            else:
                self.say(f'Baca fail "{p}" dan ringkaskan isi pentingnya.')
        return {"ok": True, "path": str(p)}

    def _describe_image(self, p):
        self.push("tool", {"text": f"Reading image · {p.name}"})
        try:
            txt = self.api._claude_quick(
                f'Baca imej "{p}" (gambar yang Tuan ambil dengan fon). Terangkan apa isinya dalam BM santai; '
                "kalau ia dokumen/surat/borang, salin maklumat penting (tarikh, nama, jumlah, tindakan).",
                ["Read"], model="sonnet")
            self.push("jarvis", {"text": str(txt)[:6000]})
            self.api._push(f"window.jarvisSay && window.jarvisSay({json.dumps(str(txt))})")
        except Exception as e:
            self.push("error", {"text": f"Could not read image: {e}"})

    # ════════ skrin laptop ════════
    def screen(self) -> bytes:
        import io
        import tempfile
        import services as sv
        from PIL import Image
        f = Path(tempfile.gettempdir()) / "jarvis-phone-screen.png"
        sv.screenshot(str(f))
        im = Image.open(f).convert("RGB")
        if im.width > 1400:
            im = im.resize((1400, int(im.height * 1400 / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=68)
        return buf.getvalue()

    # ════════ kawalan pantas ════════
    CONTROLS = {"vol_up": "volume naik", "vol_down": "volume turun", "mute": "mute", "unmute": "unmute",
                "play": "main lagu", "next": "lagu seterusnya", "prev": "lagu sebelum",
                "bright_up": "cerahkan skrin", "bright_down": "malapkan skrin",
                "lock": "kunci laptop", "sleep": "sleep laptop"}

    def control(self, action):
        text = self.CONTROLS.get(action)
        if not text:
            return {"ok": False, "msg": "Unknown control"}
        a = self.api
        try:
            r = a.quick_control(text, allow_open=False) or {}
            # lock/sleep perlu pengesahan; Tuan sudah mengesahkan di fon (dialog confirm) sebelum ini dihantar
            if action in ("lock", "sleep") and getattr(a, "_pending_token", None):
                r = a.quick_control("ya", allow_open=False) or r
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": bool(r.get("handled")), "msg": r.get("label", "")}

    # ════════ notifikasi Web Push ════════
    def _vapid(self):
        """Kunci VAPID dijana sekali, disimpan dalam runtime/ (gitignored)."""
        import base64
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
        pem = self.runtime / "vapid_private.pem"
        if not pem.exists():
            v = Vapid()
            v.generate_keys()
            v.save_key(str(pem))
        v = Vapid.from_file(str(pem))
        raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return str(pem), base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def push_key(self):
        try:
            return {"ok": True, "key": self._vapid()[1]}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def _subs(self):
        try:
            return json.loads((self.runtime / "push_subs.json").read_text(encoding="utf-8"))
        except Exception:
            return []

    def subscribe(self, sub):
        if not isinstance(sub, dict) or not str(sub.get("endpoint", "")).startswith("https://"):
            return {"ok": False}
        subs = [x for x in self._subs() if x.get("endpoint") != sub["endpoint"]] + [sub]
        (self.runtime / "push_subs.json").write_text(json.dumps(subs[-5:]), encoding="utf-8")
        threading.Thread(target=self.notify, args=("Jarvis", "Notifications are on ✓", "hello"), daemon=True).start()
        return {"ok": True}

    def notify(self, title, body, tag="jarvis"):
        subs = self._subs()
        if not subs:
            return
        try:
            from pywebpush import WebPushException, webpush
            pem, _ = self._vapid()
        except Exception as e:
            self.log(f"push tak tersedia: {e}")
            return
        keep = []
        for sub in subs:
            try:
                webpush(subscription_info=sub, data=json.dumps({"title": title, "body": str(body)[:300], "tag": tag}),
                        vapid_private_key=pem, vapid_claims={"sub": "mailto:" + (self.email or "jarvis@localhost")},
                        ttl=3600)
                keep.append(sub)
            except WebPushException as e:
                code = getattr(getattr(e, "response", None), "status_code", 0)
                if code not in (404, 410):          # langganan mati dibuang; ralat lain dicuba lagi nanti
                    keep.append(sub)
                self.log(f"push gagal {code}: {str(e)[:120]}")
            except Exception as e:
                keep.append(sub)
                self.log(f"push gagal: {e}")
        if len(keep) != len(subs):
            (self.runtime / "push_subs.json").write_text(json.dumps(keep), encoding="utf-8")

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
            self._last_reply = str(data["text"])
            self.push("jarvis", {"text": self._last_reply[:6000]})
        elif kind == "tool":
            self.push("tool", {"text": f"{data.get('name', '')} · {str(data.get('detail', ''))[:80]}"})
        elif kind == "done":
            if not data.get("ok"):
                self.push("error", {"text": str(data.get("error") or "gagal")[:200]})
            self.push("done", {"text": ""})
            try:
                if float(data.get("secs") or 0) >= 15:     # kerja panjang (coding, analisis) siap
                    body = (self._last_reply or "Done").strip().split("\n")[0][:160] if data.get("ok") \
                        else str(data.get("error") or "failed")[:160]
                    threading.Thread(target=self.notify, args=("Jarvis ✓" if data.get("ok") else "Jarvis ✕", body, "turn"),
                                     daemon=True).start()
            except Exception:
                pass
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


SW = r"""
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', e => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (x) {}
  e.waitUntil(self.registration.showNotification(d.title || 'Jarvis',
    { body: d.body || '', icon: '/icon.png', badge: '/icon.png', tag: d.tag || 'jarvis', renotify: true }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true })
    .then(cs => cs.length ? cs[0].focus() : clients.openWindow('/')));
});
"""

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
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:4px 0 6px}
.tiles button{display:flex;flex-direction:column;align-items:center;gap:6px;padding:14px 4px;border-radius:14px;
 background:rgba(255,255,255,.05);border:1px solid hsl(var(--a) 80% 70%/.25);color:var(--ink);font-size:12px}
.tiles button i{font-style:normal;font-size:24px}
.sheet h3 .fref{margin-left:auto;margin-right:6px;font-size:17px;color:hsl(var(--b) 100% 74%)}
.sheet h3 .fref+button{margin-left:0}.fref.spin{animation:fspin .6s linear}
@keyframes fspin{to{transform:rotate(360deg)}}
.frow.new b::after{content:" NEW";font-size:9px;font-weight:700;color:#5ee6a0;letter-spacing:.08em}
.crumb{font-size:11px;color:var(--dim);margin:-4px 0 8px;word-break:break-all}
.flist{overflow-y:auto}.frow{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid rgba(255,255,255,.06)}
.frow i{font-style:normal;font-size:20px;width:26px;text-align:center}.frow .tx{flex:1;min-width:0}
.frow b{display:block;font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.frow small{font-size:11px;color:var(--dim)}
#vbody{flex:1;overflow:auto;min-height:120px;border-radius:10px;background:rgba(255,255,255,.03)}
#vbody img,#vbody video{display:block;max-width:100%;margin:0 auto}
#vbody pre{margin:0;padding:10px;font:11px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.vrow{display:flex;gap:8px;margin-top:10px}.vrow a,.vrow button{flex:1;text-align:center;text-decoration:none;border:0;border-radius:22px;
 padding:11px;font-size:13px;font-weight:600;color:#fff;background:linear-gradient(135deg,hsl(var(--a) 90% 50%),hsl(var(--b) 90% 50%))}
.vrow .ghost{background:rgba(255,255,255,.08);color:var(--ink)}
#simg{width:100%;border-radius:8px;display:block}
.ctl{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.ctl button{padding:16px 4px;border-radius:14px;font-size:22px;background:rgba(255,255,255,.05);color:var(--ink);
 border:1px solid hsl(var(--a) 80% 70%/.25)}.ctl button small{display:block;font-size:10px;margin-top:4px;color:var(--dim)}
.ctl .warn{border-color:rgba(255,95,112,.5)}
#brieft{white-space:pre-wrap;font-size:14px;line-height:1.6;overflow-y:auto}
.uprow{display:flex;align-items:center;gap:8px;margin:10px 0;font-size:13px}
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
<header><img src="__ICON__" alt=""><b>J.A.R.V.I.S</b><span id="net">…</span><button type="button" id="proj">📁 —</button><button type="button" id="delta">Δ</button><button type="button" id="hist">☰</button><button type="button" id="new">＋ New</button></header>
<div class="sheet" id="msheet"><div><h3>Jarvis<button type="button" data-x>✕</button></h3>
<div class="tiles">
<button type="button" data-open="hist"><i>🕘</i>History</button>
<button type="button" data-open="files"><i>📂</i>Files</button>
<button type="button" data-open="screen"><i>🖥</i>Screen</button>
<button type="button" data-open="ctl"><i>🎛</i>Controls</button>
<button type="button" data-open="up"><i>📤</i>Send file</button>
<button type="button" data-open="brief"><i>☀</i>Daily brief</button>
<button type="button" id="notif"><i>🔔</i>Notifications</button>
</div></div></div>
<div class="sheet" id="fsheet"><div><h3>Files<button type="button" id="fref" class="fref">↻</button><button type="button" data-x>✕</button></h3>
<div class="crumb" id="fcrumb"></div><div class="flist" id="flist"></div></div></div>
<div class="sheet" id="vsheet"><div><h3 id="vtitle">File<button type="button" data-x>✕</button></h3><div id="vbody"></div>
<div class="vrow"><a id="vdl" class="ghost" href="#">⬇ Download</a><button type="button" id="vopen">🖥 Open on laptop</button></div></div></div>
<div class="sheet" id="ssheet"><div><h3>Laptop screen<button type="button" data-x>✕</button></h3><img id="simg" alt="">
<div class="vrow"><button type="button" class="ghost" id="sref">↻ Refresh</button></div></div></div>
<div class="sheet" id="csheet"><div><h3>Controls<button type="button" data-x>✕</button></h3><div class="ctl">
<button type="button" data-c="vol_down">🔉<small>Vol −</small></button><button type="button" data-c="mute">🔇<small>Mute</small></button>
<button type="button" data-c="vol_up">🔊<small>Vol +</small></button>
<button type="button" data-c="prev">⏮<small>Prev</small></button><button type="button" data-c="play">⏯<small>Play/Pause</small></button>
<button type="button" data-c="next">⏭<small>Next</small></button>
<button type="button" data-c="bright_down">🔅<small>Dim</small></button><button type="button" data-c="lock" class="warn">🔒<small>Lock</small></button>
<button type="button" data-c="bright_up">🔆<small>Bright</small></button>
<button type="button" data-c="sleep" class="warn">💤<small>Sleep</small></button>
</div></div></div>
<div class="sheet" id="usheet"><div><h3>Send file to laptop<button type="button" data-x>✕</button></h3>
<div class="uprow"><input type="checkbox" id="uask" checked><label for="uask">Ask Jarvis about it (summarise / read the photo)</label></div>
<div class="vrow"><button type="button" id="upick">📷 Choose photo or file</button></div>
<input type="file" id="ufile" hidden><div class="crumb" id="ustat" style="margin-top:10px"></div></div></div>
<div class="sheet" id="bsheet"><div><h3>Daily brief<button type="button" data-x>✕</button></h3><div id="brieft">…</div></div></div>
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

// ── menu & alat ──
const sheet=id=>$(id).classList.add('on'),unsheet=id=>$(id).classList.remove('on');
$('hist').onclick=()=>sheet('msheet');
document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>{unsheet('msheet');const k=b.dataset.open;
 if(k==='hist'){sheet('hsheet');histLoad()}else if(k==='files'){sheet('fsheet');fopen(fcur);fauto()}
 else if(k==='screen'){sheet('ssheet');shot()}else if(k==='ctl')sheet('csheet');
 else if(k==='up')sheet('usheet');else if(k==='brief'){sheet('bsheet');brief(true)}});
// Files: layar folder laptop (baca sahaja)
const icon=n=>/\.(jpe?g|png|gif|webp|heic)$/i.test(n)?'🖼':/\.(mp4|mov|mkv|webm|avi)$/i.test(n)?'🎬':/\.(mp3|m4a|wav|flac|ogg)$/i.test(n)?'🎵':
 /\.pdf$/i.test(n)?'📕':/\.(docx?|odt)$/i.test(n)?'📘':/\.(xlsx?|csv)$/i.test(n)?'📗':/\.(pptx?)$/i.test(n)?'📙':/\.(zip|rar|7z)$/i.test(n)?'🗜':'📄';
const size=b=>b>1e9?(b/1e9).toFixed(1)+' GB':b>1e6?(b/1e6).toFixed(1)+' MB':b>1e3?Math.round(b/1e3)+' KB':b+' B';
// Files: layar folder laptop (baca sahaja). Dibaca terus dari cakera — "live".
// Semasa helaian terbuka ia dimuat semula sendiri setiap 4 s; ↻ untuk serta-merta.
let fcur='',fseen=null,fnew=new Set(),ftimer=0;
async function fopen(p,quiet){
 let r;try{r=await(await fetch('/api/files?path='+encodeURIComponent(p))).json()}catch(e){return}
 const l=$('flist');const keep=quiet&&p===fcur?l.scrollTop:0;
 if(p!==fcur){fseen=null;fnew=new Set()}fcur=p;l.textContent='';
 $('fcrumb').textContent=r.path||'Laptop';if(!r.ok){l.textContent=r.msg||'Not allowed';return}
 if(r.path){const up=document.createElement('div');up.className='frow';up.innerHTML='<i>⬆</i><div class="tx"><b>..</b></div>';
  up.onclick=()=>fopen(r.parent);l.appendChild(up)}
 const names=new Set(r.items.map(i=>i.path));
 for(const it of r.items){if(fseen&&!fseen.has(it.path))fnew.add(it.path);
  const row=document.createElement('div');row.className='frow'+(fnew.has(it.path)?' new':'');
  const i=document.createElement('i');i.textContent=it.dir?'📁':icon(it.name);const tx=document.createElement('div');tx.className='tx';
  const b=document.createElement('b');b.textContent=it.name;const sm=document.createElement('small');
  sm.textContent=it.mtime?(new Date(it.mtime*1000).toLocaleDateString([], {day:'numeric',month:'short',year:'2-digit'})+(it.dir?'':' · '+size(it.size))):'';
  tx.append(b,sm);row.append(i,tx);row.onclick=()=>it.dir?fopen(it.path):view(it);l.appendChild(row)}
 if(!fseen)fseen=names;else names.forEach(n=>fseen.add(n));   // tanda NEW untuk fail yang muncul selepas folder dibuka
 l.scrollTop=keep}
function fauto(){clearTimeout(ftimer);if(!$('fsheet').classList.contains('on')||document.hidden)return;
 ftimer=setTimeout(async()=>{if($('fsheet').classList.contains('on')&&!$('vsheet').classList.contains('on'))await fopen(fcur,true);fauto()},4000)}
$('fref').onclick=async e=>{e.stopPropagation();const b=$('fref');b.classList.remove('spin');void b.offsetWidth;b.classList.add('spin');
 await fopen(fcur,true);fauto()};
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&$('fsheet').classList.contains('on')){fopen(fcur,true);fauto()}});
let vcur=null;
async function view(it){vcur=it;const u='/api/file?path='+encodeURIComponent(it.path);$('vtitle').firstChild.textContent=it.name;
 $('vdl').href=u+'&dl=1';const v=$('vbody');v.textContent='…';sheet('vsheet');const n=it.name;
 if(/\.(jpe?g|png|gif|webp)$/i.test(n)){v.innerHTML='<img alt="">';v.firstChild.src=u}
 else if(/\.(mp4|mov|webm|m4v|mp3|m4a|wav)$/i.test(n)){v.innerHTML='<video controls playsinline></video>';v.firstChild.src=u}
 else if(/\.pdf$/i.test(n)){v.innerHTML='<div style="padding:14px;font-size:13px">PDF · '+size(it.size)+'</div>';
  const a=document.createElement('a');a.href=u;a.target='_blank';a.textContent='📕 Open PDF';
  a.style.cssText='display:block;margin:0 14px 14px;padding:11px;text-align:center;border-radius:22px;color:#fff;text-decoration:none;background:rgba(255,255,255,.1)';v.appendChild(a)}
 else{const r=await(await fetch('/api/preview?path='+encodeURIComponent(it.path))).json();
  if(r.ok&&r.kind==='text'){const pre=document.createElement('pre');pre.textContent=r.text;v.textContent='';v.appendChild(pre)}
  else v.innerHTML='<div style="padding:14px;font-size:13px">No preview for this type · '+size(it.size)+'. Download it, or open it on the laptop.</div>'}}
$('vopen').onclick=async()=>{if(!vcur)return;const r=await post('/api/open',{path:vcur.path});add(r.ok?'note':'error',r.ok?'✓ Opened on laptop: '+vcur.name:(r.msg||'failed'));unsheet('vsheet')};
// Screen
let stimer=0;function shot(){clearTimeout(stimer);if(!$('ssheet').classList.contains('on'))return;
 const im=$('simg');im.onload=()=>{stimer=setTimeout(shot,2500)};im.onerror=()=>{stimer=setTimeout(shot,5000)};im.src='/api/screen?t='+Date.now()}
$('sref').onclick=shot;
// Controls (lock/sleep perlu pengesahan di fon)
document.querySelectorAll('[data-c]').forEach(b=>b.onclick=async()=>{const a=b.dataset.c;
 if((a==='lock'||a==='sleep')&&!confirm(a==='lock'?'Lock the laptop?':'Put the laptop to sleep? Jarvis on the phone will go offline.'))return;
 if(navigator.vibrate)navigator.vibrate(15);const r=await post('/api/control',{action:a});add(r.ok?'note':'error',(r.ok?'✓ ':'')+(r.msg||a))});
// Send file
$('upick').onclick=()=>$('ufile').click();
$('ufile').onchange=async()=>{const f=$('ufile').files[0];if(!f)return;$('ustat').textContent='Uploading '+f.name+' ('+size(f.size)+')…';
 try{const r=await(await fetch('/api/upload?name='+encodeURIComponent(f.name)+'&ask='+($('uask').checked?'1':''),{method:'POST',body:f})).json();
  $('ustat').textContent=r.ok?'✓ Saved: '+r.path:'✕ '+(r.msg||'failed');if(r.ok&&$('uask').checked)setTimeout(()=>unsheet('usheet'),900)}
 catch(e){$('ustat').textContent='✕ Upload failed'}$('ufile').value='';clearTimeout(timer);timer=setTimeout(poll,500)};
// Daily brief: sekali sehari bila app dibuka, dan bila diminta
async function brief(force){try{const r=await(await fetch('/api/brief')).json();const t=(r&&r.text)||'';
 $('brieft').textContent=t||'No brief yet today.';const day=new Date().toDateString();let seen='';try{seen=localStorage.getItem('briefDay')||''}catch(e){}
 if(!force&&t&&seen!==day){add('jarvis','☀ '+t);try{localStorage.setItem('briefDay',day)}catch(e){}}}catch(e){}}
// Notifikasi Web Push
const b64u=s=>{s=s.replace(/-/g,'+').replace(/_/g,'/');const r=atob(s+'='.repeat((4-s.length%4)%4));return Uint8Array.from(r,c=>c.charCodeAt(0))};
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
$('notif').onclick=async()=>{unsheet('msheet');
 if(!('serviceWorker' in navigator)||!('PushManager' in window)){add('error','On iPhone: Safari → Share → Add to Home Screen first, then open Jarvis from the Home Screen and tap Notifications again.');return}
 const perm=await Notification.requestPermission();if(perm!=='granted'){add('error','Notifications not allowed');return}
 const k=await(await fetch('/api/push/key')).json();if(!k.ok){add('error',k.msg||'No push key');return}
 const reg=await navigator.serviceWorker.ready;let sub=await reg.pushManager.getSubscription();
 if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64u(k.key)});
 const r=await post('/api/push/sub',{sub:sub.toJSON()});add(r.ok?'note':'error',r.ok?'✓ Notifications on':'Could not enable notifications')};
brief(false);
projRefresh();
poll();
</script></body></html>"""
