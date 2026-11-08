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
    def __init__(self, api, secrets_path: Path, ui_dir: Path, port=8765, log=print, domain="", email=""):
        self.api = api
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
                    # melalui tunnel: Cloudflare Access mesti sudah mengesahkan e-mel Tuan
                    who = (self.headers.get("Cf-Access-Authenticated-User-Email") or "").strip().lower()
                    if not web.email or not hmac.compare_digest(who, web.email):
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
                    page = PAGE.replace("__ICON__", ico)
                    return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                if path == "/manifest.json":
                    return self._send(200, json.dumps(manifest(web.ui_dir)).encode(), "application/manifest+json")
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
                        return self._json({"ok": False, "msg": "audio terlalu besar"}, 413)
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
                return {"ok": False, "msg": "Terlalu pendek"}
            self.api.warm_whisper()
            text = (self.api._transcribe(audio, source="phone") or "").strip()
        except Exception as e:
            return {"ok": False, "msg": f"Transkripsi gagal: {e}"}
        finally:
            try:
                p.unlink()
            except Exception:
                pass
        if not text:
            return {"ok": False, "msg": "Tak dengar apa-apa"}
        r = self.say(text)
        return {"ok": True, "text": text, **{k: v for k, v in r.items() if k != "ok"}}

    # ── suapan ───────────────────────────────────────────────
    def push(self, kind, data):
        with self._lock:
            self.seq += 1
            self.feed.append({"seq": self.seq, "kind": kind, "at": int(time.time()), **data})

    def on_emit(self, kind, data):
        """Dipanggil dari Api._emit: simpan hanya yang fon perlukan."""
        data = data or {}
        if kind == "text" and data.get("text"):
            self.push("jarvis", {"text": str(data["text"])[:6000]})
        elif kind == "tool":
            self.push("tool", {"text": f"{data.get('name', '')} · {str(data.get('detail', ''))[:80]}"})
        elif kind == "done" and not data.get("ok"):
            self.push("error", {"text": str(data.get("error") or "gagal")[:200]})
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
            self.push("note", {"text": "✓ " + (done.get("label") or "Siap")})
            return {"ok": True, "handled": True}
        a._show_window()
        a._voice_emit("text", text)
        return {"ok": True, "handled": False}


_ICON_CACHE = {}


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
<html lang="ms"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Jarvis</title><link rel="manifest" href="/manifest.json" crossorigin="use-credentials">
<link rel="icon" href="__ICON__"><link rel="apple-touch-icon" href="__ICON__">
<meta name="theme-color" content="#07040f">
<style>
:root{--a:272;--b:318;--bg:#0b0618;--ink:#e6f2fa;--dim:#8fa6b4}
html[data-theme=stark]{--a:196;--b:38;--bg:#06111b}
html[data-theme=inferno]{--a:26;--b:356;--bg:#170905}
html[data-theme=mark]{--a:356;--b:44;--bg:#180408}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:radial-gradient(120% 70% at 50% 0%,hsl(var(--a) 90% 40%/.35),transparent 60%),var(--bg);
 color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:10px;padding:calc(10px + env(safe-area-inset-top)) 16px 8px}
header img{width:30px}header b{letter-spacing:.35em;font-size:15px}
header span{margin-left:auto;font-size:11px;color:var(--dim)}
.orb{width:120px;height:120px;margin:6px auto 4px;position:relative;flex:none}
.orb i{position:absolute;inset:0;border-radius:50%;border:2px solid transparent}
.orb i:nth-child(1){border-top-color:#e3121e;border-right-color:#e3121e88;animation:sp 6s linear infinite}
.orb i:nth-child(2){inset:12px;border-bottom-color:#ffc93a;border-left-color:#ffc93a88;animation:sp 4s linear infinite reverse}
.orb i:nth-child(3){inset:30px;background:radial-gradient(circle,hsl(var(--b) 100% 70%),hsl(var(--a) 100% 45%/.5) 60%,transparent 72%);border:0;animation:pu 3s ease-in-out infinite}
body.busy .orb i:nth-child(1){animation-duration:1s}body.busy .orb i:nth-child(2){animation-duration:.7s}
body.busy .orb i:nth-child(3){animation-duration:.8s}
@keyframes sp{to{transform:rotate(360deg)}}@keyframes pu{50%{transform:scale(1.12);opacity:.8}}
#st{text-align:center;font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:hsl(var(--b) 100% 72%)}
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
form button{border:0;border-radius:22px;padding:0 18px;font-size:15px;font-weight:600;color:#fff;
 background:linear-gradient(135deg,hsl(var(--a) 90% 50%),hsl(var(--b) 90% 50%))}
#stop{display:none;background:#5a1820}body.busy #stop{display:block}
#mic{background:rgba(255,255,255,.1);padding:0 15px;font-size:18px}
#mic.rec{background:#c8101e;animation:pu 1s ease-in-out infinite}
</style></head><body>
<header><img src="__ICON__" alt=""><b>J.A.R.V.I.S</b><span id="net">…</span></header>
<div class="orb"><i></i><i></i><i></i></div><div id="st">Standby</div>
<div id="log"></div>
<form id="f"><input id="q" placeholder="Arahan untuk Jarvis…" autocomplete="off" enterkeyhint="send">
<button type="button" id="mic" aria-label="Cakap">🎙</button><button type="button" id="stop">■</button><button>Hantar</button></form>
<script>
let seq=0,busy=false,timer=0,inflight=false;const log=document.getElementById('log');
const add=(kind,text)=>{const d=document.createElement('div');d.className='m '+kind;d.textContent=text;
 if(kind==='jarvis'){const b=document.createElement('button');b.textContent='🔊 Dengar';
  b.onclick=async()=>{b.disabled=true;try{const r=await(await fetch('/api/tts',{method:'POST',body:JSON.stringify({text})})).json();
  if(r.ok)new Audio(r.src).play()}finally{b.disabled=false}};d.appendChild(b)}
 log.appendChild(d);log.scrollTop=log.scrollHeight};
async function poll(){if(inflight)return;inflight=true;clearTimeout(timer);try{const r=await(await fetch('/api/state?since='+seq)).json();
 document.getElementById('net').textContent='● laptop';
 if(r.theme&&r.theme!=='asal')document.documentElement.dataset.theme=r.theme;else delete document.documentElement.dataset.theme;
 for(const e of r.events)add(e.kind,e.text);seq=r.seq;busy=r.busy;document.body.classList.toggle('busy',busy);
 document.getElementById('st').textContent=busy?'Thinking':'Standby'}
 catch(e){document.getElementById('net').textContent='○ terputus'}
 inflight=false;timer=setTimeout(poll,busy?900:2500)}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const q=document.getElementById('q');const t=q.value.trim();
 if(!t)return;q.value='';await fetch('/api/say',{method:'POST',body:JSON.stringify({text:t})});clearTimeout(timer);timer=setTimeout(poll,300)};
document.getElementById('stop').onclick=()=>fetch('/api/stop',{method:'POST'});
// mic: tekan sekali untuk mula, sekali lagi untuk hantar (perlukan HTTPS — laluan domain)
let rec=null,chunks=[];const mic=document.getElementById('mic');
mic.onclick=async()=>{
 if(rec){rec.stop();return}
 if(!navigator.mediaDevices){add('error','Mic perlukan https://');return}
 try{const st=await navigator.mediaDevices.getUserMedia({audio:true});chunks=[];
  rec=new MediaRecorder(st);rec.ondataavailable=e=>chunks.push(e.data);
  rec.onstop=async()=>{st.getTracks().forEach(t=>t.stop());mic.classList.remove('rec');rec=null;
   add('note','◆ memproses suara…');
   const r=await(await fetch('/api/voice',{method:'POST',body:new Blob(chunks)})).json();
   if(!r.ok)add('error',r.msg||'gagal');clearTimeout(timer);timer=setTimeout(poll,300)};
  rec.start();mic.classList.add('rec')}catch(e){add('error','Mic: '+e.message)}};
poll();
</script></body></html>"""
