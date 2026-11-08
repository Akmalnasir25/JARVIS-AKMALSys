"""Cap suara untuk "Hey Jarvis": hanya suara Tuan yang membangunkan Jarvis.

openWakeWord menyokong *custom verifier*: regresi logistik kecil di atas ciri
model hey_jarvis itu sendiri, dilatih dengan contoh frasa daripada SATU
penutur. Tiada model berat (torch) diperlukan — sklearn dan ONNX yang sedia ada.

  positif : Tuan sebut "Hey Jarvis" 6 kali (dirakam dari aliran mic Jarvis)
  negatif : suara lain menyebut frasa yang sama + ayat biasa, dijana dengan
            edge-tts (12 suara, BM dan English) — inilah yang mesti ditolak:
            TV, orang lain, video YouTube yang menyebut "Jarvis".
"""
from __future__ import annotations

import asyncio
import tempfile
import wave
from pathlib import Path

import numpy as np

RATE = 16000
NEG_VOICES = ["en-US-GuyNeural", "en-US-JennyNeural", "en-GB-RyanNeural", "en-GB-SoniaNeural",
              "en-AU-WilliamNeural", "en-IN-PrabhatNeural", "en-US-AndrewMultilingualNeural",
              "en-US-AvaMultilingualNeural", "ms-MY-OsmanNeural", "ms-MY-YasminNeural",
              "id-ID-ArdiNeural", "en-US-EmmaMultilingualNeural"]
NEG_LINES = ["Hey Jarvis", "Hey Jarvis, open Chrome", "Jarvis, what time is it",
             "Hai Jarvis, buka YouTube", "Okay so the meeting starts at nine tomorrow",
             "Jangan lupa hantar borang tu petang ni"]


def write_wav(path: Path, x: np.ndarray):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def pad(x: np.ndarray, secs=0.5) -> np.ndarray:
    z = np.zeros(int(RATE * secs), dtype=np.float32)
    return np.concatenate([z, x.astype(np.float32), z])


def make_negatives(neg_dir: Path, decode) -> int:
    """Jana klip negatif dengan edge-tts. `decode` = phone.decode_16k (mp3 -> float32 16 kHz)."""
    import edge_tts
    neg_dir.mkdir(parents=True, exist_ok=True)

    async def one(voice, line, out):
        buf = bytearray()
        async for ch in edge_tts.Communicate(line, voice).stream():
            if ch["type"] == "audio":
                buf.extend(ch["data"])
        out.write_bytes(bytes(buf))

    n = 0
    with tempfile.TemporaryDirectory() as td:
        for vi, voice in enumerate(NEG_VOICES):
            for li, line in enumerate(NEG_LINES):
                mp3 = Path(td) / f"{vi}_{li}.mp3"
                try:
                    asyncio.run(one(voice, line, mp3))
                    write_wav(neg_dir / f"tts_{vi}_{li}.wav", pad(decode(mp3)))
                    n += 1
                except Exception:
                    continue
    return n


def train(pos_files: list[Path], neg_files: list[Path], out_path: Path):
    from openwakeword.custom_verifier_model import train_custom_verifier
    out_path.parent.mkdir(parents=True, exist_ok=True)
    train_custom_verifier(
        positive_reference_clips=[str(p) for p in pos_files],
        negative_reference_clips=[str(p) for p in neg_files],
        output_path=str(out_path),
        model_name="hey_jarvis",
        wakeword_models=["hey_jarvis"],
        inference_framework="onnx",
    )
    return out_path
