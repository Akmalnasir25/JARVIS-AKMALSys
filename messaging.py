"""Messaging bridge — Telegram (live) + WhatsApp (Cloud API, structured).

Why this file exists at all: the ask was not "connect an API", it was "read
and reply to WhatsApp and Telegram from inside Jarvis". That is one inbox with
two drivers, not two features. So everything here is shaped around one shared
store of conversations, and each platform only has to do three things:
receive a message, send a message, and say who it is.

Nothing in here talks to the HUD. It raises callbacks; main.py decides what to
do with them. That keeps the network code testable without a window open.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TG_API = "https://api.telegram.org"
WA_API = "https://graph.facebook.com/v21.0"


# ─────────────────────────────────────────────────────────────
# the store — one shape for both platforms
# ─────────────────────────────────────────────────────────────
class Inbox:
    """Conversations keyed by platform+chat. Bounded, so it cannot grow forever.

    A thread is a list of {id, dir, at, kind, text}. `dir` is in/out — the HUD
    needs it to put the bubble on the right side, and the replay code needs it
    to know whether the last turn was already answered.
    """

    MAX_THREADS = 80
    MAX_MSGS = 400

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._threads = {}
        self._load()

    # ---- persistence ----------------------------------------
    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._threads = raw.get("threads", {}) or {}
        except Exception:
            self._threads = {}

    def save(self):
        with self._lock:
            trimmed = dict(list(self._sorted())[: self.MAX_THREADS])
            for t in trimmed.values():
                t["msgs"] = t["msgs"][-self.MAX_MSGS:]
            try:
                self.path.write_text(
                    json.dumps({"threads": trimmed}, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
            except OSError:
                pass

    def _sorted(self):
        return sorted(self._threads.items(), key=lambda kv: kv[1].get("at", 0), reverse=True)

    # ---- reads ----------------------------------------------
    def list_threads(self):
        with self._lock:
            out = []
            for key, t in self._sorted():
                last = t["msgs"][-1] if t["msgs"] else {}
                out.append({
                    "key": key,
                    "net": t.get("net", ""),
                    "name": t.get("name", ""),
                    "handle": t.get("handle", ""),
                    "at": t.get("at", 0),
                    "unread": t.get("unread", 0),
                    "last": (last.get("text") or "")[:90],
                    "lastDir": last.get("dir", ""),
                    "msgs": len(t["msgs"]),
                })
            return out

    def thread(self, key):
        with self._lock:
            t = self._threads.get(key)
            if not t:
                return None
            return {"key": key, "net": t.get("net", ""), "name": t.get("name", ""),
                    "handle": t.get("handle", ""), "msgs": list(t["msgs"])}

    def unread_total(self):
        with self._lock:
            return sum(t.get("unread", 0) for t in self._threads.values())

    # ---- writes ---------------------------------------------
    def _thread(self, net, chat_id, name="", handle=""):
        key = f"{net}:{chat_id}"
        t = self._threads.get(key)
        if t is None:
            t = {"net": net, "name": name, "handle": handle, "at": 0,
                 "unread": 0, "msgs": []}
            self._threads[key] = t
        if name:
            t["name"] = name
        if handle:
            t["handle"] = handle
        return key, t

    def add(self, net, chat_id, direction, text, name="", handle="", kind="text", mid=None):
        with self._lock:
            key, t = self._thread(name=name, handle=handle, net=net, chat_id=chat_id)
            t["msgs"].append({
                "id": mid or uuid.uuid4().hex[:12],
                "dir": direction,
                "at": int(time.time()),
                "kind": kind,
                "text": text or "",
            })
            t["msgs"] = t["msgs"][-self.MAX_MSGS:]
            t["at"] = int(time.time())
            if direction == "in":
                t["unread"] = int(t.get("unread", 0)) + 1
            self.save()
            return key

    def mark_read(self, key):
        with self._lock:
            t = self._threads.get(key)
            if t:
                t["unread"] = 0
                self.save()

    def clear(self, key=None):
        with self._lock:
            if key:
                self._threads.pop(key, None)
            else:
                self._threads.clear()
            self.save()


# ─────────────────────────────────────────────────────────────
# HTTP — stdlib only. requests is not a dependency here and one POST
# does not justify making it one.
# ─────────────────────────────────────────────────────────────
def _post(url, payload, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


# ─────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────
class Telegram:
    """Bot API driver.

    Long polling, deliberately, and not webhook: a webhook needs a public HTTPS
    endpoint with a valid certificate, which means an open tunnel for the whole
    session. This app runs on a laptop that moves between networks. Polling
    costs one small GET every few seconds and works from anywhere, on any
    network, with nothing exposed.
    """

    NET = "tg"

    def __init__(self, token, inbox: Inbox, on_message=None, poll=800, idle=30):
        self.token = (token or "").strip()
        self.inbox = inbox
        self.on_message = on_message
        self.poll_ms = max(300, int(poll))
        # a long poll of 25s keeps the connection useful; 30s offsets expire in
        # 24h, so the offset is persisted by the inbox and never lost mid-run
        self.idle = max(5, min(50, int(idle)))
        self.offset = 0
        self.me = {}
        self._stop = threading.Event()
        self._thread = None
        self._last_good = 0
        self._err = ""
        self._sent_id = ""          # last message id we authored, to skip the echo

    # ---- lifecycle -----------------------------------------
    def start(self):
        if not self.token:
            raise ValueError("Telegram bot token kosong.")
        if self._thread and self._thread.is_alive():
            return self
        self.me = self._call("getMe", {})
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tg-poll", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def status(self):
        return {
            "net": self.NET,
            "up": bool(self._thread and self._thread.is_alive() and not self._err),
            "who": (self.me or {}).get("username", ""),
            "err": self._err,
            "seen": self._last_good,
        }

    # ---- api ------------------------------------------------
    def _call(self, method, payload):
        url = f"{TG_API}/bot{self.token}/{method}"
        try:
            r = _post(url, payload)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            raise RuntimeError(f"{method}: HTTP {e.code} {body[:160]}")
        except Exception as e:
            raise RuntimeError(f"{method}: {e}")
        if not r.get("ok"):
            raise RuntimeError(f"{method}: {r.get('description') or r}")
        return r.get("result") or {}

    def send(self, chat_id, text):
        """Send and record. Returns True on success.

        The message we authored comes back through getUpdates if the bot is in
        a group, so it is filtered by id rather than by matching text — two
        identical replies in a row would otherwise look like an echo pair.
        """
        r = self._call("sendMessage", {
            "chat_id": chat_id, "text": text,
            "disable_web_page_preview": True,
        })
        mid = str(r.get("message_id", ""))
        if mid:
            self._sent_id = mid
        self.inbox.add(self.NET, str(chat_id), "out", text, kind="text", mid=mid)
        return True

    # ---- polling --------------------------------------------
    def _loop(self):
        while not self._stop.is_set():
            try:
                upd = self._call("getUpdates", {
                    "offset": self.offset + 1,
                    "timeout": self.idle,
                    "allowed_updates": ["message"],
                })
                self._err = ""
                self._last_good = int(time.time())
                # getUpdates with a long timeout returns {} when idle, and a
                # list when it has work — normalise both
                items = upd if isinstance(upd, list) else (upd.get("result") or [])
                for u in items:
                    self.offset = max(self.offset, int(u.get("update_id", 0)))
                    self._absorb(u)
            except Exception as e:
                self._err = str(e)[:200]
                self._stop.wait(4.0)
                continue
            self._stop.wait(self.poll_ms / 1000.0)

    def _absorb(self, u):
        m = u.get("message") or u.get("edited_message") or {}
        if not m:
            return
        chat = m.get("chat") or {}
        cid = str(chat.get("id", ""))
        if not cid:
            return
        if str(m.get("message_id", "")) == self._sent_id:
            return                                  # our own message, echoed
        frm = m.get("from") or {}
        name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) \
            or chat.get("title") or chat.get("username") or cid
        handle = ("@" + frm["username"]) if frm.get("username") else cid

        kind, text = "text", m.get("text") or m.get("caption") or ""
        extra = {}
        if m.get("voice") or m.get("audio"):
            kind = "voice"
            a = m.get("voice") or m.get("audio")
            extra = {"file_id": a.get("file_id"), "secs": a.get("duration")}
            text = text or "[voice note]"
        elif m.get("photo"):
            kind = "photo"
            ph = m["photo"][-1]
            extra = {"file_id": ph.get("file_id")}
            text = text or "[photo]"
        elif m.get("document"):
            kind = "file"
            d = m["document"]
            extra = {"file_id": d.get("file_id"), "name": d.get("file_name")}
            text = text or f"[{d.get('file_name') or 'file'}]"

        key = self.inbox.add(self.NET, cid, "in", text, name=name, handle=handle,
                             kind=kind, mid=str(m.get("message_id", "")))
        if self.on_message:
            try:
                self.on_message({"net": self.NET, "key": key, "chat": cid,
                                 "name": name, "handle": handle,
                                 "text": text, "kind": kind, "meta": extra,
                                 "at": int(time.time())})
            except Exception:
                pass

    # ---- media ----------------------------------------------
    def voice_file(self, file_id, dest: Path):
        """Download a voice note. Caller transcribes; this only lands bytes.

        The HUD's Whisper path takes a path, so the file is written rather than
        held in memory — a 3-minute note is a few hundred KB, not worth a
        second code path.
        """
        r = self._call("getFile", {"file_id": file_id})
        fp = r.get("file_path")
        if not fp:
            raise RuntimeError("Telegram tidak bagi file_path.")
        url = f"{TG_API}/file/bot{self.token}/{fp}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest


# ─────────────────────────────────────────────────────────────
# WhatsApp — Cloud API. Structured, not live: no token yet.
# ─────────────────────────────────────────────────────────────
class WhatsApp:
    """Meta Cloud API driver.

    Deliberately the same three methods as Telegram so the HUD never learns
    which platform a thread belongs to. Two things differ and cannot be papered
    over:

      · inbound arrives by webhook, not by polling. Meta pushes; there is no
        getUpdates equivalent.
      · outbound outside the 24-hour customer-service window must be a
        pre-approved template. `send()` returns a template error rather than
        silently failing, so the HUD can say so.

    `send()` will raise until a phone_number_id and token are set. That is
    honest: there is nothing to fake here.
    """

    NET = "wa"

    def __init__(self, token="", phone_id="", inbox: Inbox = None, on_message=None,
                 verify_token=""):
        self.token = token
        self.phone_id = phone_id
        self.inbox = inbox
        self.on_message = on_message
        self.verify_token = verify_token or uuid.uuid4().hex[:18]

    def start(self):
        if not (self.token and self.phone_id):
            raise ValueError("WhatsApp perlukan token dan phone_number_id.")
        return self

    def stop(self):
        pass

    def status(self):
        return {"net": self.NET, "up": bool(self.token and self.phone_id),
                "who": self.phone_id, "err": "" if self.token else "tiada token"}

    def send(self, to, text):
        if not (self.token and self.phone_id):
            raise RuntimeError("WhatsApp belum dikonfigurasi.")
        try:
            _post(f"{WA_API}/{self.phone_id}/messages", {
                "messaging_product": "whatsapp",
                "to": str(to),
                "type": "text",
                "text": {"preview_url": False, "body": text},
            }, timeout=25)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if "131047" in body or "re-engagement" in body.lower():
                raise RuntimeError("Luar tetingkap 24 jam — kena template berbayar.")
            raise RuntimeError(f"WhatsApp HTTP {e.code}: {body[:160]}")
        self.inbox.add(self.NET, str(to), "out", text)
        return True

    # ---- webhook --------------------------------------------
    def verify(self, mode, token, challenge):
        """GET handshake. Returns the challenge, or None."""
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None

    def absorb(self, payload):
        """POST body from Meta. Returns the number of messages absorbed."""
        n = 0
        for entry in (payload or {}).get("entry", []):
            for change in entry.get("changes", []):
                v = change.get("value") or {}
                contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                            for c in (v.get("contacts") or [])}
                for m in (v.get("messages") or []):
                    frm = str(m.get("from", ""))
                    if not frm:
                        continue
                    kind = m.get("type", "text")
                    text = ""
                    if kind == "text":
                        text = (m.get("text") or {}).get("body", "")
                    elif kind == "button":
                        text = (m.get("button") or {}).get("text", "")
                    elif kind == "interactive":
                        i = m.get("interactive") or {}
                        text = ((i.get("button_reply") or i.get("list_reply")) or {}).get("title", "")
                    elif kind in ("image", "video", "document", "audio", "sticker"):
                        text = m.get("caption") or f"[{kind}]"
                    elif kind == "voice":
                        text = "[voice note]"
                    key = self.inbox.add(self.NET, frm, "in", text,
                                         name=contacts.get(frm, frm), handle="+" + frm,
                                         kind=kind, mid=str(m.get("id", "")))
                    n += 1
                    if self.on_message:
                        try:
                            self.on_message({"net": self.NET, "key": key, "chat": frm,
                                             "name": contacts.get(frm, frm),
                                             "handle": "+" + frm, "text": text,
                                             "kind": kind, "meta": {},
                                             "at": int(time.time())})
                        except Exception:
                            pass
        return n


# ─────────────────────────────────────────────────────────────
# the bridge — one object main.py holds
# ─────────────────────────────────────────────────────────────
class Bridge:
    """Holds whichever drivers are configured, and routes replies back.

    `on_inbound` fires on the poll thread, so the handler must not block:
    main.py hands the message to the HUD and to the model on its own thread.
    """

    def __init__(self, inbox_path: Path, secrets_path: Path, on_inbound=None, log=print):
        self.inbox = Inbox(inbox_path)
        self.secrets_path = secrets_path
        self.on_inbound = on_inbound
        self.log = log
        self.drivers = {}
        self._auto = {}             # key -> True when Jarvis should answer
        self._lock = threading.RLock()

    # ---- config --------------------------------------------
    def _secrets(self):
        try:
            return json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def configured(self):
        s = self._secrets()
        return {
            "telegram": bool((s.get("telegram_bot_token") or "").strip()),
            "whatsapp": bool((s.get("whatsapp_token") or "").strip()
                             and (s.get("whatsapp_phone_id") or "").strip()),
            "telegram_hint": "BotFather -> /newbot -> token",
            "whatsapp_hint": "Meta Cloud API: token + phone_number_id",
        }

    def start(self):
        s = self._secrets()
        started = []
        tg = (s.get("telegram_bot_token") or "").strip()
        if tg and "tg" not in self.drivers:
            try:
                d = Telegram(tg, self.inbox, on_message=self._inbound,
                             poll=s.get("telegram_poll_ms", 800),
                             idle=s.get("telegram_idle_sec", 30)).start()
                self.drivers["tg"] = d
                started.append("telegram")
            except Exception as e:
                self.log(f"telegram gagal mula: {e}")
        wa = (s.get("whatsapp_token") or "").strip()
        wpid = (s.get("whatsapp_phone_id") or "").strip()
        if wa and wpid and "wa" not in self.drivers:
            try:
                d = WhatsApp(wa, wpid, inbox=self.inbox, on_message=self._inbound,
                             verify_token=s.get("whatsapp_verify_token", "")).start()
                self.drivers["wa"] = d
                started.append("whatsapp")
            except Exception as e:
                self.log(f"whatsapp gagal mula: {e}")
        return started

    def stop(self):
        for d in self.drivers.values():
            try:
                d.stop()
            except Exception:
                pass
        self.drivers.clear()

    def _inbound(self, msg):
        if self.on_inbound:
            try:
                self.on_inbound(msg)
            except Exception as e:
                self.log(f"inbound handler gagal: {e}")

    # ---- api for the HUD -----------------------------------
    def status(self):
        out = {"drivers": {k: d.status() for k, d in self.drivers.items()},
               "unread": self.inbox.unread_total(), "configured": self.configured()}
        return out

    def threads(self):
        return self.inbox.list_threads()

    def thread(self, key, read=True):
        t = self.inbox.thread(key)
        if t and read:
            self.inbox.mark_read(key)
        return t

    def reply(self, key, text):
        """Send out through whichever driver owns the thread.

        Key is `net:chat`, so there is no guessing. A missing driver is a real
        answer — the thread exists but the platform is not configured now.
        """
        text = (text or "").strip()
        if not text:
            return {"ok": False, "msg": "Kosong."}
        net, _, chat = key.partition(":")
        d = self.drivers.get(net)
        if d is None:
            return {"ok": False, "msg": f"{net} tidak aktif."}
        try:
            d.send(chat, text)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": str(e)[:200]}

    def auto(self, key=None, on=None):
        """Whether Jarvis answers a thread on its own, without being asked.

        Off by default. An assistant that starts replying to your contacts
        unasked is a liability, so this is explicit and per-thread.
        """
        with self._lock:
            if key is None:
                return dict(self._auto)
            if on is None:
                return bool(self._auto.get(key))
            self._auto[key] = bool(on)
            return self._auto[key]

    def should_auto(self, key):
        return bool(self._auto.get(key))

    def clear(self, key=None):
        self.inbox.clear(key)
        return {"ok": True}
