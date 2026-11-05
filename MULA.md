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
jalan `python main.py` — di situ kau nampak sebab sebenar.

Klik kedua tak buka tetingkap baru: mutex `Local\JarvisDesktopHUD` mengesan
Jarvis yang dah berjalan dan restore tetingkap sedia ada.

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

Satu perkara yang diukur, sebab ia mudah disalah sangka: satu tetingkap pywebview
menghasilkan **puluhan** HWND dengan tajuk yang sama, semuanya tanpa ibu dan
semuanya `IsWindowVisible = True`. Jadi jangan sesekali percaya gelintar tajuk
apabila menyemak "tetingkap ini hidup ke tidak". Python menyimpan pemegang
`Window` itu sendiri; itulah satu-satunya sumber yang tepat.

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
