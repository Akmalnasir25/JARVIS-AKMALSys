# NEXT SESSION — mula di sini

> Fail ni ditulis supaya sesi baru boleh sambung tanpa perlu scroll sejarah chat.
> Baca `PLAN.md` selepas ni. Itu blueprint penuh.

**Dikemas kini:** 2026-11-05, 00:25

---

## BARU — sistem warna gabung (shell + panel + pasangan)

UI dulu satu warna ungu. Sekarang **tiga** warna wujud serentak pada setiap skrin.

```
lapisan 1  shell      ungu 272, kekal selama-lamanya
                      iconbar, telemetry stack, rail, kolum kanan, dock
lapisan 2  panel      --hue-live, bertukar ikut panel
                      header pane, meter, nomer ghost, sparkline, orb
lapisan 3  pasangan   --alt-live, 42° dari panel
                      .pane-head .meta, stroke nomer ghost, tag media,
                      bracket kanan-bawah .stage::before
```

Sembilan pasangan, dalam `:root`:

| panel | `--hue-*` | `--alt-*` | | panel | `--hue-*` | `--alt-*` |
|---|---|---|---|---|---|---|
| comms | 272 ungu | 318 rose | | editor | 44 emas | 86 limau |
| media | 330 magenta | 288 orkid | | browse | 186 teal | 228 kobalt |
| term | 152 hijau | 194 sian | | docs | 22 bara | 64 jerami |
| files | 200 langit | 242 biru | | ana | 258 indigo | 304 plum |
| | | | | native | 210 keluli | 168 jed |

Amber 36 dan merah kekal **khas untuk keadaan**: amaran dan rosak. Jangan guna untuk hiasan.

**Perangkap yang kena ingat** — ini yang makan satu pusingan penuh:

1. Custom property dikira **di tempat ia diisytihar**, bukan di tempat ia digunakan.
   `--accent: hsl(var(--hue) …)` pada `body` sahaja akan bekukan 272. Mesti isytihar
   semula pada `.stage` juga. Sama untuk alias legasi `--cyan`/`--cyan-2`/`--violet` —
   senarai pemilih mesti `body, .stage`, kalau tidak setiap kad metrik dalam panel
   kekal ungu shell. Ini yang paling senang terlepas pandang sebab CSS-nya "betul".

2. `hsl(var(--hue) …)` **tidak sah** sebagai warna canvas. `fillStyle` senyap abaikan.
   Resolver `ac()`/`ac2()` dalam blok orb baca `getComputedStyle` jadi RGB, dan
   `syncAccent()` dipanggil pada `stage:change`. Kalau tambah lukisan canvas baru,
   guna `ac()`/`ac2()`, jangan tulis string warna terus.

3. Rail ialah **spektrum**: setiap `.stage-tab` bawa `--tab-hue` sendiri, jadi sembilan
   warna nampak serentak walaupun hanya satu panel dicat. Itu maksud "gabung" —
   peta destinasi tunjuk semua warna yang sistem ada.

Setiap panel kini ada `.pane-head` (MEDIA, FAIL, WEB, DOK baru dapat). Shell mesti
`flex: 1 1 auto` di bawah head — ada peraturan dalam `stage.html` untuk itu.

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

**Panel yang masih placeholder:** WEB, DOK, APP. Fasa 6–7. (EDITOR siap.)

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

```bash
# ujian EDITOR — bundle sebenar, bukan stub
chrome --headless=new --allow-file-access-from-files --virtual-time-budget=25000   --dump-dom "file:///C:/Users/akmal/jarvis-desktop/ui/_ed.html" | grep -o '<div id="R">[^<]*'
```

`--dump-dom` pada iframe tak boleh baca dalaman, jadi ketiga-tiga harness tulis hasil ke
elemen dalam dokumen **ibu**, bukan `console.log`.

**Perangkap harness:** jangan guna `f.addEventListener('load', …)`. Untuk fail `file://`
sebaka ia kerap tak menyala langsung, dan bila menyala pun boleh mendahului skrip anak.
Guna gelung `poll()` yang tunggu `contentDocument.readyState === 'complete'` **dan**
`contentWindow.stageShow` wujud. Dua-dua `_smoke.html` dan `_shoot.html` pernah senyap
sebab ini.

---

## Di mana kita sekarang

| | |
|---|---|
| Projek | `C:\Users\akmal\jarvis-desktop` |
| Versi berjalan | v1.1 stage (`main.py` → `ui/stage.html`) |
| Git | **dah `git init`**, commit pertama `33fccb5`, `secrets.json` dilindungi |
| Fasa selesai | 0 (git), 1 (antara muka + Python), warna gabung, 5 (EDITOR) |
| Fasa seterusnya | **Fasa 6 WEB**, atau sahkan MEDIA dalam WebView2 betul-betul |
| TTS aktif | Google Cloud, `ms-MY-Wavenet-D` |

---

## Fasa seterusnya, ikut urutan

### 1. Sahkan MEDIA dalam HUD betul-betul (15 min)

**Sisi server dah lulus** (dua `_probe.mp3`, 59 136 bait):

```
plain        -> 200  len=59136   Accept-Ranges: bytes   audio/mpeg
bytes=0-1023 -> 206  len=1024    Content-Range: bytes 0-1023/59136
bytes=-512   -> 206  len=512     Content-Range: bytes 58624-59135/59136
bytes=N-100- -> 206  len=100     Content-Range: bytes 59036-59135/59136
bytes=N+500- -> 416
```

Yang tinggal cuma **kaki WebView2**: letak satu mp4 sebenar dalam `media/`, jalan
`python main.py`, tekan `2`, klik fail. Tiga perkara:
- video main
- scrub bar betul-betul gerak (itu maksud 206 Partial)
- tukar panel tak tinggalkan audio di latar (`stage:change` patut pause)

Dua-dua fail dalam `media/` sekarang berawalan `_` dan bukan video betul — jangan
guna untuk ujian ini.

### 2. EDITOR (Fasa 5) — SIAP

CodeMirror 6, bundle `ui/vendor/editor.js` (633 KB, di-commit, tiada CDN — HUD jalan offline).
Lazy-load pada buka pertama; boot tak bayar apa-apa.

| bahagian | fail |
|---|---|
| build | `ui/vendor/_build/entry.js` → esbuild → `ui/vendor/editor.js` |
| Python | `Api.fs_write(path, text, expected_size)` dalam `main.py` |
| stage | modul EDITOR dalam `ui/stage.html`, `window.stageEditor` |

**Bina semula bundle** (kalau tukar tema atau bahasa):

```bash
cd ui/vendor/_build
npm install          # sekali sahaja
node_modules/.bin/esbuild entry.js --bundle --format=iife \
  --global-name=JarvisEditor --minify --target=chrome110 \
  --legal-comments=none --outfile=../editor.js
```

**Tiga pagar `fs_write`** — jangan buang mana-mana:

1. `_safe_path()` — skop sama macam `fs_read`.
2. `expected_size` — saiz masa fail dibaca. Kalau fail berubah di luar, tulis ditolak
   dengan `conflict: true`, editor suruh tekan Simpan sekali lagi. Ini yang halang tab
   lama padam kerja baru.
3. `.bak` sekali sebelum tulis. Bukan versioning, cuma jaring satu pusingan.

Fail > 200 KB **ditolak**, bukan diedit — `fs_read` potong pada 200k, jadi menyimpan
semula bermakna tulis potongan itu ke cakera. Jangan longgarkan tanpa ubah `fs_read`.

**Belum ada:** tab berbilang fail, carian seluruh projek, git diff dalam editor.
Kalau perlu, itu kerja baru — jangan sangkut Fasa 6 sebab ini.

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
