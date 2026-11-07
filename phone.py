"""Cakap pada Jarvis dari fon, jawapan keluar di laptop.

Fon cuma alat kawalan jauh. Mesej (taip atau voice note) dari bot Telegram
masuk ke jalan yang sama dengan mic laptop — `onVoice('text')` — jadi apa yang
berlaku sesudahnya (bubble, AUTO, dashboard, media, suara) sama persis macam
Tuan bercakap di depan laptop. Fon hanya dapat pengakuan pendek.

Kunci: bot terbuka kepada sesiapa yang jumpa namanya, dan Jarvis boleh kawal
laptop. Jadi hanya SATU chat id yang didengar — `telegram_owner_id` dalam
secrets.json. Sebelum ada pemilik, HUD papar kod 6 digit; chat yang hantar kod
itu jadi pemilik. Chat lain diabaikan senyap (tiada balasan, supaya bot tak
mengaku wujud kepada orang asing).

Pemandu bot (long polling, muat turun fail) ialah messaging.Telegram — fail ni
tak sentuh rangkaian sendiri kecuali melalui ia.
"""
from __future__ import annotations

import json
import secrets as _rand
import threading
import time
from pathlib import Path

import messaging


class PhoneLink:
    TURN_TIMEOUT = 180      # giliran yang tak pernah "done" (UI sibuk) dilepaskan selepas ni

    def __init__(self, api, secrets_path: Path, runtime: Path, log=print):
        self.api = api
        self.secrets_path = secrets_path
        self.runtime = runtime
        self.log = log
        self.bot = None
        self.pair_code = ""
        self._turn = None           # {"chat", "at"} — giliran dari fon yang menunggu "done"
        self._tries = {}            # chat -> cubaan kod salah; 5 kali = diabaikan sampai restart
        self._lock = threading.Lock()

    # ---- secrets --------------------------------------------
    def _sec(self):
        try:
            return json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_owner(self, chat_id):
        s = self._sec()
        s["telegram_owner_id"] = str(chat_id)
        self.secrets_path.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

    def owner(self):
        return str(self._sec().get("telegram_owner_id") or "").strip()

    # ---- lifecycle ------------------------------------------
    def start(self):
        token = str(self._sec().get("telegram_bot_token") or "").strip()
        if not token:
            return {"ok": False, "msg": "Tiada telegram_bot_token dalam secrets.json."}
        inbox = messaging.Inbox(self.runtime / "phone_inbox.json")
        try:
            self.bot = messaging.Telegram(token, inbox, on_message=self._inbound, poll=500, idle=25).start()
        except Exception as e:
            self.bot = None
            return {"ok": False, "msg": f"Bot gagal mula: {e}"}
        who = (self.bot.me or {}).get("username", "")
        if not self.owner():
            self.pair_code = f"{_rand.randbelow(10 ** 6):06d}"
            self.api._emit("note", {"text": f"📱 Fon belum dipasangkan. Hantar kod {self.pair_code} "
                                            f"kepada @{who} di Telegram."})
        self.log(f"phone link up @{who} owner={'set' if self.owner() else 'none'}")
        return {"ok": True, "bot": who, "paired": bool(self.owner())}

    def status(self):
        st = self.bot.status() if self.bot else {"up": False, "who": "", "err": "off"}
        return {**st, "paired": bool(self.owner()), "code": "" if self.owner() else self.pair_code}

    def _reply(self, chat, text):
        try:
            self.bot.send(chat, text)
        except Exception as e:
            self.log(f"phone reply gagal: {e}")

    # ---- masuk ----------------------------------------------
    def _inbound(self, msg):
        # Thread polling: jangan block. Transkripsi voice note boleh ambil 10 s.
        threading.Thread(target=self._handle, args=(msg,), daemon=True).start()

    def _handle(self, msg):
        chat = str(msg.get("chat", ""))
        text = (msg.get("text") or "").strip()
        owner = self.owner()

        if not owner:
            if self._tries.get(chat, 0) >= 5:
                return                                 # meneka kod: berhenti layan chat ni
            if self.pair_code and text != self.pair_code:
                self._tries[chat] = self._tries.get(chat, 0) + 1
            if self.pair_code and text == self.pair_code:
                self._save_owner(chat)
                self.pair_code = ""
                self._reply(chat, "✓ Fon ni dah dipasangkan dengan Jarvis. Cakap atau taip apa-apa — "
                                  "jawapan keluar di laptop.")
                self.api._emit("note", {"text": f"📱 Fon dipasangkan ({msg.get('name') or chat})."})
            return                                     # orang asing / kod salah: senyap
        if chat != owner:
            return

        if text in ("/start", "/help"):
            self._reply(chat, "Taip arahan atau hantar voice note. Jawapan dipapar di laptop.\n"
                              "/status — keadaan laptop")
            return
        if text == "/status":
            try:
                import psutil   # terus, bukan Api.get_stats(): itu mengubah kiraan kelajuan rangkaian HUD
                bat = psutil.sensors_battery()
                self._reply(chat, f"CPU {psutil.cpu_percent(interval=0.3):.0f}% · "
                                  f"RAM {psutil.virtual_memory().percent:.0f}% · "
                                  f"bateri {'?' if bat is None else round(bat.percent)}%"
                                  f"{' (cas)' if bat and bat.power_plugged else ''}")
            except Exception as e:
                self._reply(chat, f"Status gagal: {e}")
            return

        if msg.get("kind") == "voice":
            fid = (msg.get("meta") or {}).get("file_id")
            if not fid:
                return
            self._reply(chat, "🎙 Dengar…")
            try:
                text = self._transcribe_note(fid)
            except Exception as e:
                self._reply(chat, f"Voice note tak dapat dibaca: {e}")
                return
            if not text:
                self._reply(chat, "Tak dengar apa-apa dalam voice note tu.")
                return
        elif msg.get("kind") != "text" or not text:
            self._reply(chat, "Buat masa ni saya terima teks dan voice note sahaja.")
            return

        self.run(chat, text)

    def run(self, chat, text):
        """Hantar satu arahan ke laptop. Kawalan pantas (volume, slide) jalan terus tanpa AI."""
        done = {}
        try:
            done = self.api.quick_control(text, allow_open=True) or {}
        except Exception:
            done = {}
        if done.get("handled"):
            self.api._voice_emit("control", {"text": text, "label": done.get("label", "")})
            self._reply(chat, f"✓ {done.get('label') or 'Siap'}")
            return
        with self._lock:
            self._turn = {"chat": chat, "at": time.time()}
        self.api._show_window()
        self.api._voice_emit("text", text)
        self._reply(chat, f"🖥 «{text[:80]}» — di laptop sekarang.")

    def turn_done(self, data):
        """Dipanggil dari Api._emit bila satu giliran tamat."""
        with self._lock:
            t, self._turn = self._turn, None
        if not t or time.time() - t["at"] > self.TURN_TIMEOUT:
            return
        data = data or {}
        if data.get("ok"):
            self._reply(t["chat"], f"✓ Siap ({data.get('secs', '?')} s) — tengok skrin laptop.")
        else:
            self._reply(t["chat"], f"✕ {str(data.get('error') or 'gagal')[:200]}")

    # ---- voice note -----------------------------------------
    def _transcribe_note(self, file_id):
        dest = self.runtime / "phone_voice" / f"{int(time.time() * 1000)}.ogg"
        self.bot.voice_file(file_id, dest)
        try:
            audio = decode_16k(dest)
        finally:
            try:
                dest.unlink()
            except Exception:
                pass
        if audio.size < 1600:
            return ""
        return (self.api._transcribe(audio) or "").strip()


def decode_16k(path: Path):
    """OGG/Opus (voice note Telegram) -> float32 mono 16 kHz, guna PyAV terus.

    Bukan faster_whisper.decode_audio: ia pecah dengan av 19 di mesin ni."""
    import av
    import numpy as np
    out = []
    with av.open(str(path)) as c:
        rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in c.decode(audio=0):
            for f in rs.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0
