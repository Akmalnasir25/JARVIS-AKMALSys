# MULA — panduan uji penuh

Jalankan `python main.py` dari `C:\Users\akmal\jarvis-desktop`, atau klik ikon
**Jarvis** atas Desktop. HUD akan buka skrin penuh.

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

Nota: `config.json` ada `"reply_language": "en"`, jadi jawapan model keluar dalam
English. Tukar ke `"ms"` dalam panel Settings kalau nak BM — tukar serta-merta,
tak perlu restart.

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
