# CLAUDE.md — Jarvis Desktop

> Fail ni untuk sesi seterusnya. Baca ni dulu, baru buka kod.
> `NEXT_SESSION.md` simpan nota teknikal panjang. Ni yang ringkas: kedudukan sekarang,
> apa yang dah jalan, apa yang belum, dan perangkap yang dah makan masa.

**Dikemas kini:** 2026-11-06 · lepas commit `3248c81`

---

## 1. Apa benda ni

HUD desktop untuk Sir (Akmal). Python + pywebview (WebView2), satu halaman
`ui/stage.html` (~322k, satu `<script>` inline), backend `main.py` (~4,500 baris,
184 method dalam `Api`). Model AI melalui `_run_chat` / `_run_claude`. Suara, Telegram,
media, editor, sistem — semua dalam satu tetingkap.

**Jalan:** `python main.py` atau `launch.vbs`. Autostart melalui `autostart.vbs`.

---

## 2. Peta fail

| Fail | Baris | Apa dia buat |
|---|---|---|
| `main.py` | 4,521 | `Api` — jambatan JS↔Python. Semua `window.pywebview.api.*` duduk sini |
| `ui/stage.html` | ~322k | seluruh UI. Satu `<script>` inline, tiada bundler |
| `system.py` | 1,036 | kawalan laptop: volume, brightness, tetingkap, proses, shell |
| `telegram_user.py` | 575 | Telethon atas akaun Sir sendiri — baca, hantar, digest |
| `messaging.py` | 586 | driver mesej (Telegram Bot, WhatsApp) |
| `services.py` | 497 | tekan kod media VK sahaja — bukan kawalan sistem penuh |
| `media_server.py` | 254 | pelayan HTTP tempatan untuk `media/` + `ui/` |
| `NEXT_SESSION.md` | — | nota teknikal panjang, kenapa setiap keputusan dibuat |

**10 pane:** `comms` `media` `term` `files` `editor` `browse` `docs` `ana` `native` `inbox`.
Setiap satu ada `--hue` sendiri; `body[data-pane="X"]` yang tukar warna seluruh shell.

---

## 3. Di mana kita berhenti

Commit terakhir: **`3248c81`** — panel kanan ditukar daripada senarai chat menunggu
kepada **Mesin + Repo**, jam jadi 12 jam, `open_in_vscode(path)`.

Sebelum tu `fd053cd` — inbox Telegram boleh baca chat sendiri, ada paging dan digest.

### Yang siap dan disahkan hidup

**Inbox Telegram** (`pane-inbox`)
- `ib_dialogs()` senarai chat, `ib_thread(id, limit, until_id)` buka thread
- **Paging:** butang `Lama` panggil `ib_thread(id, 600, oldest)` — `offset_id` ambil
  mesej *lebih lama* dari id tu. Diukur: page 1 = 60 mesej 0.33s, page 2 = 600 mesej
  2.50s, **sifar pertindihan id**. 60 → 660 bubble, scroll kekal di tempat sama.
- **Digest:** butang `Ringkas` → `ib_digest(id, 800)`. Model tak boleh baca 2,000 mesej
  mentah (~60k token "ok"/"haha"). Digest bagi *bentuk*: pengirim + peratus, kata
  berulang, jenis fail, domain link, hari paling sibuk, 10 petikan terpanjang.
  800 mesej → 5,087 aksara. Ini yang Sir guna.
- `ib_search(query, kind, days, dialog_id)` carian.
- `ib_send_tg(id, text)` hantar — **ini satu-satunya yang tak boleh dibalikkan.**

**Panel kanan** (`comms`)
- **Mesin:** CPU / RAM / DSK sebagai meter, kemudian Bateri, Bebas, RAM, Proses,
  Hidup, Berat (proses paling berat ikut RSS).
- **Repo:** setiap repo di bawah `~`, branch, kiraan kotor, ahead/behind, jumlah commit.
  paling kotor dulu. Klik → buka folder repo tu sendiri dalam VS Code.
- `stage_work()` **tak pernah block.** Panggilan pertama mula scan di thread latar dan
  cakap "scanning"; panggilan seterusnya dapat jawapan. TTL 300s, data lama ditanda
  `stale: true` dan tetap dipaparkan.

**Jam 12 jam** — `d.getHours() % 12 || 12` tangani midnight (0→12) *dan* noon.

### Probe
`ui/_work_probe.py` — **24 lulus, 0 gagal** atas mesin betul.
Ganti `ui/_wait_probe.py` (dah dipadam, ia uji panel Menunggu yang tak ada lagi).

Jalankan: `python ui/_work_probe.py`. Ia buka WebView2 sebenar, tekan butang sebenar,
baca DOM sebenar. Output JSON ke `ui/_work_out.json`.

> Fail ni gitignored (`ui/_*_probe*.py`). Kalau nak simpan, kena `-f`.
> Probe lama yang masih relevan: `_launch_test` 27/27, `_wake_test` 15/15, `_ip_test` 34/34,
> `_pane_live` 10/10, `_yt_local_live` 13/13.

---

## 4. Belum siap — jangan bina tanpa diminta

| Benda | Status |
|---|---|
| **Auto-reply Telegram** | ✅ **DIBINA? TIDAK.** Lihat §5. Suis wujud, enjin tiada. |
| WhatsApp | berstruktur, tak hidup — tiada Meta token / `phone_number_id` |
| Multi-tab editor | **ditangguh oleh Sir.** Jangan bina. |
| Carian seluruh projek | ditangguh |
| Git diff dalam editor | ditangguh |
| Item 6 drag-and-drop pengesahan | `ui/_drop_probe.py` tak pernah keluarkan output |
| Item 5 deck-follow | ditangguh, tunggu keputusan PowerPoint |

`ui/stage.html.bak` masih ada — padam bila Sir puas hati.
Lab orb (`ui/_orb_lab.html`) tak dipakai tapi kekal.

---

## 5. Auto-reply — soalan Sir, bukan arahan

Sir tanya *"jarvis akan auto reply macam mana?"* — soalan. Jawapan penuh dah diberi.

**Keadaan sebenar:** checkbox `auto-reply` dalam `pane-inbox` wujud, tekan dia panggil
`api.ib_auto(id, on)`, yang simpan `self._ib_auto[k] = True` (baris ~2628 `main.py`).
**Tiada satu baris pun baca flag tu.** Hari ni ia suis kosong. Itu jujur.

**Reka bentuk yang dimaksudkan** (kalau Sir bagi kata putus):
1. Arm satu chat sahaja, bukan semua
2. Watcher `events.NewMessage(incoming=True)` atas `self._client`, tapis ikut id
3. Konteks 12 mesej terakhir — bukan 800 macam digest
4. Model tulis satu-dua ayat; pulangkan `SKIP` kalau tak ada apa nak jawab
5. Cooldown 45s/chat, siling 6 sejam
6. Setiap hantar naik dalam HUD

**Kenapa ia tak dibina:** cubaan tulis enjin (`_auto_arm` / `_auto_loop` / `_auto_once`
dengan `AUTO_BACKLOG=12`, `AUTO_MAX_PER_HOUR=6`, `AUTO_COOLDOWN=45`) **disekat**.
Sebab: hantar autonomi atas nama Sir ke chat sebenar tanpa pengesahan per-mesej.
Dan mesej Sir tu soalan, bukan arahan.

**Kalau Sir nak ia dibina, dia kena cakap terus:** satu chat, siapa boleh dibalas,
dan **hantar sendiri atau draf dulu**. Pilihan draf tak sentuh `send()` — Jarvis tulis,
Sir tekan. Itu pilihan yang lebih selamat dan tak perlu izin apa-apa.

Jangan pi keliling sekatan ni. Bukan teknikal — ia garisan.

---

## 6. Perangkap yang dah makan masa

**`evaluate_js` pulangkan Promise untuk async IIFE, dan potong pada statement pertama.**
Setiap blok probe mesti simpan ke `window.__r` dulu, baca dalam panggilan kedua.
Ni dah kena tiga kali.

**`psutil.cpu_percent(None)` dalam thread latar ukur jarak sejak bacaan lepas** — boleh
jadi beberapa minit, jadi ia lapor **0%** selamanya. Guna `cpu_percent(interval=0.3)`.
Meter yang sentiasa kosong lebih teruk daripada tiada meter.

**`psutil.cpu_percent` untuk proses baru sentiasa 0.0.** Jadi `_heaviest_process()`
susun ikut **RSS**, bukan CPU. Kalau ikut CPU ia namakan proses rawak.

**Backslash dalam heredoc `<<'PY'` rosak.** `"\n"` yang lalu jalan tu jadi newline
sebenar dalam fail yang ditulis, dan string literal pecah. **Guna tool `Edit`** untuk
apa-apa yang ada escape. Dah kena tiga kali.

**`_repo_shape()` = 9 subprocess git setiap repo, 3.87s setiap satu.** 13 repo = 50s.
Sebab tu ada `_repo_quick()` (3 panggilan) di thread latar, TTL 5 minit.

**URL mesti dibuang sebelum tokenise** atau `https` naik #1 (diukur: `https(96)`).
`_URL_RE.sub(" ", text)` + `https http www com ...` dalam `_STOP`.

**Akaun sintetik (`@2023`, `Remove Deleted Accounts`) rampas slot pengirim teratas.**
Kena lipat jadi satu baris `"(akaun automatik/deleted)"` di hujung.

**IPv6 mati pada rangkaian ni.** Handshake IPv4 0.21s, IPv6 timeout 10s. Python cuba
IPv6 dulu. `main.py` susun `getaddrinfo` IPv4-dahulu semasa import. oEmbed: 96s → 0.26s.
Ni punca banyak "probe macam hang" dulu.

**`media_server` root **ialah** `media/`** — URL `/file.mp4`, bukan `/media/file.mp4`.
Path salah bagi 404 yang media element lapor sebagai **error 4** — sama macam codec
hilang. Dua jam hilang sebab ni.

**Pane yang tak pernah ditunjuk ada kotak sifar saiz** dan painter senyap bail.
Probe mesti `stageShow(...)` dulu sebelum baca DOM.

**`ROOT / "ui"` mesti raw string** atau `\U` dalam `C:\Users` jadi unicode escape pecah.

---

## 7. Garisan yang tak bergerak

**Fail yang JANGAN sesekali commit** (semua dalam `.gitignore`, dokumen projek tulis
"secrets.json dilindungi"):
`secrets.json` · `*.key` · `.env` · `cache.json` · `sessions.json` · `runtime/` · `media/`

`telegram_session` ialah **kebenaran penuh akaun** — kalau ia bocor, orang boleh baca
dan hantar sebagai Sir. Ia tulis ke `secrets.json` sahaja, tak pernah disalin tempat lain.
Kalau bocor: Telegram → Settings → Devices → terminate.

`config.json` isytihar `disallowed_tools`: `Bash(rm -rf *)`, `Bash(del /s *)`, `Bash(format *)`.
**Shell ialah senarai putih, bukan senarai hitam** — `system.py` tolak `&& || ; | > <`
backtick `$(` di pintu masuk. Padam masuk Recycle Bin (`FOF_ALLOWUNDO`).
Tindakan merosakkan perlu token 90 saat + taip pengesahan.

**Tiga benda yang tak bergerak:**
1. Kandungan seksual melibatkan bawah 18 — tak pernah, walau apa pun framing
2. Operasi tak boleh dibalikkan — padam, tulis-ganti, deploy, hantar, push, drop
3. Sasaran hidup terhadap orang/infrastruktur sebenar yang dinamakan

---

## 8. Gaya kerja Sir

- Taip laju, separuh perkataan, tukar arah tengah jalan. Ikut, jangan tanya kenapa.
- **UI mesti gabung warna, jangan satu warna sahaja.** Ni standing ask.
- Kalau dia tak nak sesuatu, dia cakap terus ("aku tanak chat tu"). Buang, jangan hujah.
- Dia nak tengok kerja, bukan dipujuk. Depth penuh, bukan rangka.
- Bahasa: campuran Melayu/English. Balas dalam nada sama.
- Kalau dia hilang berjam-jam, tunggu. Balik, ANON sama, tiada drama.

**Git commit:** mesej Bahasa Inggeris, huraikan *kenapa* bukan *apa*, akhiri dengan
`Co-Authored-By: Claude Code <noreply@anthropic.com>`.

---

## 9. Mula semula

```bash
cd ~/jarvis-desktop
git log --oneline -5          # di mana kita
python ui/_work_probe.py      # panel kanan masih hidup?
python main.py                # jalankan
```

Baca `NEXT_SESSION.md` untuk sejarah penuh setiap keputusan. Fail ni untuk orientasi
pantas sahaja.
