# NEXT SESSION — mula di sini

> Fail ni ditulis supaya sesi baru boleh sambung tanpa perlu scroll sejarah chat.
> Baca `PLAN.md` selepas ni. Itu blueprint penuh.

**Dikemas kini:** 2026-11-05, 00:05

---

## BARU — Fasa 1 selesai (stage hidup)

Skrip `ui/stage.html` selama ni **mati sepenuhnya** dan tiada siapa perasan, sebab HTML
statik masih nampak betul. Dua sebab, dua-dua dah dibetulkan:

| masalah | kesan | betul |
|---|---|---|
| `let api` diisytihar dalam blok BRIDGE (baris 2080) tetapi modul MEDIA/FILES sentuh `api` pada skop modul sebelum baris itu | TDZ `ReferenceError` → seluruh IIFE mati. Tiada panel bertukar, tiada stats, `onClaude`/`stageAnalysis`/`onVoice` semuanya `undefined` | deklarasi dinaikkan ke atas, satu binding dikongsi |
| tiada siapa panggil `media_list()` masa boot atau masa buka pane | senarai MEDIA kosong sampai ada arahan `media_open()` | `stageMedia.refresh()` dipanggil dari `boot()` dan dari `stage:change` |

Sekarang hidup: telemetri 2 s, sembilan panel, MEDIA (senarai + main), FAIL (tree + pratonton),
ANALISIS (kad, graf bar, poin bernarasi), terminal mirror, chat + `onClaude` stream, TTS, orb.

**Panel yang masih placeholder:** EDITOR (CodeMirror 6), WEB, DOK, APP. Fasa 5–7.

---

## ANALISIS — panel baru, dah berfungsi

`window.stageAnalysis(payload)` render payload `present_analysis` yang sedia ada dalam `main.py`.
Tiada perubahan Python diperlukan — `_emit("analysis", args)` dan blok ` ```jarvis-analysis `
dua-dua masuk ke renderer yang sama.

Struktur payload (dah wujud, jangan ubah):

```js
{title, summary, cards:[{label,value,note}], charts:[{title,items:[{label,value,display}]}],
 points:[{text,target:"card:0"|"chart:0"|"chart:0:1"}], followups:[...]}
```

Tingkah laku: kad kekal malap sampai poin yang menyebutnya disebut. TTS diambil **semua
serentak** di awal supaya tiada jeda antara poin. Bar mengisi bila grafiknya disebut.

**Jangan guna animasi kira naik untuk angka.** Percubaan pertama guna rantai
`requestAnimationFrame`; bila window tak melukis (pane tersembunyi, throttle, skrin
headless) frame pertama tulis `0` dan rantai tak pernah sampai ke nilai sebenar — kad
tersangkut pada `0%`. Angka ditulis terus, gerakan reveal dibuat dengan CSS.

---

## MEDIA — dua perkara yang baru dibetulkan

- Audio tak lagi dapat kotak hitam penuh skrin. `.media-screen audio { display:none }` +
  `.audio-only.playing` jadi jalur 64px, jadi senarai fail dapat ruang.
- Kad tengah tak lagi kata "Belum ada medium" bila folder ada fail, dan tak hilang ke
  skrin hitam bila autoplay disekat WebView2. Ia kekal sampai `<video>` betul-betul `play`.

---

## FAIL — bug ikon

Baris `..` tampal `<svg>` mentah terus ke `.node` tanpa pembalut `.ic`, jadi ikon melarat
penuh satu baris. Sekarang guna `span.ic` macam baris lain.

---

## Cara uji tanpa buka HUD

Dua harness dalam `ui/` (dua-dua di-.gitignore, jadi tak masuk commit):

```bash
# ujian penuh — Api palsu, semua panel, ask round-trip, analysis render
chrome --headless=new --allow-file-access-from-files --virtual-time-budget=9000 \
  --dump-dom "file:///C:/Users/akmal/jarvis-desktop/ui/_smoke.html" | grep -o 'RESULT{[^}]*}'

# tangkap skrin satu panel: #media #files #ana #term ...
chrome --headless=new --allow-file-access-from-files --window-size=1600,900 \
  --virtual-time-budget=9000 --screenshot="C:\...\ui\_sh.png" \
  "file:///C:/Users/akmal/jarvis-desktop/ui/_shoot.html#ana"
```

`--dump-dom` pada iframe tak boleh baca dalaman, jadi kedua-dua harness tulis hasil ke
elemen dalam dokumen **ibu**, bukan `console.log`.

---

## Di mana kita sekarang

| | |
|---|---|
| Projek | `C:\Users\akmal\jarvis-desktop` |
| Versi berjalan | v1.1 stage (`main.py` → `ui/stage.html`) |
| Git | **dah `git init`**, commit pertama `33fccb5`, `secrets.json` dilindungi |
| Fasa selesai | 0 (git), 1 (antara muka + sambungan Python) |
| Fasa seterusnya | **Fasa 2** — `media_server.py` dah wujud, kena sahkan seek betul dalam WebView2 |
| TTS aktif | Google Cloud, `ms-MY-Wavenet-D` |

---

## Fasa seterusnya, ikut urutan

### 1. Sahkan MEDIA dalam HUD betul-betul (15 min)

Letak satu mp4 dalam `media/`, jalan `python main.py`, tekan `2`, klik fail.
Yang perlu betul: video main, scrub berfungsi (itu maksud 206 Partial), tukar panel
tak tinggalkan audio berjalan di latar.

Kalau seek tak jalan → `media_server.py` hantar `Content-Range` salah. Check dengan:

```bash
curl -s -D- -o /dev/null -H "Range: bytes=0-1023" http://127.0.0.1:<port>/<fail>
```

Mesti dapat `206` + `Content-Range: bytes 0-1023/<size>`.

### 2. EDITOR (Fasa 5) — CodeMirror 6

Placeholder dah ada, kontrak dah ada. Lazy-load sahaja, jangan bundle masuk `stage.html`.
Guna `fs_read`/`fs_write`; `_safe_path()` dah hadkan skop ke workdir. Belum ada `fs_write`
dalam `main.py` — itu kerja pertama.

### 3. WEB (Fasa 6) — pilih satu jalan dulu

Iframe senang tetapi separuh laman sekat `X-Frame-Options`. Navigasi WebView2 dalam
sub-window paling bersih; snapshot DOM jalan tetapi rapuh. Jangan buat dua-dua serentak.

### 4. APP (Fasa 7) — paling akhir

`SetParent` + `SetWindowPos` atas rect stage. Wajib `ShowWindow(hwnd, SW_HIDE)` bila tukar
panel, kalau tidak app duduk atas WebView2.

---

## Keputusan yang dah dikunci

| perkara | keputusan | sebab |
|---|---|---|
| Stack | Python + pywebview | Tauri/Electron tak berbaloi |
| TTS | Google Cloud `ms-MY-Wavenet-D` | 1M aksara/bulan percuma, BM tulen |
| ElevenLabs | nanti, bila tak puas | `flash_v2_5` 0.5 kredit/aksara |
| Editor | CodeMirror 6 | Monaco terlalu berat untuk UHD 620 |
| Files/Docs | panel HTML, bukan embed | embed = curi fokus + DPI sakit |
| APP | paling akhir, pilihan | 90% keperluan selesai dengan HTML |
| Orb | dalam COMMS, bukan kolum sendiri | stage perlu ruang penuh |
| Angka dash | tulis terus, bukan kira naik | rAF tersekat = kad beku pada 0 |

---

## Perangkap yang dah ditemui — jangan ulang

- **`let` di bawah pemakaian.** Modul IIFE jalan ikut urutan fail. Kalau modul di atas
  sentuh `let` yang diisytihar di bawah, seluruh skrip mati dengan `ReferenceError` dan
  tiada apa akan beritahu — HTML statik masih nampak elok. Uji dengan `typeof window.onClaude`.
- **Animasi angka guna rAF** — pane tersembunyi tak melukis, rantai mati pada frame pertama.
- `SimpleHTTPRequestHandler` tak support Range → video tak boleh seek
- ImageGrab bagi hitam untuk WebView2 → guna `PrintWindow(hwnd, dc, 2)`
- `--dump-dom` tak tembus iframe; tulis hasil ke DOM dokumen ibu
- Headless Chrome tulis screenshot guna laluan Windows penuh, bukan relatif
- `to_ssml()` bungkus perkataan English dalam `<lang en-US>` — **jangan** guna untuk `en-GB`
- rootsys: `tool_choice` diabaikan, latency naik dengan bilangan tool, kadang DSML mentah
- MCP Gmail/Drive perlukan `ToolSearch` dulu atau server tak sambung

---

## Status git

```bash
cd ~/jarvis-desktop
git log --oneline        # 33fccb5 v0.9 baseline + v1.1 stage surface
git status               # mesti bersih
```

`.gitignore` lindungi `secrets.json`, `cache.json`, `sessions.json`, `media/`, `tts_test/`,
`__pycache__/`, dan semua `ui/_*` (harness + screenshot), `ui/stage-v1.html`,
`ui/stage-cyan.html`, `ui/stage-pre-tdz-fix.html`, `ui/index-v09.html`.
