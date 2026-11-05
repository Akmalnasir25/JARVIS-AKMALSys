# MULA — panduan uji penuh

Klik ikon **Jarvis** atas Desktop. HUD buka skrin penuh, tiada tetingkap konsol.

---

## Melancarkan Jarvis

| cara | bila guna |
|---|---|
| ikon **Jarvis** atas Desktop | kegunaan harian |
| `python main.py` dari folder projek | bila HUD tak naik dan kau nak baca error |
| `cscript //nologo launch.vbs --check` | tanya Python mana yang akan dipakai, tanpa mula HUD |

Desktop shortcut menunjuk ke `launch.vbs`, bukan ke path Python. `launch.vbs`
cari Python setiap kali ia dijalankan, ikut urutan: `pyw.exe` pada PATH →
`pythonw.exe` pada PATH → `%LOCALAPPDATA%\Python\pythoncore-*\pythonw.exe`
→ `%LOCALAPPDATA%\Programs\Python\Python*\pythonw.exe`. Jadi upgrade Python
tak mematikan shortcut, dan projek boleh dipindah ke folder lain tanpa edit apa-apa.
Kalau tiada Python langsung, ia berhenti dengan dialog yang menyebut apa yang dicari.

`pythonw` telan semua traceback. Bila HUD tak naik dan tak ada apa berlaku,
jalan `python main.py` — di situ kau nampak sebab sebenar. Setiap pelancaran
juga menulis satu baris ke `runtime\startup.log`; kalau log itu berhenti pada
`start`, masalahnya sebelum tetingkap; kalau berhenti pada `webview.start`,
masalahnya dalam WebView2. Kalau `main()` sendiri meletup, dialog muncul dengan
baris terakhir traceback — bukan senyap lagi.

Klik kedua tak buka tetingkap baru. Ia cari tetingkap HUD yang betul-betul ada
dan bawa ke depan. Kalau ada Jarvis yang masih bernyawa tetapi tetingkapnya
sudah hilang, ia tanya sama ada nak tamatkan proses itu dan mula semula —
tidak lagi keluar senyap.

### Autostart

```
cscript //nologo autostart.vbs --install     letak dalam Startup folder
cscript //nologo autostart.vbs --status      semak
cscript //nologo autostart.vbs --remove      buang
```

Per-user, tiada admin, tiada registry. Ia tulis satu `.lnk` dalam
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` yang menunjuk ke
`launch.vbs` — jadi autostart tahan upgrade Python sama seperti ikon Desktop.

Sembilan panel. Tekan nombor **1–9** atau klik rail kiri. `Esc` tak menutup apa-apa;
tutup dengan butang tetingkap.

---

## 1 · COMMS — orb, suara, chat

| cuba | apa yang patut jadi |
|---|---|
| taip `status laptop` | panel tak bertukar, balasan dalam satu baris: volume, kecerahan, tetingkap |
| taip `volume 30` | volume betul-betul jadi 30%, **tanpa** lag model |
| taip `cerahkan skrin` | kecerahan naik 10% |
| taip `tutup notepad` | prompt kuning **"⚠ Tutup tetingkap?"** dengan dua butang — tekan **Tak** untuk uji batal |
| tekan mic, cakap `Hey Akmal` | orb masuk mod listening, kemudian transkrip |
| taip `apa khabar` | model chat jawab (`rootsys.cloud`, deepseek-v4.1-flash) |
| taip `senaraikan Downloads` | senarai tugas muncul di **kanan orb**: jenis kerja, subjek, dan nama item |
| taip `cari harga minyak` | baris **connecting web** dengan favicon laman, tajuk tiga sumber teratas |
| tekan gear ⚙ di bar atas | sheet **TETAPAN** terbuka — model, suara, rate, pitch, bahasa, baca-balasan |
| tukar apa-apa dalam TETAPAN | kaki sheet tulis **disimpan**; label suara di rail ikut serta-merta |
| isi rate `8` (tanpa +%) | medan jadi merah, kaki tulis **ikut bentuk +8%** — nilai tak disimpan |

### Orb bercakap

Orb ada empat keadaan asas: `standby`, `mendengar`, `berfikir`, `bercakap`.
Di sebelah kanannya, senarai tugas mengalir semasa kerja berjalan:

| jenis | rupa |
|---|---|
| `membaca fail` | ikon fail |
| `menyemak folder` | ikon folder + nama enam entri pertama, `+N lagi` kalau lebih |
| `connecting web` | favicon laman sebenar, kemudian tajuk tiga sumber teratas |
| `menjalankan arahan` | ikon kod |

Baris yang siap jadi pudar dengan titik hijau di sudut ikon — favicon kekal,
supaya Akmal masih nampak "ini carian web tadi". Bila ada senarai, orb bergeser
72px ke kiri supaya dua-dua dapat ruang.

Nota: `config.json` ada `"reply_language"`, `"speak_replies"`, `"voice"`,
`"voice_rate"` dan `"voice_pitch"`. Semua boleh ditukar dari sheet TETAPAN —
tukar serta-merta, tak perlu restart.

---

## 2 · MEDIA — video, seek, range server

Ada satu fail ujian: `showreel-30s-uji.mp4` (6 saat, 735 KB).

1. Klik fail dalam senarai kanan.
2. Video main. **Tarik scrub bar** — itu yang membuktikan `206 Partial Content`
   berfungsi; tanpa Range, video tak boleh seek langsung.
3. Tukar ke panel lain. Audio mesti **berhenti**, bukan terus main di latar.
4. Balik ke MEDIA — posisi kekal.

Letak fail sendiri dalam `media/` (mp4, mkv, webm, mov, avi, mp3, m4a, flac, wav, opus).

---

## 3 · TERMINAL — kerja Claude Code

Taip arahan dalam kotak bawah. Setiap tool call muncul baris demi baris.
Contoh: `senaraikan fail dalam Downloads dan cari yang lebih 50 MB`.

---

## 4 · FAIL — pelayar + pratonton

Panel kiri folder, kanan pratonton. Fail teks boleh dibuka terus;
butang **Edit** hantar ke editor.

---

### Dock bawah

Tiga tab: **DESKTOP · N**, **APPS**, **FOLDER**. Tile dibina dari apa yang
benar-benar ada pada mesin ini, bukan markup tetap — Desktop sebenar, 13 app
dari `shortcuts.json`, 7 folder. Klik folder → masuk panel **FAIL** HUD sendiri,
bukan tetingkap Explorer bertimbun. Klik app → dilancarkan. Tile yang sasarannya
tiada pada mesin ini kelihatan pudar dan berkata begitu bila diklik.

---

## 5 · EDITOR — CodeMirror

Buka fail `.py`, ubah, **Ctrl+S**. Tiga pagar:

- fail berubah di luar semasa awak edit → tulis ditolak, minta tekan Simpan sekali lagi
- `.bak` dibuat sekali sebelum tulis
- fail > 200 KB ditolak, bukan diedit separuh

---

## 6 · WEB — dua jalan render

Taip `example.com` dan Enter.

| butang | apa yang jadi |
|---|---|
| (lalai) | tetingkap WebView2 berasingan, diletak atas rect stage |
| **Embed** | iframe dalam stage — sesetengah laman sekat, jadi kosong |

Tukar panel: tetingkap **diparkir**, bukan dimusnahkan. Balik ke WEB — laman sama,
posisi skrol sama. Butang **×** yang musnahkan.

### Lagu YouTube

Cakap `cari lagu Hindia Secukupnya` atau `main lagu tu`. Jarvis cari di YouTube,
pilih video yang boleh dimainkan, dan mula main **di dalam panel WEB** — tiada
Chrome, tiada tab baru.

| apa yang awak nampak | maksudnya |
|---|---|
| badge **YT** menyala | video itu dimainkan sebagai embed dalam stage |
| baris hasil carian berwarna dan boleh diklik | klik terus untuk main; `Enter` pun boleh |
| baris tanpa warna | halaman channel atau senarai main — tiada video id, jadi ia buka dalam tetingkap. Tooltip kata kenapa |
| **Video unavailable** | embed ditolak. Tekan butang **Chrome** dalam bar WEB — Chrome sebenar dibuka dan diletakkan di dalam stage, dan ia main sepenuhnya |
| tetingkap Chrome dalam stage | awak boleh tekan, skrol, tukar tab seperti biasa; `Release` mengeluarkannya semula jadi tetingkap biasa |

**Kenapa ada dua jalan.** Embed boleh gagal atas dua sebab yang kelihatan sama
pada skrin: pemilik video tak benarkan embed, atau WebView2 menolak permintaan
itu. Kedua-duanya keluar sebagai "Video unavailable" yang sama, dan tiada apa
yang boleh dibaiki dari dalam kod kita — jadi butang Chrome menyelesaikannya
tanpa perlu tahu sebabnya. Ia bukan jalan utama; ia jalan keluar.

Satu perkara yang diukur: video itu sendiri **boleh** di-embed. Endpoint oEmbed
YouTube (`/oembed?url=...&format=json`) pulangkan HTTP 200 untuk setiap calon
id, jadi penolakan itu berlaku di sebelah WebView2, bukan pada video.

Tool yang mengendalikannya ialah `play_youtube`, bukan `open_media`. `open_media`
hanya untuk fail dalam folder `media/` pada PC ini. Sebelum ini tiada tool untuk
YouTube langsung, jadi `main lagu tu` jatuh ke `open_media` dan menyenaraikan
folder kosong — itulah sebabnya tiada apa yang bermain.

Satu perkara yang diukur, sebab ia mudah disalah sangka: satu tetingkap pywebview
menghasilkan **puluhan** HWND dengan tajuk yang sama, semuanya tanpa ibu dan
semuanya `IsWindowVisible = True`. Jadi jangan sesekali percaya gelintar tajuk
apabila menyemak "tetingkap ini hidup ke tidak". Python menyimpan pemegang
`Window` itu sendiri; itulah satu-satunya sumber yang tepat.

Dan satu lagi, khusus Chrome: Chrome berkongsi **satu** proses pelayar. Bila
Chrome sudah berjalan, `chrome.exe --new-window` hanya menyuruh proses sedia ada
membuka tab, dan proses yang baru dilancarkan itu **terus keluar tanpa tetingkap**.
Jadi mencari tetingkap ikut pid yang kita lancarkan tidak pernah berjaya pada
kes itu. Yang dipakai ialah beza-set: ambil senarai tetingkap sebelum, lancar,
kemudian ambil sekali lagi — yang baru muncul itulah tetingkapnya.

### Mic dan "Hey Jarvis"

Butang **chip di kanan atas** (dan baris `wake` dalam Channels) ialah suis mic,
bukan bacaan status. Ia menunjukkan keadaan sebenar aliran audio.

| apa yang awak nampak | maksudnya |
|---|---|
| dot hijau, **HEY JARVIS** | mic terbuka, Jarvis mendengar "Hey Jarvis" |
| dot amber, **MIC OFF** | mic **tertutup sepenuhnya** — tiada bunyi bilik diproses |
| klik chip | tukar antara dua keadaan itu, serta-merta |

Bila ia `MIC OFF`, menekan butang mic masih boleh bercakap seperti biasa — satu
tekanan, satu arahan. Pilihan itu disimpan dalam `config.json`, jadi ia kekal
selepas Jarvis dimulakan semula.

Satu perkara yang diukur: versi pertama suis ini hanya menulis `config.json`,
sedangkan gelung mic membaca fail itu **sekali sahaja** semasa mula. Menghidupkan
semula "Hey Jarvis" tak berkesan sehingga restart. Sekarang gelung itu membaca
semula setiap setengah saat dan membina semula model bila dihidupkan.

---

## 7 · DOK — dokumen dalam stage

Empat format dihurai **dalam Python**, bukan dalam browser:
pdf (pymupdf), docx (python-docx), xlsx/xlsm (openpyxl), pptx (python-pptx),
tambah csv/md/txt/json.

1. Klik satu pdf → halaman render sebagai imej 130 dpi.
2. Anak panah kiri/kanan untuk tukar halaman (atau `←` `→` bila panel fokus).
3. Penapis kiri: recent / pdf / docx / xlsx.
4. Atau cakap/taip: **`buka laporan.pdf`** — Jarvis cari dalam workdir, Desktop,
   Documents, Downloads, dan buka terus dalam panel ini.

### Laporan fail atau folder

Tiga jalan masuk, satu laporan:

| Jalan | Cara |
|---|---|
| **File…** | Klik, pilih satu atau banyak fail dalam dialog Windows |
| **Folder…** | Klik, pilih satu folder |
| **Seret-lepas** | Seret fail/folder dari Explorer ke atas HUD |

Ketiga-tiganya berakhir pada `Api.analyse_path()`, jadi laporannya sama.
Fail contoh: **`analisis folder Downloads`** — Jarvis faham laluan yang disebut
dan terus mengukur.

Angka diukur dengan `os.scandir`, bukan dianggarkan oleh model:

- bilangan fail dan folder, jumlah saiz, purata per fail
- pecahan jenis (kod, imej, dokumen, video, arkib…) sebagai donut
- kiraan dan saiz ikut sambungan sebagai bar
- umur fail: < 1 minggu, 1–4 minggu, 1–6 bulan, 6–12 bulan, > 1 tahun
- 12 fail terbesar, fail kosong, tarikh fail terbaru dan tertua
- **fail berganda** — saiz sama disahkan dengan hash 64 KB pertama
- kata yang paling kerap muncul dalam nama fail

Folder `node_modules`, `.git`, `__pycache__`, `dist`, `build`, `.venv` dan
seumpamanya **dilangkau**: 40 ribu fail dependency tidak menceritakan apa-apa
tentang projek yang memilikinya. Had 120,000 fail — bila had itu dicapai,
laporan menyebutnya, kerana angka yang terpotong mesti diakui, bukan
dibulatkan diam-diam.

Satu fail pula dibaca sifatnya: saiz, jenis, hash, bilangan baris dan perkataan
(jika teks), pengkodan, dan tarikh ubah suah.

Senarai penuh fail dipaparkan dalam panel DOK sebagai jadual — nama, jenis,
saiz, tarikh — dihantar melalui `window.stageFeed()`.

**Had ruang kerja masih terpakai.** Memilih fail sendiri bukan alasan untuk
melangkau `_safe_path`: dialog boleh dihantar ke mana-mana folder melalui
kotak alamatnya, jadi sempadan workdir / Desktop / Documents / Downloads /
`shortcuts.json` masih diperiksa selepas pilihan. Laluan di luar itu ditolak
dengan sebab, bukan didiamkan.

---

## 8 · ANA — dashboard analisis

Minta analisis dalam COMMS, contoh:
`analisis folder Downloads, fail apa yang paling besar dan berapa jumlah saiz`.
Jawapan ditukar jadi kad + graf bar, dan dibacakan satu-satu.

---

## 9 · NATIVE — app asal masuk stage

1. Buka Notepad (atau Chrome, atau apa-apa app).
2. Panel NATIVE → **Imbas semula** → klik tetingkap.
3. App masuk ke dalam stage, masih hidup sepenuhnya — menaip dalam Notepad berfungsi.
4. Tukar panel: app **disembunyikan** automatik. Balik: muncul semula.
5. **KELUARKAN**: app dipulangkan ke desktop dengan saiz, gaya dan ibu asalnya.

---

## Kawalan laptop — senarai ayat

Semua ini jalan melalui resolver, bukan model. Laju, dan tiada lag.

```
status laptop                    volume 40 / naikkan volume / turunkan bunyi
mute / unmute                    cerahkan skrin / malapkan skrin / kecerahan 50
buka chrome                      fokus chrome / minimize chrome / maximize chrome
tutup chrome          ⚠        senarai tetingkap
senarai proses                   kill chrome           ⚠
run ipconfig                     run ping 8.8.8.8
salin <teks> / baca clipboard    kunci laptop
sleep                 ⚠          restart               ⚠
shutdown              ⚠          buang fail ke recycle bin  ⚠
buka example.com                 buka laporan.pdf
```

⚠ = perlu sahkan. Prompt muncul dengan dua butang dan token 90 saat. Kalau awak
taip/cakap `ya` dalam masa itu, ia terus jalan. Kalau `tak`, token dibuang.

**Yang sengaja tak dibenarkan:** shell bebas. Hanya senarai putih —
`ipconfig`, `systeminfo`, `tasklist`, `ping`, `tracert`, `nslookup`, `netsh wlan`,
`powercfg`, `wmic`, `dir`, `ver`, `vol`, `get-*`. Rantaian (`&&`, `|`, `>`) ditolak
sebelum sempat jalan.

---

## Kalau ada yang tak kena

| gejala | punca biasa |
|---|---|
| video tak boleh seek | bukan salah server — semak `media_server.py` masih hidup |
| app terapung atas panel lain | `stage:change` listener hilang dari `stageApp` |
| suara keluar English | `reply_language: "en"` dalam `config.json` |
| TTS guna edge, bukan Google | kunci `google_tts_api_key` — semak `secrets.json` |
| `create_window` gagal | pywebview mesti 6.x; semak `python -c "import webview"` |
| klik ikon, tiada apa berlaku | baca `runtime\startup.log` — baris terakhir beritahu di mana ia berhenti |
| "another Jarvis is starting up" | pelancaran kedua semasa yang pertama masih naik; tunggu sekejap |
| seret-lepas tak buat apa-apa | WebView2 tidak menghantar laluan; guna **File…** / **Folder…** |
| Web / YouTube kata "Video unavailable" | tekan butang **Chrome** dalam bar WEB; embed ditolak, Chrome tidak |
| "Hey Jarvis" menyambar suara orang lain | klik chip **HEY JARVIS** jadi **MIC OFF**, atau `wake_word: false` |
| chip kata MIC OFF tapi mic masih terbuka | bukan chip itu — semak aplikasi lain dalam Settings › Privacy › Microphone |
| "outside the workspace" | laluan di luar workdir/Desktop/Documents/Downloads — tambah dalam `shortcuts.json` |
| laporan kata "stopped after 120,000 files" | folder itu memang sebesar itu; had dalam `inspect_path.MAX_ENTRIES` |
