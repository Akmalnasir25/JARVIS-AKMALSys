# Jarvis Desktop — PLAN v1.0

> **Sasaran:** Semua kerja berlaku di dalam paparan Jarvis. Tiada `os.startfile`, tiada `webbrowser.open`, tiada Notepad, tiada VS Code. Satu surface.
>
> **Pemilik:** Akmal · **Bermula:** 2026-11-03 · **Blueprint:** 2026-11-04

---

## 0. Keadaan sekarang (v0.9)

| fail | baris | nota |
|---|---:|---|
| `main.py` | 1,458 | satu kelas `Api`, 63 method |
| `ui/index.html` | 1,668 | HTML + CSS + JS dalam satu fail |
| `services.py` | 342 | weather, solat, control, speech |
| `config.json` | — | model, voice, location, allowed_tools |
| `secrets.json` | — | rootsys, serper, google_tts, google_stt — **tiada .gitignore** |

**Kemampuan sedia ada:** dua otak (Claude Code CLI + DeepSeek via rootsys), TTS edge-tts + Google Cloud, STT hybrid Google/Whisper, wake word `hey_jarvis`, 18 tool calling, reminder, analysis panel, autostart Task Scheduler, single-instance mutex.

**Perkakasan:** Intel UHD 620 · 8 GB RAM · Windows 11 · disk C 73% penuh (67 GB bebas).

---

## 1. Diagnosis

Jarvis bukan ada masalah UI. Dia ada **lima lubang pelepasan** — setiap satu memindahkan pengguna keluar dari HUD dan memutuskan aliran.

| # | fungsi | baris | tindakan sekarang | panel pengganti |
|---|---|---:|---|---|
| 1 | `open_item()` | 361 | `os.startfile(target)` | `FILES` / `DOCS` / `NATIVE` |
| 2 | `search_web()` | 391 | `webbrowser.open(google)` | `BROWSER` |
| 3 | `open_url()` | 395 | `webbrowser.open(url)` | `BROWSER` |
| 4 | `edit_shortcuts()` | 402 | `subprocess notepad` | `EDITOR` |
| 5 | `open_in_vscode()` | 507 | `subprocess code.cmd` | `EDITOR` |

**Akar masalah:** `Api` tiada konsep "di mana sesuatu dipaparkan". Setiap tindakan yang bukan teks berakhir dengan `subprocess`. Selagi tiada konsep *stage*, setiap panel baru akan menambah satu lagi lubang.

---

## 2. Seni bina — STAGE

Tiga kolum kekal sepanjang hayat aplikasi.

```
┌────────────┬──────────────────────────────┬────────────┐
│ TELEMETRY  │           STAGE              │   COMMS    │
│            │                              │            │
│  CPU  RAM  │   ┌──────────────────────┐   │  feed      │
│  DISK BAT  │   │                      │   │            │
│            │   │   satu panel aktif   │   │  ────────  │
│  spark     │   │                      │   │  input     │
│  net/up    │   └──────────────────────┘   │            │
│            │                              │            │
│  TODAY     │        orb (idle: kecil)     │            │
└────────────┴──────────────────────────────┴────────────┘
                  dock · tabs · capsule
```

**Peraturan stage:**
1. Satu panel aktif pada satu masa. Bukan sembilan tersembunyi dalam DOM.
2. Panel di-`destroy()` bila ditukar — bebaskan memori, hentikan stream.
3. Orb kekal di tengah semasa `COMMS`; mengecil dan duduk atas stage semasa panel lain.
4. TTS dan STT kekal aktif merentasi semua panel.
5. Setiap panel ada kontrak: `mount()`, `unmount()`, `onResize()`, `onEvent()`.

**Kontrak JS:**

```js
// language: JavaScript, file: ui/js/stage.js
export class Panel {
  async mount(root, ctx) {}    // root = elemen stage, ctx = api bridge
  unmount() {}                 // WAJIB: hentikan stream, lepas handle, kosongkan DOM
  onResize(rect) {}            // rect = getBoundingClientRect() dalam CSS px
}
```

---

## 3. Spesifikasi panel

| panel | teknologi | ganti | fasa |
|---|---|---|---:|
| `COMMS` | HTML sedia ada | — | 1 |
| `MEDIA` | `<video>` + Range server | pemain luar | 2 |
| `TERMINAL` | xterm.js + pywinpty (ConPTY) | cmd / PowerShell | 4 |
| `FILES` | HTML tree + preview | File Explorer | 5 |
| `EDITOR` | CodeMirror 6 | VS Code / Notepad | 5 |
| `BROWSER` | WebView2 `evaluate_js` + `<iframe>` | Chrome | 6 |
| `DOCS` | PDF.js · docx-preview · SheetJS | Adobe / Word / Excel | 6 |
| `ANALYSIS` | sedia ada | — | 1 |
| `NATIVE` | HWND overlay (SetWindowPos) | app tak boleh embed | 7 |

### 3.1 MEDIA

`SimpleHTTPRequestHandler` **tidak** support `Range` — scrub bar mati, fail besar kena muat penuh sebelum frame pertama. Perlukan handler 206 Partial Content.

- `media_server.py`, bind `127.0.0.1`, port 0 (OS pilih), thread daemon.
- Dedah `media_base` ke JS melalui `api.media_info()`.
- Folder `media/` di root repo. Subfolder dibenarkan.
- YouTube: `<iframe>` embed dari `file://` — jalan tanpa server.

### 3.2 TERMINAL

Stack: `pywinpty` (ConPTY) → WebSocket → `@xterm/xterm` v5.5+.

Empat perangkap yang mesti dikendalikan:

| isu | penyelesaian |
|---|---|
| `pty.read()` blocking | satu thread per sesi, `loop.call_soon_threadsafe(queue.put_nowait, data)` |
| ConPTY flush kecil-kecil | buffer 5–10 ms sebelum hantar frame |
| resize garble vim/htop | debounce `fit()` 50–100 ms, hantar hanya bila cols/rows berubah |
| input mesti `\r` | bukan `\n` |

Bonus: `claude` boleh dijalankan dalam panel TERMINAL — Claude Code masuk dalam HUD, bukan subprocess tersembunyi.

### 3.3 FILES + EDITOR

- Baca/simpan melalui `Api` (Python), bukan `file://`. Guna `_tool_read` sedia ada, tambah `write_file`.
- **Guard:** tulis hanya dalam `workdir` yang dikonfigurasi. Semak `Path.resolve().is_relative_to(WORKDIR)`.
- Editor: **CodeMirror 6**, bukan Monaco. Monaco ~2MB; UHD 620 kau akan rasa beza.
- Preview: Monaco read-only untuk teks, PDF.js untuk PDF, `openpyxl` sedia ada untuk xlsx.

### 3.4 BROWSER

Dua laluan:
- **Iframe** untuk laman yang benarkan embed (YouTube, docs ringkas).
- **WebView2 nav** untuk laman yang sekat — `window.load_url()` atau `evaluate_js("location.href=...")`. Ini menukar seluruh HUD, jadi perlukan snapshot DOM dan pulih bila balik.

**Batasan jujur:** banyak laman (Google, bank, Gmail) sekat iframe melalui `X-Frame-Options`. Untuk itu, guna `webbrowser.open` sebagai *fallback* yang pengguna pilih secara eksplisit — bukan lalai.

### 3.5 NATIVE

Tiada cara browser embed HWND dalam `<iframe>`. Satu corak sahaja:

```
JS ukur rect stage → Python → SetParent + SetWindowPos
```

- `window.native` (pywebview 6.2.1, backend edgechromium) → `Form.Handle` = HWND induk.
- **DPI:** `getBoundingClientRect()` CSS px, `SetWindowPos` physical px → darab `devicePixelRatio`.
- **Z-order:** `SetParent` ke Form buat app duduk atas WebView2. Bila tukar panel, **wajib** `ShowWindow(hwnd, SW_HIDE)`.
- **Input:** app yang di-embed curi fokus. Tak boleh dapat DOM event menembusinya.
- **Resize:** `ResizeObserver` → hantar rect baru.

**Keputusan:** 90% keperluan selesai dengan panel HTML. NATIVE hanya untuk app yang benar-benar perlu (Photoshop, software khusus), dan paling akhir sekali.

---

## 4. Struktur fail sasaran

```
jarvis-desktop/
├── main.py                  # ~120 baris: boot, mutex, webview.start()
├── core/
│   ├── config.py            # load_json, paths, secrets
│   ├── bus.py               # _emit, event routing
│   └── window.py            # HWND, SetWindowPos, DPI
├── panels/
│   ├── comms.py
│   ├── media.py
│   ├── terminal.py
│   ├── files.py
│   ├── editor.py
│   ├── browser.py
│   ├── docs.py
│   └── native.py
├── voice/
│   ├── tts.py               # router: elevenlabs → google → edge
│   ├── providers/
│   │   ├── eleven.py
│   │   ├── google.py
│   │   └── edge.py
│   ├── stt.py               # hybrid google/whisper
│   └── wake.py              # openWakeWord loop
├── services.py              # kekal
├── media_server.py          # Range handler
├── ui/
│   ├── index.html           # struktur sahaja
│   ├── css/{base,hud,panels}.css
│   └── js/
│       ├── app.js           # boot + router
│       ├── stage.js         # panel manager
│       ├── orb.js
│       └── panels/*.js
├── media/
├── .gitignore
└── PLAN.md
```

`Api` jadi **thin facade** yang dispatch ke panel. Bila terminal rosak, buka `panels/terminal.py` (~200 baris), bukan cari dalam 1,458.

---

## 5. Suara — ElevenLabs

### 5.1 Kenapa

TTS sekarang: **edge-tts** (percuma, `ms-MY-OsmanNeural`) dan **Google Cloud** (`ms-MY-Wavenet-D`). Kedua-duanya jelas sintetik. Osman khususnya berbunyi macam penyampai berita 2010 — tiada prosodi emosi, tiada pernafasan, tiada variasi.

ElevenLabs ialah lompatan generasi, bukan peningkatan kecil. Untuk Bahasa Melayu, ini yang paling dekat dengan suara manusia sebenar yang ada hari ini.

### 5.2 Model — pilih betul

**Bahasa Melayu (`ms`) disahkan ada dalam kedua-dua `multilingual_v2` dan `flash_v2_5`.** Ini bukan andaian — ia dalam senarai bahasa rasmi.

| model | bahasa | kredit/aksara | latency | guna |
|---|---|---:|---:|---|
| `eleven_flash_v2_5` | 32 | 0.5 | ~75 ms | **lalai** — sembang langsung |
| `eleven_turbo_v2_5` | 32 | 0.5 | ~250 ms | naratif panjang |
| `eleven_multilingual_v2` | 29 | 1.0 | ~400 ms | kualiti tinggi, lebih perlahan |
| `eleven_v3` | 70+ | 1.0 | tinggi | ekspresif, tidak sesuai sembang |
| `eleven_v4` | 90+ | semak | tinggi | generasi baru, sahkan kos |

`flash_v2_5` senarai 29 bahasa `multilingual_v2` **tambah** Hungarian, Norwegian, Vietnamese. Kedua-duanya ada Melayu. Jadi pilihan lalai jelas: **`flash_v2_5`** — 2× lebih murah, 5× lebih pantas, Melayu ada.

Sahkan sekali dengan `GET /v1/models` masa implementasi — senarai berubah.


### 5.3 Kos — ini yang menentukan reka bentuk

Jarvis bercakap **sepanjang hari**. Balasan ~500 aksara, brief pagi ~2,000, naratif analisis ~1,500.

| pelan | harga | kredit | aksara (flash) | balasan/bulan |
|---|---:|---:|---:|---:|
| Free | $0 | 10k | 20k | ~40 |
| Starter | $5 | 30k | 60k | ~120 |
| Creator | $22 | 100k | 200k | ~400 |
| Pro | $99 | 500k | 1M | ~2,000 |

Implikasi reka bentuk: **jangan hantar semua teks ke ElevenLabs.** Tiga peraturan:

1. **Router berlapis.** ElevenLabs untuk balasan sembang dan brief. edge-tts untuk sistem (`"File dibuka"`, `"Reminder"`) — percuma, tak perlu kualiti.
2. **Cache mengikut hash teks.** Brief pagi, pengumuman solat, sapaan — semuanya berulang. `sha1(text+voice+settings)` → fail mp3 dalam `cache/tts/`. Satu kali bayar, seribu kali main.
3. **Potong teks.** Buang markup, kod, URL, jadual sebelum hantar. Kod tak perlu dibaca kuat.

### 5.4 Streaming

`tts()` sekarang pulangkan data URI base64 penuh — kau tunggu seluruh audio siap. Untuk teks panjang itu mati.

Tiga lapisan:

1. **Ayat demi ayat.** Pecah pada `.` `?` `!` dan hantar serentak. Main ayat 1 sambil ayat 2 dimuat. Kau dah buat ini dalam analysis mode — jadikan ia lalai.
2. **Endpoint stream** `POST /v1/text-to-speech/{id}/stream` — audio mula mengalir sebelum teks habis diproses.
3. **Simpan ke fail, serve melalui media_server.** Elak base64 33% overhead merentasi JS bridge. `<audio src="http://127.0.0.1:PORT/tts/abc.mp3">` — Range support percuma.

### 5.5 Suara tersuai

Tiga pilihan, ikut urutan kos:

| pilihan | cara | kos |
|---|---|---|
| **Voice library** | pilih dari pustaka ElevenLabs, ada suara sedia ada | $0 |
| **Instant cloning** | muat naik 1–3 minit audio bersih | pelan berbayar |
| **Professional cloning** | 30 min audio studio | $22+ |

Untuk Jarvis, **voice library cukup** — cari British RP male, tenor rendah, tenang. Itu tonaliti Jarvis asal. Clone diri sendiri hanya kalau kau mahu Jarvis bercakap dengan suara kau.

**Nota undang-undang:** clone suara orang lain tanpa kebenaran bertulis — jangan. Clone suara sendiri — bebas.

### 5.6 Fallback

Setiap panggilan ElevenLabs mesti ada rantaian: `eleven → google → edge → gagal senyap`.
Sebab: rate limit, kredit habis, rangkaian putus. Jarvis tak boleh berhenti bercakap sebab API pihak ketiga.

### 5.7 Alternatif tempatan (untuk rujukan)

| enjin | BM | nota |
|---|---|---|
| Piper | ada `ms_MY` | percuma, offline, CPU, kualiti sederhana |
| Coqui XTTS-v2 | tiada | 17 bahasa, BM tiada |
| Kokoro-82M | tiada | Apache, laju, BM tiada |
| F5-TTS | tiada | cloning, BM tiada |

**Realiti:** pilihan TTS Bahasa Melayu tipis. ElevenLabs bukan kemewahan — ia satu-satunya yang betul-betul natural. Kalau mahu percuma, Piper satu-satunya jalan, dan kau akan dengar beza.

---

## 6. Urutan binaan

| fasa | kerja | sesi | hasil |
|---|---|---:|---|
| **0** | `git init` · `.gitignore` (`secrets.json`, `cache.json`, `__pycache__`) · commit pertama | 10 min | selamat |
| **1** | `stage.js`, panel manager, tab, peralihan, orb mengecil | 1 | rangka boleh dilihat |
| **2** | `media_server.py` · panel MEDIA · playlist · YouTube | 1 | **lubang #1 tertutup** |
| **3** | Pecah `Api` → `core/` + `panels/` + `voice/` | 1 | asas boleh dikembangkan |
| **4** | `pywinpty` + `xterm.js` + panel TERMINAL | 1–2 | `claude` masuk HUD |
| **5** | FILES + EDITOR (CodeMirror 6) | 1 | **lubang #1, #4, #5 tertutup** |
| **6** | BROWSER + DOCS (PDF.js, SheetJS) | 1 | **lubang #2, #3 tertutup** |
| **7** | NATIVE HWND host | 2 | pilihan |
| **8** | Suara: router TTS + ElevenLabs + cache + streaming | 1–2 | v1.0 penuh |

**Peraturan:** fasa 3 (pecah `Api`) mesti sebelum fasa 4. Menambah terminal ke dalam fail 1,800 baris ialah cara terpantas membuat projek mati.

**Peraturan 2:** setiap fasa berakhir dengan Jarvis boleh dijalankan. Tiada fasa separuh siap yang ditinggalkan.

---

## 7. Kekangan perkakasan

Intel UHD 620 · 8 GB RAM. Ini kekangan yang **membentuk** keputusan, bukan alasan:

- **Satu stage panel pada satu masa.** Lazy-load, destroy bila tukar.
- **CodeMirror 6, bukan Monaco.**
- **1080p H.264 sahaja.** Tiada live-preview 4K.
- **Whisper `small` kekal.** Jangan naik ke `medium`.
- **Cache TTS wajib.** Bukan pilihan — ia yang menjimatkan CPU dan kredit.

---

## 8. Log keputusan

| tarikh | keputusan | sebab |
|---|---|---|
| 2026-11-04 | Kekal Python + pywebview, tolak Tauri/Electron | pywebview = Python otak + HTML HUD. Tauri/Electron tak beri kelebihan setimpal dengan kos migrasi |
| 2026-11-04 | Range server, bukan `SimpleHTTPRequestHandler` | tanpa 206, video tak boleh seek |
| 2026-11-04 | CodeMirror 6, bukan Monaco | UHD 620 |
| 2026-11-04 | FILES/DOCS sebagai panel HTML, bukan embed Explorer/Word | embed = curi fokus + DPI per-monitor + tak boleh kawal |
| 2026-11-04 | NATIVE panel paling akhir, pilihan | 90% keperluan selesai dengan HTML |
| 2026-11-04 | ElevenLabs `flash_v2_5` lalai, bukan `multilingual_v2` | BM dalam senarai 32 bahasa v2.5; kos 0.5 kredit/aksara |
| 2026-11-04 | edge-tts kekal untuk mesej sistem | percuma, kualiti tak kritikal |

---

## 9. Soalan terbuka

1. NATIVE panel perlu atau tidak? (menentukan 5 fasa vs 7)
2. Voice library atau clone suara sendiri?
3. Pelan ElevenLabs mana — Starter, Creator, atau Pro?
4. `claude` dalam TERMINAL panel — ganti `_run_claude` sedia ada, atau kekal dua laluan?
