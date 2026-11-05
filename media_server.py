# language: Python, file: media_server.py, target: Windows 11, Python 3.14
"""Range-capable static file server for the Jarvis stage.

SimpleHTTPRequestHandler answers every request with the whole file and no
Content-Range, so <video> cannot seek and a 2 GB mkv downloads before the first
frame. This one speaks HTTP/1.1, honours a single `Range: bytes=a-b` request with
206 Partial Content, and keeps the socket open so WebView2 can scrub.

Bind is 127.0.0.1 only, port 0 (kernel picks), token-free — the HUD is a local
process and the surface never leaves the machine. If that changes, add the token
check in `_allowed`.
"""
from __future__ import annotations

import mimetypes
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

CHUNK = 128 * 1024
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

EXTRA_TYPES = {
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
    ".srt": "text/plain; charset=utf-8",
    ".vtt": "text/vtt; charset=utf-8",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "JarvisMedia/1.0"
    protocol_version = "HTTP/1.1"

    root: Path = Path(".")

    def log_message(self, fmt, *args):
        pass  # no console spam; WebView2 reconnects constantly while seeking

    # ---------- helpers ----------
    def _resolve(self) -> Path | None:
        raw = unquote(urlparse(self.path).path)
        if raw in ("", "/"):
            return None
        # strip every form of traversal before touching the disk
        clean = os.path.normpath(raw.lstrip("/")).replace("\\", "/")
        if clean.startswith("..") or clean.startswith("/") or ":" in clean:
            return None
        target = (self.root / clean).resolve()
        try:
            target.relative_to(self.root.resolve())
        except ValueError:
            return None
        return target if target.is_file() else None

    def _ctype(self, p: Path) -> str:
        ext = p.suffix.lower()
        if ext in EXTRA_TYPES:
            return EXTRA_TYPES[ext]
        guess, _ = mimetypes.guess_type(p.name)
        return guess or "application/octet-stream"

    def _cors(self):
        # file:// origin is opaque, so the browser sends Origin: null
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Range, Accept-Ranges, Content-Length")

    def _send_range(self, path: Path, size: int):
        header = self.headers.get("Range", "").strip()
        start, end = 0, size - 1
        partial = False

        if header:
            m = RANGE_RE.match(header)
            if not m:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self._cors()
                self.end_headers()
                return
            a, b = m.group(1), m.group(2)
            if a == "" and b == "":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Length", "0")
                self._cors()
                self.end_headers()
                return
            if a == "":                       # suffix range: bytes=-500 = last 500
                start = max(0, size - int(b))
                end = size - 1
            else:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            if start > end or start >= size:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self._cors()
                self.end_headers()
                return
            partial = True

        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self.send_header("Content-Type", self._ctype(path))
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._cors()
        self.end_headers()

        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    buf = fh.read(min(CHUNK, remaining))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the player seeked away mid-chunk; that is normal, not an error

    # ---------- verbs ----------
    ui_root: Path | None = None
    ui_entry: str = "stage.html"

    def _send_file(self, target: Path, ctype: str | None = None):
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", ctype or mimetypes.guess_type(target.name)[0]
                         or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        # /stage and /stage/ are the HUD itself. It is served over http on
        # purpose: a file:// document has a null origin, and a null origin
        # is what makes the YouTube player refuse with "configuration error
        # 153" — the embed checks its referrer and gets nothing. Serving the
        # same file from 127.0.0.1 gives it a real origin without changing a
        # byte of the page, and keeps it out of any other process's reach.
        raw = unquote(urlparse(self.path).path)
        if raw in ("/", "/stage", "/stage/"):
            entry = (self.ui_root or Path(".")) / self.ui_entry
            if entry.is_file():
                self._send_file(entry, "text/html; charset=utf-8")
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if raw.startswith("/ui/") and self.ui_root:
            ui = (self.ui_root / raw[4:]).resolve()
            try:
                ui.relative_to(self.ui_root.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if ui.is_file():
                self._send_file(ui)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = self._resolve()
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_range(path, path.stat().st_size)

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()


class MediaServer:
    """Owns the socket. `base` is the URL prefix children should prepend."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        handler = type("BoundHandler", (_Handler,), {"root": self.root})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def serve_ui(self, ui_dir: str | Path, entry: str = "stage.html") -> "MediaServer":
        """Mount the HUD on the same socket so it loads from an http origin."""
        self._httpd.RequestHandlerClass.ui_root = Path(ui_dir)
        self._httpd.RequestHandlerClass.ui_entry = entry
        return self

    @property
    def stage_url(self) -> str:
        return f"{self.base}/stage"

    def start(self) -> "MediaServer":
        if self._thread is None:
            self._thread = threading.Thread(target=self._httpd.serve_forever,
                                            kwargs={"poll_interval": 0.3}, daemon=True)
            self._thread.start()
        return self

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass

    def url_for(self, name: str) -> str:
        from urllib.parse import quote
        return f"{self.base}/{quote(name)}"


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else "media"
    srv = MediaServer(root).start()
    print(f"serving {Path(root).resolve()} at {srv.base}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.stop()
