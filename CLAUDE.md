# CLAUDE.md — Jarvis Desktop

> Fail ni untuk sesi seterusnya. Baca ni dulu, baru buka kod.
> `NEXT_SESSION.md` simpan nota teknikal panjang (sejarah lama). Ni yang ringkas: kedudukan
> sekarang, apa yang dah jalan, apa yang belum, dan perangkap yang dah makan masa.

**Dikemas kini:** 2026-11-08 · lepas commit `cf482d6`

---

## 1. Apa benda ni

HUD desktop untuk Akmal (guru, pemimpin Pengakap, pembangun projek web *.akmalsys.com).
**Jarvis panggil dia "Tuan"** — nota lama yang sebut "Sir" ialah sejarah, bukan arahan.
Python + pywebview (WebView2), satu halaman `ui/stage.html` (~430 KB, satu `<script>` inline
utama), backend `main.py` (~6,400 baris, ~238 method dalam `Api`). Dua otak:
- **Chat** (`_run_chat`): model rootsys (DeepSeek) dengan tool OpenAI-style. `tools_for()`
  tapis tool ikut `TOOL_TRIGGERS` (regex) supaya API tak lambat.
- **Claude Code** (`_run_claude`): `claude -p` stream-json untuk kerja PC/coding/projek.
  Model & effort dari config (`model`, `effort` → `--model`, `--effort`).
- `pickEngine()` di UI: arahan mesej/Telegram **sentiasa** ke chat (`MSG_TASK`), kerja PC
  (`PC_TASK`) ke Claude, selain itu chat.

**Jalan:** `python main.py`, `launch.vbs`, atau tugas berjadual **Jarvis**
(log masuk + buka kunci + bangun dari sleep, `main.py --ensure`, restart 3× bila crash).
`--ensure` keluar senyap jika Jarvis sudah hidup (lock `runtime/jarvis.lock`).
Restart manual: `Stop-Process` pythonw main.py → `schtasks /run /tn Jarvis`;
semak `runtime/startup.log`. **Restart hanya bila Tuan minta** (auto-mode menyekat).

---

## 2. Peta fail

| Fail | Baris | Apa dia buat |
|---|---|---|
| `main.py` | ~6,440 | `Api` — jambatan JS↔Python, tool chat, `resolve_system` (arahan tanpa AI), mic/wake, STT |
| `extras.py` | ~730 | memori, Calendar, draf Gmail, dokumen Word/PDF, sijil, rutin, pantau laman, deploy, backup, Malwarebytes, Canva |
| `phone_web.py` | ~1,330 | app fon (PWA) di `jarvis.akmalsys.com`: halaman, API, Files, Screen + kawalan, push |
| `meeting.py` | ~210 | rakam mesyuarat (mic + loopback WASAPI) → Opus → Gemini nota |
| `voiceprint.py` | ~80 | cap suara "Hey Jarvis" (openWakeWord custom verifier) |
| `phone.py` | ~210 | bot Telegram @JarvisAkmal_bot (fon → laptop) |
| `telegram_user.py` | ~580 | Telethon atas akaun Tuan — inbox, hantar, `listen()` mesej masuk |
| `system.py` | ~1,040 | kawalan laptop: volume, kecerahan, tetingkap, proses, shell senarai putih |
| `services.py` | ~540 | kekunci media, TTS strim, cuaca/solat, `screenshot(path, hide=True)` |
| `media_server.py` | ~250 | pelayan HTTP tempatan untuk `media/` + `ui/` (HUD dimuat dari `/stage?theme=`) |

**10 pane HUD:** `comms` `media` `term` `files` `editor` `browse` `docs` `ana` `native` `inbox`.

---

## 3. Yang siap dan hidup (ringkas, ikut kawasan)

**HUD**
- Orb: 5 lapisan kanvas (`#orb` dail, `.orb-layer.red`/`.gold` cincin Iron Man diwarnakan
  `tint()` multiply dalam kanvas, `.sph` sfera emas ala JARVIS/Vision ikut `--orb-core`
  tema, `.top` logo+kaca). Thinking: sfera pecah/kembang, cincin luar kembang & pecah.
- Tema: Purple (`asal`), Stark, Inferno, Mark — `html[data-theme]`, butang 🎨, arahan
  "tema …", simpan `config.theme`, dihantar dalam URL supaya skrin permulaan betul.
- Skrin permulaan akmalsys.com (bar kemajuan ikut langkah `boot()` sebenar).
- Panel 3D terapung, tiub telemetri kaca, kad tugas dengan ikon laman sebenar.
- History sesi (`chat_history.json`) + padam (butang tong merah, klik dua kali).
- Mod projek: chip projek, `Δ` diff overlay + commit setempat (`project_diff/commit`).
- Mod perbualan: arahan dari suara → selepas jawapan dibaca, mic dibuka ~6 s (`listen_followup`).

**Suara**: STT Gemini (`gemini-3.1-flash-lite`, thinking minimal) dengan pengawal senyap +
had panjang; Google/Whisper sandaran. `STT_WORDS` = ejaan rujukan (akmalsys, eLawatan…).
Wake word + cap suara pilihan ("daftar suara"; ambang naik ke 0.6 bila aktif).

**App fon — `https://jarvis.akmalsys.com`** (`phone_web.py`)
- Cloudflare Tunnel **`jarvis`** (`~/.cloudflared/jarvis.yml`, dimulakan oleh Jarvis;
  tunnel `sipeng` berasingan, JANGAN sentuh) → `127.0.0.1:8765`.
- Kunci: Cloudflare Access (nama pasukan dalam `config.phone_web_team`, polisi e-mel Tuan). JWT
  `Cf-Access-Jwt-Assertion` disahkan RS256 dengan kunci awam pasukan. E-mel Tuan sah →
  masuk; Service Token (Shortcut iOS) → perlu juga `X-Jarvis-Key`. Tanpa Access = 404.
- Orb HUD yang sama (kod diambil dari stage.html semasa dihidang), tekan-tahan untuk
  bercakap, UI Bahasa Inggeris, projek/Δ/commit, History, ＋ New (segerak dua hala).
- ☰ Menu: Files (baca sahaja, live, auto-refresh 4 s, NEW, Range untuk video),
  Screen + **kawalan penuh skrin** (ketuk/klik, dua kali, tahan = klik kanan, cubit zum,
  papan kekunci), Controls, Send file (→ Downloads\Jarvis Uploads), Daily brief,
  Notifications (Web Push, VAPID dalam `runtime/`), Model (Claude model/effort), Reload.
- Muat semula sendiri bila versi berubah (`page_version`), kecuali semasa merakam/menaip.
- Tailscale masih disokong sebagai sandaran (ikat pada IP 100.64/10 sahaja).

**Telegram**: hantar = draf + "ya" (`_pending_tg`, TTL 120 s). Mesej peribadi masuk →
kad HUD + notifikasi. **Auto-draf** (Inbox, suis per chat, `config.tg_autodraft`): draf
sahaja, tak pernah hantar tanpa "ya"; 45 s jarak, 6/jam. Pautan dalam mesej masuk →
Malwarebytes di latar (domain dipercayai dilangkau, cache 24 j, 20/jam) → amaran fon.

**Kerja harian (`extras.py`)**: memori (`memory.json`), Google Calendar (penyambung
Claude — **perlu Tuan Connect di claude.ai**), draf Gmail (tiada tool send), surat rasmi
Word+PDF (`Documents\Jarvis Dokumen`), sijil berkelompok Excel+templat `{{Lajur}}`
(`Documents\Jarvis Sijil`), rutin (`routines.json`), pantau 7 laman *.akmalsys.com
(5 min, amaran selepas 2 gagal), deploy Firebase (9 projek, perlu "ya"), backup robocopy
mingguan ke `OneDrive\Jarvis Backup` (tanpa node_modules/.git/rahsia), Canva
(`Documents\Jarvis Canva`).

**Lain-lain**: pembantu mesyuarat ("mula/tamat rekod mesyuarat"), senarai main YouTube
("main 5 lagu X", ke MEDIA), carian PC+Drive serentak (`find_anywhere`), dashboard
automatik bila data jadual dibaca, ikon taskbar (AppUserModelID + WM_SETICON).

---

## 4. Belum siap / perlu tindakan Tuan

| Benda | Status |
|---|---|
| Google Calendar | kod siap; Tuan mesti **Connect** di claude.ai → Settings → Connectors |
| Kepala surat rasmi | tempat kosong `[Nama]`; tunggu nama/jawatan/sekolah (`config.doc_sender`) |
| Shortcut iOS | `/api/ask` siap; Tuan memilih PWA sahaja — tak perlu dikejar |
| Ejen VPS | dibincang, Tuan tiada VPS lagi. Reka bentuk: VPS = pusat, laptop = ejen |
| WhatsApp | Tuan tolak (item 10). Jangan bina |
| Multi-tab editor | ditangguh oleh Tuan. Jangan bina |
| `ui/stage.html.bak`, `ui/_orb_lab.html` | sisa lama, padam bila Tuan setuju |

---

## 5. Garisan yang tak bergerak

**Fail yang JANGAN sesekali commit** (dalam `.gitignore`): `secrets.json` · `*.key` · `.env` ·
`cache.json` · `sessions.json` · `chat_history.json` · `memory.json` · `routines.json` ·
`runtime/` (VAPID, push_subs, startup.log, rakaman) · `media/`.
**`config.json` jangan di-commit** melainkan diminta — ia ada tetapan peribadi Tuan
(wake_word, theme, domain, e-mel). Repo **AWAM**: imbas diff untuk rahsia sebelum setiap push.

**Pengesahan sebelum tindakan luar** — dikuatkuasakan dalam kod, bukan prompt:
Telegram hantar & auto-draf → "ya"; e-mel → draf sahaja (tool send tak diberi); deploy →
"ya"; lock/sleep dari fon → confirm di fon; Malwarebytes → semak sahaja (tool report tak diberi).

**App fon:** `_sensitive()` sembunyi & 404 fail rahsia walaupun dalam folder dibenarkan
(secrets.json, .env, kunci, token/credential, .git/.ssh/.cloudflared/runtime) —
ujian pertama dulu bocorkan `secrets.json` melalui akar projek jarvis-desktop.

`telegram_session` = kebenaran penuh akaun; tulis ke `secrets.json` sahaja.
Jangan minta Tuan tampal kunci dalam chat — dia isi `secrets.json` sendiri. Jangan cetak nilai rahsia.

---

## 6. Perangkap yang dah makan masa

**Heredoc bash + backslash rosak.** `"\n"` jadi baris baru sebenar dan string pecah.
Untuk tampalan, tulis skrip Python ke scratchpad dengan tool **Write**, atau guna **Edit**.
Dah kena berkali-kali (termasuk 2026-11-08 dalam `extras.py`).

**Konsol Windows cp1252**: `print` emoji/◆ crash skrip → `PYTHONIOENCODING=utf-8`.

**Chrome headless** tak jalankan rAF/animasi CSS dengan betul, dan tetingkap minimum ~500 px
lebar. Paksa keadaan akhir dalam salinan ujian; uji susun atur fon pada 500 px.
Pengawas orb (`setInterval`) set 'thinking' → idle bila `busy=false` — ujian mesti tiru giliran.

**Laptop pada skala 150%.** Thread tak DPI-aware nampak 1280×720, ImageGrab 1920×1080.
Input jauh: `SetThreadDpiAwarenessContext(-4)` dulu, baru `GetSystemMetrics/SetCursorPos`.

**`services.screenshot()` sembunyi Jarvis** — untuk fon guna `ImageGrab` terus.
Sembunyi/papar WebView2 berulang dari thread lain = HUD berkelip lalu "gui loop returned".

**Penapis CSS tak boleh warnakan garis putih jadi merah** (hasil merah jambu) — warnakan
dalam kanvas (multiply + destination-in).

**`--alt` hanya wujud dalam `.stage`.** Elemen di luar (overlay) yang guna `.btn.solid`
dapat latar lutsinar — isytihar `--alt` pada overlay.

**`soundcard` mulakan COM semasa import**; thread lain perlu `CoInitializeEx` SELEPAS import.

**`cloudflared tunnel route dns` baca `config.yml` lalai (sipeng)** — selalu guna
`--config jarvis.yml` + UUID tunnel, atau rekod jatuh ke tunnel yang salah.

**Nama method bertembung**: `Api._git` sudah wujud (pulang str) — kaedah projek ialah `_pgit`.

**`quick_control` melangkau `resolve_system` bila ayat ada "lagu/slide"** — laluan pantas
lagu disemak awal dalam `quick_control`.

Yang lama masih benar: `evaluate_js` + async IIFE (simpan ke `window.__r`); `psutil.cpu_percent`
perlu `interval`; IPv6 mati pada rangkaian ni (IPv4 dahulu); `media_server` root = `media/`;
pane tersembunyi berukuran sifar; `ROOT / "ui"` raw string.

---

## 7. Gaya kerja Tuan

- Taip laju, separuh perkataan, BM santai + English. Balas dalam nada sama.
- "buat semua" = buat semua; tanya hanya keputusan sebenar (keselamatan/privasi).
- **UI mesti gabung warna**, nampak 3D/hidup, bukan rata. App fon UI dalam English.
- Dia nak lihat hasil: uji, ambil gambar, beritahu apa diuji dan apa belum.
- "commit dan push" = commit fail kod sahaja (bukan config.json), mesej English yang
  terangkan *kenapa*, akhiri `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

---

## 8. Mula semula

```bash
cd ~/jarvis-desktop
git log --oneline -8          # di mana kita
tail -20 runtime/startup.log  # Jarvis hidup? tunnel? telegram watch?
python -m py_compile main.py extras.py phone_web.py
```
