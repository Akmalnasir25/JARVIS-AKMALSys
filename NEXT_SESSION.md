# NEXT SESSION — mula di sini

> Fail ni ditulis supaya sesi baru boleh sambung tanpa perlu scroll sejarah chat.
> Baca `PLAN.md` selepas ni. Itu blueprint penuh.

**Dikemas kini:** 2026-11-04, 22:44

---

## BARU — UI v1.1 (instrument cluster, ungu)

`ui/stage.html` ditulis semula sepenuhnya. Bukan tampal cat — bahasa bentuk ditukar.

| sebelum (v1.0) | sekarang (v1.1) |
|---|---|
| 4 gauge bulat kecil | 4 meter LED menegak berpecah segmen |
| 9 tab teks melintang di atas stage | rel nombor menegak 54px di kiri stage |
| kolum kanan 372px | **292px** |
| kolum kiri 208px | 168px |
| bubble chat macam WhatsApp | log bersempadan kiri, bukan gelembung |
| cyan `#00d0ff` | **ungu `#b478ff`**, ground `#05030f` |
| angka panel ghost terpotong | numeral ghost penuh di penjuru stage |

Fail simpanan sebelum ubah: `ui/stage-v1.html` (versi asal), `ui/stage-cyan.html` (versi cyan baharu).
Buang bila tak perlu lagi.

**Nisbah sekarang:** 168 · 54 · stage · 292. Stage ambil ~66% ruang mendatar.

**API JS yang dah sedia untuk sambung Python:**

```js
window.stageMeter(id, pct, {invert})   // invert:true untuk bateri (rendah = amaran)
document.addEventListener('stage:change', e => e.detail.pane)
location.hash = '#media'               // deep link, dan kekal sebagai router
```

**Logik meter:** `hot` bila ≥85, `crit` bila ≥96. Bateri songsang — `hot` bila ≤20, `crit` bila ≤10.
Bug lama dah dibuang: dulu 88% bateri ditanda amaran sebab ambang keterbalikan.

---

## Di mana kita sekarang

| | |
|---|---|
| Projek | `C:\Users\akmal\jarvis-desktop` |
| Versi berjalan | v0.9 (HUD lama, `main.py` + `ui/index.html`) |
| Versi dalam kerja | **v1.0 stage build** (`ui/stage.html`) |
| Fasa selesai | 0 (git), 1 separuh (antara muka sahaja) |
| Fasa seterusnya | **Fasa 1 penuh** — sambung stage ke Python |
| TTS aktif | **Google Cloud, `ms-MY-Wavenet-D`** — disahkan berfungsi |

---

## Fail yang penting sekarang

```
jarvis-desktop/
├── PLAN.md              ← blueprint penuh v1.0, 9 seksyen, 8 fasa
├── NEXT_SESSION.md      ← fail ini
├── .gitignore           ← BARU: secrets.json dilindungi
├── main.py              ← v0.9 lama, 1,489 baris (tts() dah tukar ke Google)
├── services.py          ← v0.9 lama, 342 baris
├── ui/
│   ├── stage.html       ← BARU: antara muka v1.0, 9 panel, boleh dilihat
│   ├── index.html       ← v0.9 lama, masih dipakai main.py
│   └── logo.png
├── config.json          ← voice_provider=google, voice=ms-MY-Wavenet-D
├── secrets.json         ← 6 kunci (JANGAN commit)
└── tts_test/            ← 4 sampel mp3 untuk didengar
```

---

## Apa yang perlu dibuat dalam sesi baru

### 1. Dengar sampel suara dulu (2 minit)

```
C:\Users\akmal\jarvis-desktop\tts_test\
  google_A_ssml.mp3    ← perempuan
  google_B_ssml.mp3    ← lelaki
  google_D_plain.mp3   ← lelaki, dalam (lalai sekarang)
  google_D_ssml.mp3    ← sama saiz dengan plain = SSML tiada kesan
```

Soalan yang belum dijawab: **D atau B?** Dan: `"fix"` disebut betul atau jadi *"fik"*? Kalau jadi Melayu, `EN_WORDS` dalam `services.py` baris 282 perlu dibesarkan.

### 2. Semak antara muka (`ui/stage.html`)

Buka dalam Chrome. Tekan `1`–`9` tukar panel. Empat soalan menunggu jawapan:

1. Orb dalam COMMS — cukup besar, kecik, atau patut lebih besar?
2. Sembilan tab — semua perlu, atau ada yang patut dibuang?
3. Kolum kiri 208px — cukup sempit?
4. Warna cyan ini — kekal, atau tukar?

### 3. Fasa 1 penuh — sambung stage ke Python

Ini kerja sebenar sesi baru. Tiga langkah:

**a. `stage.html` jadi `index.html`** — tapi jangan buang v0.9. Simpan sebagai `ui/index-v09.html` dulu supaya boleh rollback.

**b. Telemetry hidup.** Dalam `Api`, tambah:

```python
def stage_stats(self):
    # psutil.cpu_percent, virtual_memory, disk_usage, sensors_battery, net_io
    return {...}
```

JS panggil setiap 2s, kemas kini gauge, spark, kv. Gauge `paintGauge()` dah ada dalam stage.html — cuma perlu data betul.

**c. Panel switching sebenar.** Kontrak dalam `PLAN.md` §2:

```js
class Panel {
  async mount(root, ctx) {}
  unmount() {}
  onResize(rect) {}
}
```

Mula dengan MEDIA sebab ia paling senang dan paling kau tunggu.

### 4. Fasa 2 — `media_server.py`

Kod penuh dah ada dalam chat lama. Ringkasnya: handler 206 Partial Content, bind `127.0.0.1`, port 0. **`SimpleHTTPRequestHandler` tak boleh seek** — itu sebab ia mesti ditulis sendiri.

---

## Keputusan yang dah dikunci

| perkara | keputusan | sebab |
|---|---|---|
| Stack | Python + pywebview | Tauri/Electron tak berbaloi |
| TTS | Google Cloud `ms-MY-Wavenet-D` | percuma 1M aksara/bulan, BM tulen, tiada campur |
| ElevenLabs | nanti, bila tak puas | `flash_v2_5` 0.5 kredit/aksara, BM ada |
| Editor | CodeMirror 6 | Monaco terlalu berat untuk UHD 620 |
| Files/Docs | panel HTML, bukan embed | embed = curi fokus + DPI sakit |
| NATIVE panel | paling akhir, pilihan | 90% keperluan selesai dengan HTML |
| Orb | dalam COMMS, bukan kolum sendiri | stage perlu ruang penuh |

---

## Perangkap yang dah ditemui — jangan ulang

- `SimpleHTTPRequestHandler` tak support Range → video tak boleh seek
- ImageGrab bagi hitam untuk WebView2 → guna `PrintWindow(hwnd, dc, 2)`
- Headless Chrome `--screenshot` boleh tangkap `ui/stage.html` dengan betul
- `to_ssml()` bungkus perkataan English dalam `<lang en-US>` — **jangan** guna untuk suara `en-GB`, rosak sebutan
- `_google_tts` dulu hardcode `ms-MY` walaupun suara English — dah betulkan
- rootsys: `tool_choice` diabaikan, latency naik dengan bilangan tool, kadang keluar DSML mentah
- MCP Gmail/Drive perlukan `ToolSearch` dulu atau server tak sambung

---

## Cara mula sesi baru

Taip apa saja yang jelas. Contoh:

> "sambung jarvis v1.0, baca NEXT_SESSION.md"

atau

> "aku dah dengar tts_test. guna B. sekarang buat fasa 1"

Memori projek (`jarvis-desktop-project.md`) auto-load. `NEXT_SESSION.md` beri butiran. `PLAN.md` beri blueprint.

---

## Status git

Belum `git init`. `.gitignore` dah sedia — `secrets.json`, `cache.json`, `sessions.json`, `media/`, `__pycache__/` semua dilindungi.

Bila nak mula:

```bash
cd ~/jarvis-desktop
git init
git add .
git status            # ← SEMAK: secrets.json TIDAK boleh muncul
git commit -m "v0.9 baseline + v1.0 stage prototype"
```
