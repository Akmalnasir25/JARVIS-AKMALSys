# NEXT SESSION — mula di sini

> Fail ni ditulis supaya sesi baru boleh sambung tanpa perlu scroll sejarah chat.
> Baca `PLAN.md` selepas ni. Itu blueprint penuh.

**Dikemas kini:** 2026-11-06, 01:10

---

## BARU — Jarvis boleh kawal laptop (`system.py`)

Satu perkataan sahaja: **`system.py`** (baharu, ~900 baris). Ia duduk sebelah
`services.py` kerana `services.py` hanya tahu tekan kod VK media — ia tak boleh jawab
"volume 30", "cerahkan separuh", atau "apa tetingkap terbuka".

**Tiga tingkat kuasa**, ditanda pada setiap handler sebagai `.kind`:

| tingkat | maksud | contoh |
|---|---|---|
| `baca` | tak ubah apa-apa | status, windows, processes, clip_read, shell |
| `ubah` | ubah tapi boleh undur | volume, brightness, focus, launch, url, type, lock |
| `pukal` | susah diundur | kill, close_window, recycle, sleep, shutdown, restart |

`pukal` tak jalan terus. `System.do()` pulangkan `{"need_confirm":True, "token":...,"ask":...}`
dan token itu hidup **90 saat**. `confirm(token)` yang buat kerja. Tiga jalan masuk
kongsi satu `System` — suara (`Api.resolve_system`), model (tool `system`), dan panel —
jadi token yang dicetak satu jalan boleh dibelanja jalan lain. Token palsu dan token
luput dua-dua ditolak (diuji).

**Audio tanpa `pycaw`.** COM terus melalui `ctypes`: `CoCreateInstance(CLSID_MMDeviceEnumerator)`
→ vtable[4] `GetDefaultAudioEndpoint` → vtable[3] `Activate(IID_IAudioEndpointVolume)` →
vtable[7] `SetMasterVolumeLevelScalar`. Tiada dependency baharu, tiada pip install.

**Kecerahan melalui WMI + pythonnet.** `WmiMonitorBrightnessMethods` /
`InvokeMethod("WmiSetBrightness",[1,pct])`. Nota: menghantar `str` kosong sebagai nama
kelas membaling ralat ManagementPath — guna `ManagementPath("...")` dengan `ObjectGetOptions()`.
Bacaan selepas tulis lambat ~1 saat; jangan tulis ujian yang baca serta-merta.

**Shell ialah senarai putih, bukan senarai hitam.** `SHELL_ALLOW` regex + penapis awal
yang tolak `&&`, `||`, `;`, `|`, `>`, `<`, backtick, `$(`. Senarai hitam sentiasa ketinggalan
satu langkah di belakang pemanggil yang rajin.

**Perangkap clipboard.** `GlobalAlloc` / `GlobalLock` / `GetClipboardData` memulangkan
pemegang 64-bit; tanpanya `argtypes`/`restype` ctypes potong jadi int 32-bit dan menulis
melaluinya membaling `access violation writing 0x0000000000000000`. Setiap satu mesti
ada `argtypes` **dan** `restype`, dan guna `ctypes.wstring_at(ptr)`, bukan `c_char_p(ptr)`.

**Resolver jalan dahulu, media dikecualikan.** `quick_control` baca `resolve_system`
sebelum `services.match_control` — sebab "volume 30" yang lalu melalui tekan-kekunci
30 kali akan bunyikan bunyi bising dan berhenti di 100%. Tapi ayat yang ada
`lagu|muzik|music|track|song|slide|slideshow|pembentangan|presentation|scroll` melangkau
resolver, jika tidak "main lagu" ditelan oleh cabang buka/url.

**`show_doc` ialah satu-satunya tindakan yang diwakilkan.** `System` tak tahu tentang HUD,
jadi `_a_show_doc` ditanda `.delegated = True` dan `Api._open_doc_in_stage()` yang
menyelesaikannya (baca dokumen → tukar panel → suap ke `window.stageDocs.open`).
Kalau `@staticmethod` tertinggal pada `_match_system`, `self._find_doc` membaling
`NameError` — sudah dibetulkan, jangan letak balik.

---

## BARU — DOK dalam Python, bukan dalam browser

Fasa 6 selebihnya siap tanpa PDF.js / docx-preview / SheetJS. Keputusan: **hurai di
Python**, hantar blok struktur kecil, stage warnakan dengan CSS sendiri.

| format | pembaca | dihantar sebagai |
|---|---|---|
| pdf | `pymupdf` | teks 60 halaman + PNG halaman semasa @130dpi |
| docx | `python-docx` | blok `h`/`p`/`table` |
| xlsx/xlsm | `openpyxl` | helaian × baris (dipotong) |
| pptx | `python-pptx` | slaid: tajuk + isi |
| csv / md / txt / json | stdlib | teks |

Sebab: PDF.js + docx-preview + SheetJS bersama ~3 MB JS, perlu npm build dan versi
yang mesti dijaga. Empat pilihan Python itu **sudah ada** dalam env dan berjalan pada
mesin yang sama. Bonus: kerana stage yang melukis, dokumen ikut warna panel secara
percuma (hue 22) — sesuatu yang bundle pihak ketiga tak bagi.

Perangkap: `pr.slides[:80]` memulangkan `list` kosong tanpa `rId`, jadi `AttributeError`
bila python-pptx baca semula. Guna `range(min(total,80))` + indeks.
`fitz` sudah deprecated dalam 1.28 — `import pymupdf as fitz`, dengan `import fitz` sebagai
sandaran.

---

## BARU — APP: tetingkap asal masuk stage (Fasa 7)

`SetParent` + `SetWindowPos`, dengan pemulihan penuh pada detach:

```
simpan  GetParent(hwnd), GetWindowLongPtrW(GWL_STYLE), GetWindowRect
pasang  style = (style & ~WS_POPUP) | WS_CHILD  →  SetParent
lepas   SetParent(parent) → SetWindowLongPtrW(style asal) → SetWindowPos(rect asal)
```

**Koordinat.** `SetWindowPos` pada tetingkap anak mengambil koordinat relatif kepada
kawasan **klien** ibu; `getBoundingClientRect()` dalam JS pula relatif kepada viewport.
Kedua-dua asalan itu sama, jadi tiada pembetulan asalan skrin diperlukan. Yang tinggal
hanya tukar unit: CSS px → px fizikal.

**Penemuan yang memakan masa:** WebView2 **sudah** menyelesaikan unit CSS terhadap skala
Windows. Probe dengan `scale=1.5` pada DPI 150% menghasilkan 630×390 daripada rect
420×260 CSS — iaitu WebView2 melaporkan CSS px yang sudah diskalakan. Jadi JS mesti
hantar `scale=1` dan **Python** yang ukur DPI tetingkap HUD sendiri (`GetDpiForWindow/96`).
Tanpa itu app tersangkut di suku atas stage.

**Wajib:** `ShowWindow(hwnd, SW_HIDE)` bila tukar panel. Tetingkap anak sentiasa duduk
atas WebView2 dan CSS tak boleh menutupnya. Pendengar `stage:change` dalam stageApp
yang uruskan — jangan buang.

---

## Ringkasan status fasa

| fasa | apa | status |
|---|---|---|
| 0 | git + `.gitignore` | siap |
| 1 | antara muka Python ↔ WebView2 | siap |
| — | sistem warna gabung (3 lapisan) | siap |
| 5 | EDITOR (CodeMirror 6) | siap |
| 6 | WEB (tetingkap anak + iframe) | siap · `create_window` belum diuji hidup |
| 6b | DOK (pdf/docx/xlsx/pptx/csv/md) | siap |
| 7 | APP (embed tetingkap asal) | siap · belum diuji atas HUD sebenar |
| — | kawalan laptop (`system.py`) | siap · 46/46 ujian e2e |

---

## Cara uji tanpa buka HUD

```bash
# kawalan laptop hujung-ke-hujung, Api sebenar, _window=None
PYTHONIOENCODING=utf-8 python ui/_sys_e2e.py        # 46 lulus, 0 gagal

# harness browser — satu skrip untuk semua
cd ui && sh _run.sh _smoke.html _docs.html _app.html _sysui.html _web.html
```

`PYTHONIOENCODING=utf-8` bukan hiasan: konsol Windows guna cp1252 dan `✔`/`✖` dalam
label akan membaling `UnicodeEncodeError` di tengah ujian.

`--allow-file-access-from-files` pula wajib untuk harness: tanpanya skrip dalam iframe
tak jalan dan `--dump-dom` hanya memulangkan **sumber** skrip, bukan hasilnya.

---



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

**Bar telemetri** ikut peraturan yang sama, tapi bukan `var(--hue)`: meter ialah
perabot shell, jadi ia mesti kekal bila panel bertukar. Setiap tube ada pasangan
sendiri melalui `--fill-a`/`--fill-b`:

| meter | bawah | atas |
|---|---|---|
| CPU | ungu 272 | magenta 302 |
| RAM | violet 256 | biru 196 |
| DSK | biru 228 | ungu 272 |
| BAT | hijau 152 | sian 186 |

Empat warna berbeza pada ketinggian yang sama — itu maksudnya. Kalau semua tube
kongsi satu gradien, stack jadi satu blok warna, bukan empat alat.

`hot` (amber) dan `crit` (merah) menang atas warna per-alat melalui pemilih
**ber-ID** (`#g-cpu.hot .v`). Tanpa ID, warna `.v` per-alat akan menang atas
`.meter.hot .v` dan amaran tak pernah muncul. Ini dah terkena sekali.

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

**Panel yang masih placeholder:** DOK, APP. Fasa 6–7. (EDITOR dan WEB siap.)

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

## Perangkap harness browser

`--dump-dom` tak boleh baca dalaman iframe, jadi setiap harness tulis hasil ke elemen
`#R` dalam dokumen **ibu**, bukan `console.log`.

**Jangan guna `f.addEventListener('load', …)`.** Untuk fail `file://` sebaka ia kerap
tak menyala langsung, dan bila menyala pun boleh mendahului skrip anak. Guna gelung
`poll()` yang tunggu `contentDocument.readyState === 'complete'` **dan**
`contentWindow.stageShow` wujud. `_smoke.html` dan `_shoot.html` pernah senyap sebab ini.

**Jangan panggil `send()` dari harness.** Ia skop-modul, bukan pada `window`. `window.runCommand`
dieksport khas untuk itu.

**HUD `busy` lock.** `ask()` palsu mesti juga hantar `onClaude('done')`, kalau tidak
arahan berikutnya digugurkan senyap.

```bash
# tangkap skrin satu panel: #media #files #ana #term #docs #native
chrome --headless=new --allow-file-access-from-files --window-size=1600,900 \
  --virtual-time-budget=9000 --screenshot="C:\...\ui\_sh.png" \
  "file:///C:/Users/akmal/jarvis-desktop/ui/_shoot.html#ana"
```

---

## Di mana kita sekarang

| | |
|---|---|
| Projek | `C:\Users\akmal\jarvis-desktop` |
| Versi berjalan | v1.1 stage (`main.py` → `ui/stage.html`) |
| Git | **dah `git init`**, commit pertama `33fccb5`, `secrets.json` dilindungi |
| Fasa selesai | 0 (git), 1 (antara muka), warna gabung, 5 (EDITOR), 6 (WEB), 6b (DOK), 7 (APP), kawalan laptop |
| Pengesahan hidup | **37/37 lulus** dalam WebView2 sebenar (`ui/_live.py`) — sembilan panel, media seek, pdf, editor, embed app, web, token, volume, TTS, chat |
| TTS aktif | Google Cloud, `ms-MY-Wavenet-D` |

---

## Fasa seterusnya, ikut urutan

### 0. Pengesahan hidup — SELESAI

`ui/_live.py` memulakan HUD sebenar (WebView2, bukan headless), memandu setiap panel,
dan menulis `ui/_live/report.txt` baris demi baris supaya keputusan terselamat kalau
`win.destroy()` tergantung. Larian terakhir: **37 ok, 0 gagal**. Skrin: `ui/_live/*.png`.

```bash
cd ~/jarvis-desktop
python ui/_live.py          # ~90 saat, buka HUD sebenar dua kali
```

Yang dibuktikan, bukan diandaikan: media `readyState 4` dan seek 4.2/6s; pdf 8 halaman
render 1075×1521 melalui laluan suara; CodeMirror buka fail; Notepad masuk stage melalui
`SetParent` dengan rect 452,106 → 528×509; `create_window` hidup dan bertukar
visible/parkir tanpa reload; prompt pengesahan dua butang dan "Tak" membatalkan token;
`volume 33` mendarat; `status laptop` membaca angka hidup; TTS edge; model chat 1.3s.

Yang **belum** diuji: `python main.py` penuh dengan mic, penjaga solat dan `_stt_janitor`
hidup serentak. Itu Akmal yang jalankan, ikut `MULA.md`.

Cara uji manual (kalau mahu ulang satu panel sahaja):

| apa | cara sahkan | apa yang membuktikan ia betul |
|---|---|---|
| MEDIA | letak satu `.mp4` dalam `media/`, `python main.py`, tekan `2`, klik fail | video main, scrub gerak (itu maksud 206), tukar panel senyap |
| WEB | tekan `6`, taip `example.com` | `create_window` benar-benar hidup dalam pywebview 6 |
| APP | buka Notepad, tekan `9`, pilih tetingkap | ia masuk stage, tak melimpah, hilang bila tukar panel |
| DOK | tekan `7`, klik satu pdf | halaman render, anak panah tukar halaman |
| kawalan | cakap "volume 40", "tutup chrome", "status laptop" | resolver tangkap sebelum model, tanpa lag |
| buka dokumen | cakap "buka laporan.pdf" | panel DOK terbuka dengan fail itu, bukan app luar |

`widget`/`media` sekarang hanya ada `_probe.mp3` dan `_t.bin` — bukan video. Jangan guna
untuk ujian MEDIA.

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

### 3. WEB (Fasa 6) — SIAP

Dua jalan render, dipilih ikut laman. **Bukan** dua-dua sekali gus — sebab separuh
internet sekat embed, dan satu jalan sahaja tak cukup:

| jalan | bila | kos |
|---|---|---|
| tetingkap anak WebView2 | default | tetingkap berasingan, kena ikut rect stage |
| iframe | tekan **Embed** | laman yang hantar `X-Frame-Options` jadi kosong |

Tetingkap anak dicipta Python (`webview.create_window` dari thread bridge JS —
pywebview 6 sokong ini) dan diletak tepat atas `#webBody`. Rect dihantar dari JS
melalui `web_stage_rect(x, y, w, h)` pada buka pane dan resize.

**Tiga method, jangan keliru antara satu sama lain:**

| method | makna |
|---|---|
| `web_open(url)` | cipta atau navigasi. Guna semula tetingkap kalau ada |
| `web_show()` | tunjuk semula tetingkap yang diparkir, **tanpa reload** |
| `web_hide()` | parkir, kekalkan laman |

Tukar panel guna `hide`, bukan `close` — destroy setiap kali tukar panel bermakna
buang posisi skrol dan borang yang separuh diisi. `web_show` yang buat `show`,
bukan `web_open`; kalau tersilap panggil `web_open` di situ, setiap kali balik ke
WEB laman reload.

Carian: alamat tanpa titik dianggap carian, dibawa ke DuckDuckGo dalam tetingkap
anak. Logik yang sama dipakai kotak alamat dan `web_search()`, jadi dua-dua tak
boleh bercanggah.

**Snapshot DOM telah dibuang dari reka bentuk.** Ia nampak betul untuk satu saat,
lepas itu setiap laman yang bergantung pada skrip mati dan skrol langsung tak jalan.

**Belum diuji:** `create_window` sebenar. Semua laluan lain diuji dengan bridge
palsu. Jalankan `python main.py`, tekan `6`, taip satu alamat.

### 4. APP (Fasa 7) — SIAP

`SetParent` + `SetWindowPos` atas rect stage, dengan pemulihan penuh (parent, style, rect).
Wajib `ShowWindow(hwnd, SW_HIDE)` bila tukar panel — tetingkap anak sentiasa di atas
WebView2 dan CSS tak boleh menutupnya. Perincian penuh di bahagian APP di atas.

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
- **ctypes tanpa `restype`.** Pemegang 64-bit dipotong jadi int 32-bit; menulis melaluinya
  membaling `access violation writing 0x0000...`. Setiap fungsi Win32 mesti ada `argtypes`
  **dan** `restype`.
- **`\b` selepas kata dasar Melayu.** `\bcerah\b` tak padan dengan "cerahkan". Guna
  `cerah(?:kan)?` dan seasamanya untuk `terang`/`malap`/`gelap`.
- **`pr.slides[:n]` bukan objek slaid** — ia `list`. Akses indeks, bukan hirisan.
- **WebView2 sudah selesaikan unit CSS.** JS hantar `scale=1`; Python ukur
  `GetDpiForWindow/96` sendiri.
- **Konsol Windows cp1252.** Ujian yang cetak `✔`/`✖` perlu `PYTHONIOENCODING=utf-8`.
- **`@staticmethod` pada `_match_system`** menjadikan `self` hilang; `_find_doc` jadi
  `NameError` yang hanya muncul bila ayat itu benar-benar dihantar.
- **Satu tetingkap pywebview = puluhan HWND bertajuk sama.** Semuanya kelas
  `WindowsForms10.Window.8.app.*`, semuanya `GetParent() == 0`, semuanya
  `IsWindowVisible = True` dan pada rect yang sama. `FindWindowW`, `GetParent`, kelas
  dan tajuk **semua** gagal membezakan bingkai daripada anak. Untuk tetingkap
  pywebview, guna pemegang Python: `win.native.Handle` (`Api.web_hwnd()` /
  `Api.hud_hwnd()` membalutnya). `system.app_hwnd` hanya untuk app biasa.
- **Gelung `_emit("web", {"url": u})` → `stageWeb.open(u)` → `go()` → `web_open()`.**
  Panel WEB yang membuka URL sendiri tidak boleh menerima URL itu balik melalui
  saluran peristiwa. `web_open(url, notify=False)` dan `web_search(q, notify=False)`
  memutuskan gelung; pemanggil dari JS menghantar `false`, suara dan model kekal
  `true` supaya panel ikut bertukar. Gejala sebelum dibetulkan: 6 `web_open` dalam
  12 saat, handle bertukar setiap 1–2 saat, tetingkap bertindih atas stage.
- **`_closed()` menulenkan pemegang yang salah.** Callback `closed` dari tetingkap
  lama boleh mendarat selepas tetingkap baharu dibina. Semak
  `if self._web_win is not win: return` dahulu, jika tidak panel kehilangan browser
  yang sebenarnya masih hidup.
- **`win.events.closed.wait(3)` lebih jujur daripada memeriksa HWND.** `destroy()`
  hanya menjadualkan `Close()` pada GUI thread; menunggu HWND hilang gagal kerana
  maya HWND hantu kekal. `closed` diset dari `on_close()` selepas `FormClosed`.
- **`pane("web")` bukan `pane("browse")`.** `stageShow()` pulang senyap untuk nama
  panel yang tidak wujud, jadi ujian lulus tanpa menguji apa-apa. Harness `_live.py`
  sekarang membaca `document.body.dataset.pane` balik dan FAIL kalau tak padan.
- **`_live.py` mesti tulis hasil baris demi baris.** `win.destroy()` boleh tergantung
  dan proses tak pernah sampai ke penulisan akhir — versi pertama kehilangan semua
  keputusan sementara lapan PNG terselamat.

- **`#orbTasks` mesti duduk DALAM `.orb-box`, bukan di bawahnya.** Percubaan pertama
  menambat kad ke dasar kotak 250px dan ia menutup sfera. Penyelesaian: senarai
  mengalir ke kanan (`left: calc(50% + 108px)`), dan `.orb-box.has-tasks #orb`
  menggeser orb 72px ke kiri supaya dua-dua dapat ruang.
- **`done()` tidak boleh menukar favicon jadi tanda semak.** Ikon itu satu-satunya
  penanda jenis kerja — kalau dipadam, baris "connecting web" jadi baris pudar
  tanpa makna. Status siap dibawa opacity + titik sudut CSS (`.orbt.done .orb-ico::after`).
- **`const` peringkat atas dalam `<script>` TIDAK boleh dilihat dari `window.onClaude`.**
  `TOOL_LABEL` yang ditulis sebelum `const orbTasks` tetapi selepas IIFE lain
  menghasilkan `ReferenceError: TOOL_LABEL is not defined` hanya apabila tool betul-betul
  dipanggil. Ujian sentuhan DOM tidak menangkapnya — suapkan `window.onClaude('tool', …)`
  dalam harness, itu satu-satunya cara.
- **`js()` dalam `_live.py` tidak menunggu promise.** `evaluate_js` pulang nilai
  segerak; rantaian `.then()` perlu menulis hasil ke `window.__x` dulu, kemudian
  `time.sleep()` dan baca semula. Versi pertama pulang `{}` / `None` dan kelihatan
  seperti API rosak.
- **`_safe_path` dulu menolak folder shortcut.** Klik `Pictures` pada dock memaparkan
  "Folder luar kawasan kerja" kerana akar hanya workdir/ROOT/Desktop/Documents/Downloads.
  Sekarang `shortcuts.json` `folders` masuk senarai akar juga.
- **Ujian tetapan menulis ke `config.json` sebenar.** `_live.py` menulis
  `voice_rate` dan `reply_language`; kalau nilai asal berbeza, `git status` akan
  menunjukkannya. Semak `git diff config.json` selepas setiap larian hidup.

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

## Session 05 Nov — repo stats, motion graphics, projector follow

### What shipped
- `repo_stats` chat tool + `Api.repo_scan()` / `_repo_dashboard()`. Walks Home,
  Desktop, Documents, Downloads, Projects, source, dev, depth 4, skipping
  `REPO_SKIP`. Live count on this machine: 13 repos.
- `carries_data()` — a reply full of figures now routes into the analysis pane
  even when the question had no analysis keyword. Akmal's rule: data answer
  means drawn answer.
- `ana` pane: three drawing kinds (`bar`, `line`, `donut`). Line is a polyline
  revealed by `stroke-dashoffset`, donut by `stroke-dasharray` per slice. Both
  are CSS transitions, not rAF — see the trap below.
- Cards and charts reveal on their own stagger, independent of narration.
- Deck follow: `_deck` state, `_deck_step()`, `_deck_label()`, `stageDocs.slide()`.
  "next slide" advances the projector *and* the doc pane, and the pane shows the
  caption of the slide being presented.

### Traps hit this session
1. **`datetime` was never imported in `main.py`.** Every `_repo_shape` threw
   `NameError`, `repo_scan` swallowed it into the per-repo `error` field, and the
   dashboard rendered a confident wall of zeroes. A per-row try/except that
   stores the exception turns a hard crash into a wrong answer — the picture
   looked plausible, which is worse. Fixed with `from datetime import datetime`.
2. **Hermes-style heredoc strips `\b`.** Writing a regex through
   `python - <<'PY'` turns `\b` into a literal 0x08 byte before Python parses it.
   The block landed with four backspace bytes and every word-boundary regex went
   silently dead. Detect with `s.count("\x08")`; repair by replacing with `\b`.
   Write generators to a file with the Write tool, not through a heredoc.
3. **`el()` is scoped inside the docs IIFE.** The new `lineChart()` lives in the
   analysis IIFE and cannot see it — `ReferenceError: el is not defined`, caught
   only because the probe printed the stack. Use `document.createElement` in the
   analysis pane.
4. **`.aline .ax` never matched** — the axis div is appended to the chart box,
   not inside `.aline`. Labels rendered as run-together "w1w26".
5. **Charts stayed invisible when narration was interrupted.** Original reveal
   depended on a point targeting each chart. Now every card and chart reveals on
   a timer at render time; narration only adds the focus ring.
6. **`evaluate_js` throws on a JS exception** rather than returning a value.
   Wrap probes in `(()=>{try{...}catch(e){return e.message}})()`.
7. **`win.screenshot()` does not exist on pywebview 6.2.1 `Window`.** Use
   `PrintWindow(hwnd, hdc, 2)`; `ImageGrab` returns black for WebView2.
8. **A window can be minimised and report `-32000` coordinates.** Guard the
   `GetWindowRect` result before grabbing, or the PNG silently does not appear.

### Live probe scripts kept
- `ui/_deck_live.py` — 20 checks, builds its own 8-slide pptx and drives the
  whole follow path. Green.
- `ui/_live.py` — 63/63. `ui/_sys_e2e.py` — 46/46.

### Still open
- `_make_analysis`'s prompt still asks for "Bahasa Melayu Malaysia santai"
  instead of following `reply_language`.
- Deck follow is optimistic: clicking a thumbnail in PowerPoint desyncs the
  pane until a spoken slide number corrects it. A real fix needs UI Automation
  on the PowerPoint window, not a keystroke counter.

---

## Session 05 Nov (b) — fail/folder upload, measure, report

### What shipped
- **`inspect_path.py`** (new, no GUI deps). `inspect_file()` / `inspect_folder()`
  / `inspect()` / `dashboard()` / `listing()`. Measures with `os.scandir`; the
  model never touches a number.
- **`Api.pick_upload(kind)`** — `FileDialog.OPEN` (multi) or `FileDialog.FOLDER`,
  every returned path re-checked through `_safe_path`.
- **`Api._resolve_target(raw)`** — accepts a bare name ("Downloads") and finds
  it under the same roots `_safe_path` allows. Still fenced by `_safe_path`.
- **`Api.analyse_path(path, paths)`** — 1..12 targets, emits the same
  `present_analysis` payload shape `_repo_dashboard` uses, so `render()` draws
  it with no new UI. Also pushes a flat listing to DOK via `window.stageFeed`.
- **`Api._wire_drop(window)`** — registered as `webview.start(func, window)`.
  Creates a hidden sink element via `window.dom.create_element` and calls
  `sink.on('drop', ...)` so pywebview's `_dnd_state['num_listeners']` rises
  above 0; a bounded 0.4 s poll then drains `_dnd_state['paths']` and pushes
  real paths into the page. Bounded (18 000 iterations), not `while True`.
- **`analyse_path` chat tool** — "analisis folder Downloads" routes with no
  button. Returns exact measured lines to the model so the closing sentence
  cannot invent a figure.
- **DOK pane** — `File…` / `Folder…` buttons, drag veil, `.feed` table.
- **ANA cards** — `--card-hue` per card from a six-hue rotation (`HUE[]`),
  gradient-clipped value text. Manuel's standing rule: never one colour.
- **`MULA.md`** — new "Laporan fail atau folder" section + three new rows in
  the troubleshooting table.
- **`ui/_ip_test.py`** — 34 checks against a synthetic fixture with known
  counts, known duplicates, and a `node_modules` that must be ignored. Green.
- **`ui/_upload_live.py`** — 27 checks driving the real Api and reading the
  DOM back. Green. Screenshots `11-upload-listing.png`, `12-upload-report.png`.

### Traps hit this session
1. **An Edit anchor ate a `def` line.** Replacing `return out\n\n    def _doc_pdf`
   with a block that ended in `return out` silently deleted
   `def _doc_pdf(self, p, page=None):`, leaving its docstring floating under
   the previous function. Symptom: `AttributeError: 'Api' object has no
   attribute '_doc_pdf'` at `docs_open`, only on PDF. Fix: always grep the
   method name after inserting a block near another method. Guard now: an
   `ast` walk asserting every expected `Api` method still exists.
2. **`.acard` / `.apoint` are not the class names.** The analysis pane uses
   `.ana-card` / `.ana-point`. Probe selectors must be read off the render
   code, not guessed from the feature's name.
3. **The analysis pane's scroller is `.ana-shell`, not `.pane-body`.** A
   windowed `::-webkit-scrollbar` rule for it rendered as a grey slab; the rest
   of the HUD hides scrollbars entirely. Matched that convention instead:
   `scrollbar-width: none` + `::-webkit-scrollbar { display: none }`.
4. **`.ana-card b` was `var(--cyan)` for every card**, so four cards read as one
   colour. Gradient-clipped text also ignores `color`, so the `.focus` state
   must reset `background: none` *and* set `-webkit-text-fill-color`.
5. **`docs_open` is Python-only — it does not paint.** The DOM stays empty
   until JS calls `stageDocs.open(path)`. A probe that only calls `docs_open`
   and then checks for `#docBody img` will always fail.
6. **A native `drop` listener in the page is not enough.** No filesystem path
   reaches the page from a `File` object; pywebview's `FilesDropped` route is
   the only one that carries a real path, and it is gated on
   `_dnd_state['num_listeners'] > 0`, which only `element.on('drop', cb)` via
   `webview.dom` raises. Hence `_wire_drop` in Python, with the page pushing
   into `window.stagePick`.

### Baseline failures, NOT caused by this work
`ui/_live.py` reports 59 ok / 4 failed, and the same 4 fail with this session's
changes stashed (`git stash push main.py ui/stage.html`, re-run, pop):
- `imej pdf render` — the harness checks the image 1.6 s after
  `_open_doc_in_stage`, before the `evaluate_js` paint lands. PDF rendering
  itself verified independently: 1075×1521, page "1 / 8", one `#docBody img`.
- `stageApp.attach` / `rect host` / `host stage kelihatan` — needs a live
  Notepad HWND; the harness's `launch_app` does not leave one behind in a
  non-interactive run.

### Still open
- `_make_analysis`'s prompt still asks for "Bahasa Melayu Malaysia santai"
  instead of following `reply_language`.
- Deck follow is optimistic (unchanged).
- Drag-and-drop is wired but not proven end to end: a real `drop` through
  WebView2 needs a human hand on the mouse. The `File…` / `Folder…` buttons
  are the verified route.

---

## Session 05 Nov (c) — minimize button, and the room was too dark

### Minimize
`on('.iconbar button[title="Sembunyi"]', …)` had been hunting a title that no
longer existed — the button was translated to `title="Minimize"` and the
binding was never updated, so it attached to nothing and the click did
nothing. Bound to a class now (`button.min`), because a title is user-facing
copy and gets translated. Verified by clicking the real button and reading
`document.visibilityState === 'hidden'`, then restoring.

### Darkness — three layers, each chosen as if it were the only one
Measured, not guessed. Screen mean luminance was **24.5/255**, median **16**.

1. **`.glass` was redefined mid-stylesheet** with a hardcoded
   `linear-gradient(168deg, rgba(20,10,40,.80), rgba(9,4,20,.72))` that
   overrode the `--panel` token at line 33. This was the real culprit — the
   panels computed to roughly rgb(15,8,29), barely above the ground.
2. **`.vignette` was `rgba(0,0,0,.70)`** at the edges — a 70% black wash over
   the entire screen, permanently.
3. **`.scanlines` at `opacity: .32`** on top of both.

Now: panel fill rgb(48,30,84) @ .93, vignette .22, scanlines .09, ground
`#140d26` instead of `#05030f`, window `background_color` matched so the
first paint is not a black flash. Screen mean **46.7/255**, median **30**.

### Text was part of it
`--ink-dim #84a8b9` and `--ink-faint #43616f` were too dark to read on a
dark panel. Now `#a8c6d6` / `#85a3b1`. Contrast against the measured panel:
body **9.8:1**, secondary **6.2:1**, faint **4.1:1**.

### The lesson worth keeping
**A custom property that references one declared later at the same scope
resolves to nothing.** `--panel: rgb(var(--lift-top) …)` had to be moved
*below* `--lift-top` in `:root`. If a token change appears to do nothing,
check declaration order before checking anything else.

### Other fixes found while measuring
- `.btn.solid` inherited the bright `.btn` cyan on a bright gradient — the
  label was invisible in every state. Dark ink now, plus a hover stop.
- `.btn[disabled] { opacity: .38 }` made a filled button read as an empty
  box. Disabled now drops the fill and keeps readable text instead.
- Six `rgba(0,0,0,…)` wells migrated to a tinted `--inset` token, so recessed
  surfaces are a dark violet, never pure black.

### Probe kept
`ui/_ui_fix_live.py` — 11 checks: real pixels (mean/median luminance), WCAG
contrast on all three ink tokens, the minimize button clicked rather than its
API called, restore, and two other panes still lit. Green.

`ui/_upload_live.py` re-run after the theme change: 27/27, unchanged.

---

## Session 05 Nov (d) — the shortcut stopped opening Jarvis

### What he saw
"aku dah klik nk open jarvis, dia tak buka pun." Nothing. No window, no error,
no flash. Every click, forever.

### The cause — a mutex that outlived its window
`already_running()` created the named mutex `Local\JarvisDesktopHUD` and treated
`ERROR_ALREADY_EXISTS` as proof that someone else was serving a HUD. That is not
what a mutex means. It means *someone who created it is still alive* — whether or
not they still have a window.

At 13:22:31 a `pythonw` started. At 14:26 Manuel clicked the shortcut and
nothing happened. The process in between:

```
pythonw  pid=35040  hwnd=0  title=[]  cpu=1467.9s  started 5/11 13:22:31
```

No window at all. Two invisible helper windows (`class=G`, `class=I`) that
`EnumWindows` reports but no human can see, no title, nothing to restore. It held
the mutex anyway. So every new launch created the mutex, saw `183`, called
`FindWindowW(None, "Jarvis")`, found nothing — because the corpse had no window
to find — and returned `True`. A silent no-op at the first line of `main()`.

### Three faults stacked
1. **The mutex proved too much.** Existence ≠ a window. This is the bug.
2. **`_hud_hwnd()` only searched its own pid.** After the rewrite this showed up
   live: a second click was *blocked* by the lock instead of restoring the first
   window, because the lookup could never see another process's window. Blocked
   is the same silent no-op wearing a new coat. Caused by this session's first
   fix, not pre-existing — found only by clicking twice and reading the log:
   `blocked by pid 38156 (no window) — that process is stale` while pid 38156 had
   a perfectly good window.
3. **`launch.vbs` quoting.** `""""` emitted `command: "pyw.exe" ""main.py"` —
   doubled quote before a path with no spaces.

**Correction, measured not assumed.** I first claimed WebView2 renames the window
when `stage.html` sets `document.title = 'J.A.R.V.I.S — STAGE v1.1'`, and that
this is why `FindWindowW(None, "Jarvis")` found nothing. That is wrong.
`system.hud_hwnd("Jarvis")` returns a valid HWND, and `Get-Process` reports
`MainWindowTitle = Jarvis` on a healthy HUD. The title is stable. The soft
matching in `_hud_hwnd` is defence against a hardcoded string, not a fix for a
rename that never happened. The mutex was the whole cause.

Discovered only by clicking twice and reading `runtime/startup.log`:
`blocked by pid 38156 (no window) — that process is stale` while pid 38156 had
a perfectly good window.

### The fix
- **Lock is a pid, not a mutex.** `runtime/jarvis.lock` holds `{"pid", "started"}`.
  `_lock_owner()` validates the pid is alive *and* is running `main.py`, so a dead
  pid and a reused pid both read as "no owner". A stale lock can therefore never
  veto a launch.
- **A window is the proof.** `already_running()` enumerates windows across every
  pid running `main.py` and accepts any title containing `JARVIS` or `STAGE`.
  Restores if iconic, shows if hidden, foregrounds either way.
- **No more silent exits.** A live Jarvis with no window now asks one question:
  end it and start fresh? Yes reaps it, No exits. A crash inside `main()` puts the
  last traceback line in a `MessageBoxW` — the one channel `pythonw` cannot swallow.
- **`runtime/startup.log`** gets one line per launch: `start`, media URL,
  `webview.start`, `gui loop returned`, `exit`, or `CRASH` + traceback. This is
  the whole diagnosis path for next time.
- **The process cannot outlive its window.** After `webview.start()` returns,
  `_drop_lock()` then `os._exit(0)` — a non-daemon recorder thread can no longer
  pin a windowless process holding the lock.
- **`launch.vbs` quoting made explicit** via `q = Chr(34)`. The `""""` form emitted
  `command: "pyw.exe" ""main.py"` — doubled quote before the path, and a path
  with no spaces turns a stray quote into a literal filename character.

### Verified
- `ui/_launch_test.py` — 27 checks, hermetic (no HUD needed, works with one open).
  Stale-by-death, stale-by-pid-reuse, corruption, live block, self-reap refusal.
- `ui/_launch_live.py` — 18 checks against a real running HUD: restore, minimize
  → restore, reap an orphan, crash log.
- End to end through `C:\Users\akmal\Desktop\Jarvis.lnk`: launch 1 writes three
  log lines and paints (screenshot `ui/_launch-proof.png`); launch 2 writes
  `hud already up: hwnd=6690256` and spawns nothing.

### Trap for next time
A probe that asserts "no HUD exists" fails the moment Manuel has the HUD open.
Scope window assertions to a pid you control (`_hud_hwnd([some_pid])`) or branch
on the result. Two "regressions" in `_launch_test.py` were the suite being
non-hermetic, not the code being wrong.

### Still open
- The corpse is gone and the gate is fixed, but the *original* reason pid 35040
  hung with no window was never reproduced. `os._exit(0)` and the crash dialog
  close the silent shape of it; if it recurs, `runtime/startup.log` will now say
  whether it died in `webview.start` or after `gui loop returned`.

---

## Session 05 Nov (e) — "cari lagu, lepas tu main" played nothing

### What he saw
Asked Jarvis to find a song on YouTube, then told it to play. Nothing played.

### Three separate breaks, measured not guessed
Probed the real model (`ui/_yt_route.py`) with his two exact messages:

```
USER: cari lagu hindia secukupnya dalam youtube
  tools offered: web_search,…,control_pc,open_media    <- no YouTube tool existed
  CALLED: web_search  (then, in the first run) open_media {}
  RESULT: Tool gagal: 'name'
```

1. **No tool could play YouTube.** `open_media` is "play a file in media/ on this
   disk". The model reached for it because nothing else claimed the words *lagu,
   main, play* — and it then listed an empty folder. The WEB pane's embed code was
   correct all along (`ui/_yt_live.py` proves a watch URL becomes a playing embed
   with the right referrer); nothing could reach it from chat.
2. **`open_media {}` crashed.** `chk_tool` built its reply with `res['name']`, but
   `media_list()` returns `{"ok":True,"items":[…]}` — no `name`. With a non-empty
   `media/` this raised `KeyError: 'name'`, so the tool loop died instead of
   answering. This is why "main lagu tu" produced no visible failure at all.
3. **Search rows under the orb were inert.** `orbTasks.items()` built a `DIV` per
   result, attached a favicon, appended the text, and stopped. No click handler,
   no `data-url`, no role. A video link could be found and read but never opened
   — the visible half of the same dead end.

### The fix
- **`play_youtube`** — resolves a song to a real watch id via Serper with
  `site:youtube.com/watch` (plain web search returns channel homepages and
  playlists, which carry no video id and cannot embed), de-duplicates by id,
  ranks by token overlap with the query, then `_emit("web", {url})` so the pane's
  existing embed path plays it. Verified: `Hindia Secukupnya` → `kcc9Kfip2uw`,
  and the live page title confirms it is the actual song.
- **Trigger tuned** to the words that mean YouTube — `youtube`, `lagu`, `muzik`,
  `main`, `play`, `putar`, `pasang`, `lagu tu`. Proven by re-running the route
  probe: turn 1 now calls `play_youtube` and reports it is playing; turn 2
  ("main lagu tu") correctly calls nothing because it already is.
- **`open_media` crash fixed** — a bare listing returns the file names and points
  at `play_youtube`; only a named hit reads `res['name']`.
- **Rows are links** — `.it.link` gets `data-url`, `role=link`, `tabIndex`, and a
  click/Enter handler that switches to the WEB pane and opens the url. Styled as
  a link so it reads as one instead of being a coincidence of the cursor.
- **`notPlayable()`** gives a tooltip explaining that a channel page or playlist
  has no video id and will open in a window — the difference between "playing in
  the stage" and "silently opened elsewhere" is otherwise invisible.
- **`clean_yt_title()`** strips ` - YouTube` and credit parens like
  `(Official Lyric Video)` while keeping real subtitles such as
  `[Remastered In 4K]`, so a row shows the song rather than 90 characters of
  credits that ellipsise before the identifying part.

### Verified
`ui/_yt_live.py` — 15/15: title cleaning, `play_youtube` resolves and the pane
embeds that exact id, badge on, stage switches to `data-pane=browse`, rows carry
`data-url` and `role=link`, a real click loads the video, a channel row is
present and clickable.
`ui/_yt_route.py` — the real model, real tools, real history.
Regression: `_launch_test.py` 27/27, `_ip_test.py` 34/34.

### Trap for next time
The model's tool choice is decided by the *descriptions and the trigger regex*,
not by what the code can do. "lagu" appeared in both `open_media` and
`play_youtube` triggers; the model picked the wrong one because `open_media` was
the only tool whose description mentioned playing. When a spoken follow-up does
the wrong thing, log `tool_calls` before touching anything else — the routing is
in the prompt, not in the handler.
