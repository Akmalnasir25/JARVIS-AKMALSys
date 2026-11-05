"""Telegram user session — read your own account, not a bot's inbox.

Why this exists separate from Telegram() in messaging.py:

  A bot only ever sees messages addressed to it, and only from the moment it
  was created. "Cari fail atau dokumen dalam Telegram aku", "analisis perbualan
  chat ni", "cari maklumat pasal X" all need the account's own history —
  every chat, every file, going back years. That is MTProto, and it needs a
  user session (StringSession), not a bot token.

Two rules this module keeps:

  1. Telethon is async. The rest of this app is threads and blocking calls.
     Every public method here is synchronous and runs the coroutine on a
     private loop held on a dedicated thread, so callers never see asyncio.
  2. It reads a lot and writes almost nothing. `send()` exists because the
     inbox needs it, but nothing else writes. A search must never mark a
     dialog as read — that is visible on the other side.

Nothing here downloads anything unless asked, and nothing is cached to disk
beyond the session string.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path

try:
    from telethon import TelegramClient, functions, types
    from telethon.sessions import StringSession
    from telethon.tl.types import (
        InputMessagesFilterDocument, InputMessagesFilterPhotos,
        InputMessagesFilterMusic, InputMessagesFilterUrl,
        InputMessagesFilterVideo, InputMessagesFilterContacts,
    )
    HAVE_TELETHON = True
except Exception:                                   # pragma: no cover
    HAVE_TELETHON = False


# what a file-search can be narrowed to, and the Telethon filter for each
FILTERS = {
    "document": InputMessagesFilterDocument if HAVE_TELETHON else None,
    "photo":    InputMessagesFilterPhotos if HAVE_TELETHON else None,
    "video":    InputMessagesFilterVideo if HAVE_TELETHON else None,
    "audio":    InputMessagesFilterMusic if HAVE_TELETHON else None,
    "link":     InputMessagesFilterUrl if HAVE_TELETHON else None,
    "contact":  InputMessagesFilterContacts if HAVE_TELETHON else None,
}


def _ext(name: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]{1,6})$", name or "")
    return m.group(1).lower() if m else ""


def _can_write(v):
    """Can this account post here, without the send failing server-side?

    Written against the live account, after the first version got it exactly
    backwards. The trap is `default_banned_rights`: `send_messages=False`
    there does NOT mean sending is banned — it means sending is NOT banned by
    default, i.e. ordinary members may post. Reading it as a restriction
    marked 57 of 62 groups read-only. It is ignored here entirely, because it
    describes what happens to *new joiners*, not to this account now.

    What actually decides:

      · `banned_rights.send_messages` — a restriction applied to THIS account
      · a broadcast channel — only admins with post_messages may post
      · kicked / left / deactivated — no channel to post into
    """
    if v is None:
        return False
    if getattr(v, "deactivated", False) or getattr(v, "kicked", False):
        return False
    if getattr(v, "left", False):
        return False

    br = getattr(v, "banned_rights", None)
    if br is not None and getattr(br, "send_messages", False):
        return False                      # this account is muted in the chat

    if getattr(v, "broadcast", False):
        # channels: post_messages is the right that matters, and it lives on
        # admin_rights. No admin rights means ordinary subscriber.
        ar = getattr(v, "admin_rights", None)
        return bool(ar is not None and getattr(ar, "post_messages", False))

    return True


def _r(v):
    """Telethon chat -> {id, name, type, canWrite}. Kept tiny; it crosses a
    thread boundary, so it stays plain data."""
    if v is None:
        return {"id": 0, "name": "?", "type": "?", "canWrite": False}
    kind = "user"
    if getattr(v, "title", None):
        if getattr(v, "megagroup", False):
            kind = "group"
        elif getattr(v, "broadcast", False):
            kind = "channel"       # broadcast: read-only unless admin
        else:
            kind = "group"
    elif getattr(v, "first_name", None) or getattr(v, "last_name", None):
        kind = "user"
    name = (getattr(v, "title", None)
            or " ".join(x for x in (getattr(v, "first_name", ""),
                                    getattr(v, "last_name", "")) if x)
            or getattr(v, "username", "")
            or str(getattr(v, "id", "?")))
    return {"id": int(getattr(v, "id", 0) or 0), "name": name, "type": kind,
            "canWrite": _can_write(v),
            "members": int(getattr(v, "participants_count", 0) or 0)}


# Words that carry no signal when counting what a chat is about. Both languages,
# because Manuel's groups mix them in the same sentence — "ok semua, esok kita
# submit the form" is one message, not two languages.
_STOP = set("""
yang dan di ke dari untuk pada dengan itu ini adalah tidak tak ada juga akan sudah
telah dalam atau kalau tapi lah kah nya aku saya kau awak dia kami kita mereka kamu
je jer lah pun dah takdex ni tu ni la
the a an and or of to in for on with is are was were be been being it this that
these those i you he she we they me my your our their them not no yes but if so do
does did have has had will would can could should about at by from as into than then
https http www com share post video watch amp utm fbclid
there here what when who how why all any some more most other such only own same
just also very too well now new get got make made like one two
""".split())

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


class TgAccount:
    """A logged-in Telegram account, driven synchronously from a thread."""

    def __init__(self, api_id, api_hash, session_string="", on_message=None):
        self.api_id = int(api_id or 0)
        self.api_hash = (api_hash or "").strip()
        self.session_string = session_string or ""
        self.on_message = on_message
        self.me = {}
        self._loop = None
        self._thread = None
        self._client = None
        self._ready = threading.Event()
        self._err = ""
        self._started_at = 0

    # ── lifecycle ────────────────────────────────────────────
    def start(self, wait=30):
        """Connect and verify the session. Raises if the session is dead."""
        if not HAVE_TELETHON:
            raise RuntimeError("telethon tiada — python -m pip install telethon")
        if not (self.api_id and self.api_hash):
            raise ValueError("api_id / api_hash kosong (my.telegram.org).")
        if not self.session_string:
            raise ValueError("session_string kosong — login dulu sekali.")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="tg-account", daemon=True)
        self._thread.start()
        if not self._ready.wait(wait):
            raise RuntimeError("Telegram tidak jawab dalam %ds." % wait)
        if self._err:
            raise RuntimeError(self._err)
        return self

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot())
            self._loop.run_forever()
        except Exception as e:
            self._err = f"{type(e).__name__}: {e}"
            self._ready.set()

    async def _boot(self):
        try:
            self._client = TelegramClient(StringSession(self.session_string),
                                          self.api_id, self.api_hash,
                                          device_model="Jarvis Stage",
                                          system_version="Windows 11",
                                          app_version="1.1")
            await self._client.connect()
            if not await self._client.is_user_authorized():
                self._err = "Session tidak sah — login semula."
                self._ready.set()
                return
            me = await self._client.get_me()
            self.me = {"id": me.id, "name": " ".join(
                x for x in (me.first_name, me.last_name) if x),
                "username": me.username or "", "phone": me.phone or ""}
            self._started_at = int(time.time())
            self._ready.set()
        except Exception as e:
            self._err = f"{type(e).__name__}: {e}"
            self._ready.set()

    def stop(self):
        if self._loop and self._client:
            try:
                asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop)
            except Exception:
                pass

    def status(self):
        return {"net": "tguser", "up": bool(self.me) and not self._err,
                "who": self.me.get("username") or self.me.get("name", ""),
                "phone": self.me.get("phone", ""),
                "err": self._err, "since": self._started_at}

    # ── the one bridge between sync callers and the async client ──
    def call(self, coro, timeout=90):
        if not self._loop or not self._client:
            raise RuntimeError("Telegram belum mula.")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    # ── reads ────────────────────────────────────────────────
    def dialogs(self, limit=60):
        async def go():
            out = []
            async for d in self._client.iter_dialogs(limit=limit):
                if not d.is_user and not d.is_group and not d.is_channel:
                    continue
                m = d.message
                out.append({
                    **_r(d.entity), "unread": d.unread_count or 0,
                    "last": (m.message or "" if m else "")[:110],
                    "at": int(m.date.timestamp()) if (m and m.date) else 0,
                })
            return out
        return self.call(go())

    def thread(self, dialog_id, limit=40, until_id=None):
        """Last N messages of one chat. Read-only by construction — the client
        does not mark anything read here, which matters: opening a thread in
        the HUD must not show as 'read' on the phone.

        `until_id` pages backwards: pass the smallest id you already hold and
        the server returns what came before it. Page size stays small so the
        first paint is quick; depth is a button, not a wait.
        """
        async def go():
            ent = await self._client.get_entity(int(dialog_id))
            msgs = []
            async for m in self._client.iter_messages(
                    ent, limit=limit,
                    offset_id=int(until_id) if until_id else 0):
                f = getattr(m, "file", None)
                msgs.append({
                    "id": m.id, "at": int(m.date.timestamp()) if m.date else 0,
                    "out": bool(m.out), "text": (m.message or ""),
                    "kind": ("media" if f else "text"),
                    "file": ({"name": (getattr(f, "name", None) or ""),
                              "size": int(getattr(f, "size", 0) or 0),
                              "ext": _ext(getattr(f, "name", "") or "")} if f else None),
                })
            msgs.reverse()
            return {"chat": _r(ent), "msgs": msgs,
                    # the pane needs to know whether asking for more is worth it
                    "oldest": msgs[0]["id"] if msgs else 0,
                    "more": len(msgs) >= int(limit)}
        return self.call(go())

    # ── search: the thing a bot cannot do ───────────────────
    def search(self, query="", kind="", limit=40, dialog_id=None, days=None):
        """Search across the account.

        `search` and `filter` are both accepted by TelegramClient.iter_messages
        and both are passed through, so kind+query is one request rather than
        two. What is NOT guaranteed is that the server narrows by both: the
        filter describes the media type, the query the text, and nothing in the
        API promises they intersect. So the extension check below stays as a
        free local narrowing on top — it can only remove rows, never add one.

        `days` bounds it to a recent window; without it, a common word over a
        decade of history will return thousands of rows.
        """
        filt = FILTERS.get(kind) if kind else None
        if kind and filt is None and kind not in ("", "any"):
            raise ValueError(f"jenis tidak dikenali: {kind}")

        async def go():
            since = None
            if days:
                since = time.time() - int(days) * 86400
            out = []
            ent = None
            if dialog_id:
                ent = await self._client.get_entity(int(dialog_id))
            # room to spare when a local extension filter will run after,
            # because narrowing 40 rows down to 2 is a wasted request
            want_kind = kind and kind not in ("", "any")
            cap = limit * 4 if (want_kind and query) else limit
            it = self._client.iter_messages(
                ent, limit=cap,
                search=query or None,
                filter=(filt if want_kind else None),
            )
            async for m in it:
                if since and m.date and m.date.timestamp() < since:
                    continue
                f = getattr(m, "file", None)
                fname = (getattr(f, "name", None) or "") if f else ""
                if want_kind and query:
                    # extension-level narrowing when both were given
                    want = {"document": ("pdf", "doc", "docx", "xls", "xlsx", "ppt",
                                         "pptx", "txt", "csv", "zip", "rar", "apk"),
                            "photo": ("jpg", "jpeg", "png", "webp", "gif", "heic"),
                            "video": ("mp4", "mkv", "mov", "avi", "webm"),
                            "audio": ("mp3", "ogg", "wav", "flac", "m4a")}.get(kind, ())
                    if want and _ext(fname) not in want:
                        continue
                chat = None
                try:
                    chat = _r(await m.get_chat())
                except Exception:
                    pass
                out.append({
                    "id": m.id, "at": int(m.date.timestamp()) if m.date else 0,
                    "text": (m.message or "")[:600],
                    "chat": chat,
                    "file": ({"name": fname, "size": int(getattr(f, "size", 0) or 0),
                              "ext": _ext(fname)} if f else None),
                })
                if len(out) >= limit:
                    break
            return out
        return self.call(go())

    def files(self, query="", kind="document", limit=40, dialog_id=None):
        return self.search(query=query, kind=kind, limit=limit, dialog_id=dialog_id)

    def digest(self, dialog_id, limit=None, days=None, per_sender=6):
        """Everything needed to summarise a conversation, in one pass.

        A model cannot read 2,000 raw messages: at ~120 chars each that is 60k
        tokens of "ok", "haha" and forwarded links. So this does the reading
        that a human does before telling you what a group is talking about —
        it counts, it ranks, and it keeps the lines that carry the argument.

        What comes back, per chat:

          volume    messages mined, span of time, msgs/day, peak day
          people    top senders by count, with their share of the chat
          topics    the words that actually recur, stopwords stripped
          files     what was dropped in, by type and name
          links     distinct domains, deduped
          busiest   the three heaviest days, by count
          samples   the longest messages — the ones with reasoning in them

        `days` bounds it to a window; without it the whole `limit` is mined.
        Reading never marks anything read, same as `thread()`.
        """
        cap = int(limit or 800)

        async def go():
            ent = await self._client.get_entity(int(dialog_id))
            since = (time.time() - int(days) * 86400) if days else None

            n = 0
            first_ts = last_ts = 0
            by_sender = {}
            by_day = {}
            words = {}
            files, links = [], {}
            scored = []           # (length, ts, who, text) for the longest lines
            total_len = 0
            mine = 0              # how many are Sir's own

            async for m in self._client.iter_messages(ent, limit=cap):
                ts = int(m.date.timestamp()) if m.date else 0
                if since and ts and ts < since:
                    if ts and since and ts < since - 86400:
                        break      # walked past the window; older is worse
                    continue
                n += 1
                if ts:
                    first_ts = min(first_ts or ts, ts)
                    last_ts = max(last_ts, ts)
                    day = time.strftime("%Y-%m-%d", time.localtime(ts))
                    by_day[day] = by_day.get(day, 0) + 1
                if m.out:
                    mine += 1

                # sender — a forwarded message still names who said it here,
                # because what matters is who is talking in THIS chat
                who = "Sir" if m.out else ""
                if not who:
                    try:
                        s = m.sender
                        if s is not None:
                            who = (getattr(s, "title", None)
                                   or " ".join(x for x in (getattr(s, "first_name", ""),
                                                           getattr(s, "last_name", "")) if x)
                                   or getattr(s, "username", "")
                                   or "?")
                    except Exception:
                        who = ""
                who = who or "(tiada nama)"
                by_sender[who] = by_sender.get(who, 0) + 1

                text = (m.message or "").strip()
                total_len += len(text)

                f = getattr(m, "file", None)
                if f is not None:
                    nm = getattr(f, "name", None) or ""
                    files.append({"name": nm or "(gambar/audio)",
                                  "ext": _ext(nm),
                                  "size": int(getattr(f, "size", 0) or 0),
                                  "by": who, "at": ts})
                for u in _URL_RE.findall(text):
                    try:
                        host = u.split("//", 1)[1].split("/", 1)[0].lower()
                    except IndexError:
                        host = u.lower()
                    host = host.lstrip("www.")
                    links[host] = links.get(host, 0) + 1

                if text:
                    # a URL's scheme and path are not topics. Stripped before
                    # tokenising, otherwise "https" ranks above every real word.
                    prose = _URL_RE.sub(" ", text)
                    for w in re.findall(r"[0-9A-Za-zÀ-ɏ']{4,}", prose):
                        lw = w.lower().strip("'")
                        if len(lw) < 4 or lw in _STOP or lw.isdigit():
                            continue
                        words[lw] = words.get(lw, 0) + 1
                    if len(text) >= 60:
                        scored.append((len(text), ts, who, text[:400]))

            scored.sort(key=lambda r: (-r[0], -r[1]))
            span_days = max(1, round((last_ts - first_ts) / 86400)) if first_ts else 0
            # Telegram's own service accounts ("Deleted Account", "Remove
            # Deleted Accounts", "Telegram") are large by count but are not
            # people, and letting them take a slot at the top of the sender
            # list misrepresents who is actually talking. They are folded into
            # one row at the end instead of being dropped — the count is real.
            def _synthetic(nm):
                low = nm.lower()
                return ("deleted" in low or low in ("telegram", "anonymous")
                        or nm.strip() in (".", "?", "-", "(tiada nama)"))

            humans = {k: v for k, v in by_sender.items() if not _synthetic(k)}
            bots = {k: v for k, v in by_sender.items() if _synthetic(k)}
            top_people = sorted(humans.items(), key=lambda kv: -kv[1])[:per_sender]
            if bots:
                top_people.append(("(akaun automatik/deleted)", sum(bots.values())))
            top_days = sorted(by_day.items(), key=lambda kv: -kv[1])[:3]
            top_words = sorted(words.items(), key=lambda kv: -kv[1])[:28]

            # a message count with no context is a number; a share is a fact
            people = [{"name": k, "n": v,
                       "pct": round(100.0 * v / n, 1) if n else 0.0,
                       "synthetic": k.startswith("(akaun automatik")}
                      for k, v in top_people]

            by_ext = {}
            for fe in files:
                key = fe["ext"] or "media"
                by_ext.setdefault(key, [0, 0])
                by_ext[key][0] += 1
                by_ext[key][1] += fe["size"]

            return {
                "chat": _r(ent),
                "volume": {
                    "msgs": n, "limit": cap,
                    "from_ts": first_ts, "to_ts": last_ts,
                    "span_days": span_days,
                    "per_day": round(n / span_days, 1) if span_days else float(n),
                    "avg_chars": round(total_len / n) if n else 0,
                    "mine": mine, "others": n - mine,
                    "truncated": n >= cap,
                },
                "people": people,
                "total_senders": len(by_sender),
                "topics": [{"w": k, "n": v} for k, v in top_words],
                "files": files[:40],
                "file_types": [{"ext": k, "n": v[0], "bytes": v[1]}
                               for k, v in sorted(by_ext.items(), key=lambda kv: -kv[1][0])],
                "links": [{"host": k, "n": v}
                          for k, v in sorted(links.items(), key=lambda kv: -kv[1])[:12]],
                "busiest": [{"day": k, "n": v} for k, v in top_days],
                "samples": [{"at": ts, "by": w, "chars": ln, "text": t}
                            for ln, ts, w, t in scored[:12]],
            }
        return self.call(go(), timeout=180)

    def contacts(self, query="", limit=40):
        async def go():
            res = await self._client(functions.contacts.SearchRequest(
                q=query or "", limit=limit))
            return [_r(u) for u in (res.users or [])]
        return self.call(go())

    # ── the only write ──────────────────────────────────────
    def send(self, dialog_id, text):
        async def go():
            ent = await self._client.get_entity(int(dialog_id))
            m = await self._client.send_message(ent, text)
            return {"id": m.id, "at": int(m.date.timestamp()) if m.date else int(time.time())}
        return self.call(go())

    # ── live tail (optional) ────────────────────────────────
    def listen(self):
        """Push new incoming messages to on_message. Not started by default —
        the HUD's inbox works from the dialog list, and a tail on every chat
        is a lot of wakeups for a laptop."""
        async def go():
            @self._client.on(__import__("telethon").events.NewMessage(incoming=True))
            async def _h(ev):
                if not self.on_message:
                    return
                try:
                    ch = await ev.get_chat()
                    self.on_message({
                        "net": "tguser", "chat": _r(ch),
                        "text": (ev.raw_text or "")[:4000],
                        "at": int(ev.message.date.timestamp()) if ev.message.date else 0,
                        "id": ev.message.id,
                    })
                except Exception:
                    pass
            await self._client.run_until_disconnected()
        return threading.Thread(target=lambda: self.call(go(), timeout=10**9),
                                daemon=True).start()


def login(api_id, api_hash, phone, code_getter, password_getter=None, session_path=None):
    """One-time interactive login that returns a StringSession.

    `code_getter` and `password_getter` are callables so the caller decides how
    to ask — terminal here, HUD later. Runs its own loop because at this point
    there is no client yet to own one.
    """
    if not HAVE_TELETHON:
        raise RuntimeError("telethon tiada — python -m pip install telethon")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def go():
        client = TelegramClient(StringSession(), int(api_id), api_hash.strip(),
                                device_model="Jarvis Stage",
                                system_version="Windows 11", app_version="1.1")
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            try:
                await client.sign_in(phone, code=code_getter())
            except Exception as e:
                if "password" in str(e).lower() or type(e).__name__ == "SessionPasswordNeededError":
                    await client.sign_in(password=(password_getter or (lambda: ""))())
                else:
                    raise
        me = await client.get_me()
        ss = client.session.save()
        await client.disconnect()
        return ss, {"id": me.id, "name": " ".join(x for x in (me.first_name, me.last_name) if x),
                    "username": me.username or "", "phone": me.phone or ""}

    try:
        ss, me = loop.run_until_complete(go())
    finally:
        loop.close()
    if session_path:
        Path(session_path).write_text(ss, encoding="utf-8")
    return ss, me
