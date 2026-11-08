"""Pembantu mesyuarat: rakam mic + bunyi laptop, kemudian Gemini buat transkrip dan nota.

Dua trek, satu jam:
  · mic  — suara dalam bilik (mikrofon lalai)
  · sys  — bunyi yang keluar dari laptop (WASAPI loopback): Zoom, Meet, Teams
Kedua-duanya dirakam pada 48 kHz dan diturunkan ke 16 kHz mono, ditulis sebagai
PCM mentah (bukan WAV) supaya rakaman yang terputus masih boleh dibaca — WAV
hanya sah selepas header ditutup.

Diukur 8 Nov 2026: loopback memulangkan sifar ketika senyap (tidak tersekat),
jadi dua trek kekal sejajar dan boleh dicampur sampel demi sampel.

Selepas tamat: campur -> Opus 24 kbps (~17 MB sejam) -> Gemini. Di bawah 14 MB
dihantar terus dalam permintaan; lebih besar melalui Files API.
"""
from __future__ import annotations

import base64
import ctypes
import json
import threading
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

import numpy as np

RATE = 16000
API = "https://generativelanguage.googleapis.com"

NOTES_PROMPT = """Ini rakaman mesyuarat/kelas di Malaysia (Bahasa Melayu bercampur English).
Hasilkan dalam Bahasa Melayu, format Markdown, tepat begini:

## Ringkasan
3-6 ayat: tujuan, perkara utama yang dibincangkan.

## Keputusan
- senarai keputusan yang dibuat (tulis "Tiada keputusan jelas" jika tiada)

## Tindakan
- [Siapa] — apa — bila (tarikh/hari jika disebut)

## Perkara penting
- angka, tarikh, nama, tempat yang disebut

## Transkrip
Transkrip penuh perkataan demi perkataan. Label penutur sebagai "Penutur 1", "Penutur 2"...
(atau nama jika disebut). Letak cap masa [mm:ss] setiap kali penutur bertukar.

Jangan reka apa-apa yang tidak kedengaran. Jika audio senyap atau tiada pertuturan, tulis "Tiada pertuturan dirakam."."""


class Meeting:
    def __init__(self, out_dir: Path, log=print):
        self.out_dir = Path(out_dir)
        self.log = log
        self.on = False
        self.t0 = 0.0
        self.dir: Path | None = None
        self.err = ""
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.level = {"mic": 0.0, "sys": 0.0}

    # ── rakaman ────────────────────────────────────────────────
    def start(self):
        if self.on:
            return {"ok": False, "msg": "Mesyuarat sedang dirakam."}
        try:
            warnings.simplefilter("ignore")
            import soundcard  # noqa: F401  (import memulakan COM pada thread ini)
        except Exception as e:
            return {"ok": False, "msg": f"soundcard tiada: {e} — python -m pip install soundcard"}
        self.dir = self.out_dir / time.strftime("%Y%m%d-%H%M%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self.err = ""
        self.on = True
        self.t0 = time.time()
        self._threads = [threading.Thread(target=self._rec, args=(src,), daemon=True) for src in ("mic", "sys")]
        for t in self._threads:
            t.start()
        return {"ok": True, "dir": str(self.dir)}

    def _rec(self, src):
        import soundcard as sc
        from scipy.signal import resample_poly
        ctypes.windll.ole32.CoInitializeEx(None, 0)   # soundcard hanya mulakan COM pada thread yang import
        path = self.dir / f"{src}.pcm"
        try:
            dev = (sc.default_microphone() if src == "mic" else
                   sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True))
            with open(path, "ab") as f, dev.recorder(samplerate=48000, channels=1) as r:
                while not self._stop.is_set():
                    d = r.record(numframes=24000)                 # 0.5 s
                    x = resample_poly(d[:, 0], 1, 3)              # 48k -> 16k
                    self.level[src] = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
                    f.write((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
                    f.flush()
        except Exception as e:
            self.err = f"{src}: {e}"
            self.log(f"meeting {src} gagal: {e}")

    def stop(self):
        if not self.on:
            return {"ok": False, "msg": "Tiada mesyuarat sedang dirakam."}
        self._stop.set()
        for t in self._threads:
            t.join(3)
        self.on = False
        return {"ok": True, "secs": round(time.time() - self.t0), "dir": str(self.dir)}

    def status(self):
        return {"on": self.on, "secs": round(time.time() - self.t0) if self.on else 0,
                "mic": round(self.level["mic"], 4), "sys": round(self.level["sys"], 4), "err": self.err}

    # ── pemprosesan ────────────────────────────────────────────
    def mix(self, d: Path) -> np.ndarray:
        tracks = []
        for src in ("mic", "sys"):
            p = d / f"{src}.pcm"
            if p.exists() and p.stat().st_size:
                tracks.append(np.frombuffer(p.read_bytes(), dtype="<i2").astype(np.float32) / 32768.0)
        if not tracks:
            return np.zeros(0, dtype=np.float32)
        n = max(len(t) for t in tracks)
        out = np.zeros(n, dtype=np.float32)
        for t in tracks:
            # setiap trek dinormalkan ke paras yang sama dulu: mic bilik biasanya jauh lebih perlahan
            peak = float(np.percentile(np.abs(t), 99.5)) if len(t) else 0
            out[:len(t)] += t * (0.5 / peak if peak > 1e-4 else 0)
        return np.clip(out, -1, 1)

    @staticmethod
    def to_opus(x: np.ndarray, path: Path):
        import av
        out = av.open(str(path), "w", format="ogg")
        st = out.add_stream("libopus", rate=RATE)
        st.bit_rate = 24000
        try:
            st.layout = "mono"
        except Exception:
            pass
        pcm = (x * 32767).astype("<i2")
        for i in range(0, len(pcm), 16000):
            fr = av.AudioFrame.from_ndarray(pcm[i:i + 16000].reshape(1, -1), format="s16", layout="mono")
            fr.sample_rate = RATE
            for p in st.encode(fr):
                out.mux(p)
        for p in st.encode(None):
            out.mux(p)
        out.close()

    def _upload(self, key, data: bytes, mime: str) -> str:
        """Files API (resumable). Pulangkan file_uri bila fail ACTIVE."""
        req = urllib.request.Request(
            f"{API}/upload/v1beta/files", method="POST",
            data=json.dumps({"file": {"display_name": "jarvis-meeting"}}).encode(),
            headers={"x-goog-api-key": key, "X-Goog-Upload-Protocol": "resumable",
                     "X-Goog-Upload-Command": "start",
                     "X-Goog-Upload-Header-Content-Length": str(len(data)),
                     "X-Goog-Upload-Header-Content-Type": mime, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            up = r.headers.get("x-goog-upload-url")
        req = urllib.request.Request(up, method="POST", data=data,
                                     headers={"X-Goog-Upload-Command": "upload, finalize",
                                              "X-Goog-Upload-Offset": "0",
                                              "Content-Length": str(len(data))})
        with urllib.request.urlopen(req, timeout=600) as r:
            f = json.load(r)["file"]
        name = f["name"]
        for _ in range(60):
            if f.get("state") == "ACTIVE":
                return f["uri"]
            time.sleep(3)
            g = urllib.request.Request(f"{API}/v1beta/{name}", headers={"x-goog-api-key": key})
            with urllib.request.urlopen(g, timeout=30) as r:
                f = json.load(r)
        raise RuntimeError("Gemini tak sempat memproses fail audio")

    def notes(self, d: Path, key: str, model: str) -> str:
        """Campur, mampat, hantar ke Gemini. Pulangkan nota Markdown (juga disimpan sebagai notes.md)."""
        x = self.mix(d)
        secs = len(x) / RATE
        if secs < 3:
            raise RuntimeError("Rakaman terlalu pendek.")
        ogg = d / "meeting.ogg"
        self.to_opus(x, ogg)
        data = ogg.read_bytes()
        if len(data) < 14 * 1024 * 1024:
            part = {"inline_data": {"mime_type": "audio/ogg", "data": base64.b64encode(data).decode()}}
        else:
            part = {"file_data": {"mime_type": "audio/ogg", "file_uri": self._upload(key, data, "audio/ogg")}}
        body = {"contents": [{"parts": [{"text": NOTES_PROMPT}, part]}],
                "generationConfig": {"temperature": 0.2}}
        req = urllib.request.Request(
            f"{API}/v1beta/models/{model}:generateContent", method="POST",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=900) as r:
            out = json.load(r)
        parts = ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "\n".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if not text:
            raise RuntimeError("Gemini tak pulangkan nota.")
        head = f"# Nota mesyuarat {time.strftime('%d/%m/%Y %H:%M', time.localtime(d.stat().st_ctime))} · {int(secs // 60)} min {int(secs % 60)} s\n\n"
        (d / "notes.md").write_text(head + text, encoding="utf-8")
        return head + text
