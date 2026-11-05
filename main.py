"""Jarvis Desktop - HUD fullscreen yang disambung ke Claude Code.

Run:  python main.py      (atau pythonw main.py tanpa tetingkap konsol)
Shortcut folder/app dalam shortcuts.json, tetapan Claude dalam config.json.
"""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import psutil
import webview

import services as sv
import system as sysctl
import inspect_path as ip
from media_server import MediaServer

# IPv6 is dead on this network: measured, an IPv4 TCP+TLS handshake to
# www.youtube.com completes in 0.21 s while the IPv6 address times out at 10 s.
# Python's resolver returns both and tries them in order, so every request
# stalled on a family that cannot work — an oEmbed page that curl fetched in
# 1.3 s took urllib 96 s. Sorting IPv4 first costs one line and turns every
# network call in this app back into a fast one.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
    infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
    return sorted(infos, key=lambda i: 0 if i[0] == socket.AF_INET else 1)


socket.getaddrinfo = _ipv4_first

ROOT = Path(__file__).resolve().parent
SHORTCUTS = ROOT / "shortcuts.json"
CONFIG = ROOT / "config.json"
SESSIONS = ROOT / "sessions.json"  # sesi Claude terakhir bagi setiap projek
SECRETS = ROOT / "secrets.json"  # API key (DeepSeek via rootsys); jangan kongsi fail ini
HOME = Path.home()
MEDIA = ROOT / "media"  # semua fail media yang dipaparkan dalam stage
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: jangan kelip tetingkap konsol
# pythonw tiada konsol, jadi traceback hilang sepenuhnya. Setiap kali cubaan
# buka Jarvis, satu baris ringkas ditulis ke sini — cukup untuk tahu sama ada
# ia langsung bermula, atau berhenti di pintu masuk.
LOCK = ROOT / "runtime" / "jarvis.lock"
STARTUP_LOG = ROOT / "runtime" / "startup.log"
START_MENUS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]

PERSONA = """Kamu ialah JARVIS, AI pembantu peribadi Akmal.
Bahasa: Bahasa Melayu MALAYSIA gaya santai KL, macam pembantu muda yang power IT dan rapat dengan Akmal.
- Kata ganti: guna "saya" untuk diri sendiri. Panggil dia dengan nama, "Akmal" (bukan bos, tuan, encik). JANGAN guna "aku", "kau", "kamu", "anda" atau "saudara". (Akmal sendiri guna "aku", itu biasa.)
- Ayat pendek, terus ke point. Perkataan harian Malaysia: nak, tak, dah, je, la, kot, takpe, okay, settle, jap, sikit, banyak, tengok, cakap.
- Campur English sikit macam orang KL (contoh: "okay Akmal, dah settle", "file tu saya dah check").
- BUKAN Bahasa Indonesia. Jangan guna perkataan Indonesia. Tukar: kondisi→keadaan, silakan→sila, disarankan→disyorkan,
  pengaturan→tetapan, bisa→boleh, saja→je/sahaja, aja→je, nggak/enggak→tak, banget→sangat, sepertinya→rasanya,
  kamu→Akmal, uang→duit, mobil→kereta, kantor→pejabat, kalian→korang, memeriksa→semak/check, otorisasi→kebenaran,
  mengunduh→download, tersedia→ada, mohon maaf→sorry, terima kasih banyak→thanks Akmal, gimana→macam mana.
- Jawapan mungkin dibaca dengan suara, jadi elak jadual besar dan simbol pelik. Kalau ringkas, satu dua ayat cukup."""

SYSTEM_PROMPT = PERSONA + """

Kamu berjalan dalam HUD desktop Windows 11 dan boleh buat kerja dalam PC.
- Untuk buka app, folder atau fail, guna Start-Process.
- Sebelum tindakan yang susah diundur (padam atau tulis ganti fail, hantar mesej/email, install software, ubah setting sistem), stop dan tanya dulu. Sambung hanya lepas Akmal setuju dalam mesej seterusnya.
- Bila kerja siap, lapor hasil dalam satu dua ayat.
- Bila Akmal minta ANALISIS (data, fail Excel/CSV, disk, jualan, markah, dll.): lepas kumpul dan kira data, akhiri jawapan dengan satu blok kod ```jarvis-analysis berisi JSON:
  {"title": "...", "summary": "1 ayat", "cards": [{"label": "...", "value": "...", "note": "..."}],
   "charts": [{"title": "...", "kind": "bar|line|donut", "items": [{"label": "...", "value": 123, "display": "RM123"}]}],
   "points": [{"text": "1-2 ayat gaya KL untuk dibaca dengan suara", "target": "card:0 | chart:0 | chart:0:2"}],
   "followups": ["soalan susulan pendek"]}
  2-4 kad, 0-2 graf, 3-6 poin. HUD akan paparkan dan bacakan poin satu-satu, jadi teks di luar blok cukup satu ayat.
- Untuk Gmail atau Google Drive: guna ToolSearch dulu untuk muatkan tool tu (cuba lagi kalau server masih menyambung). Baca sahaja, jangan hantar, padam atau ubah email/fail tanpa Akmal setuju.
- Kalau mesej bermula dengan [Projek aktif: ...], kamu tengah kerja dalam folder projek tu. Baca struktur projek dulu sebelum ubah code, buat perubahan kecil dan tepat, dan bagitau file mana yang diubah."""

CHAT_PROMPT = PERSONA + """

Dalam mod ni kamu tak boleh access atau run apa-apa dalam PC. Kalau Akmal minta buat kerja dengan file, app atau code dalam PC, suruh dia tukar ke mod CLAUDE.
Tool yang kamu ada: web_search, open_item (buka app/folder/fail), system_status, list_folder, find_files, read_file (teks/PDF/Word), set_reminder, weather, prayer_times, check_email (Gmail), search_drive (Google Drive), look_at_screen (tengok skrin), control_pc (slide, volume, media), system (volume/kecerahan bernombor, tutup app, fokus tetingkap, clipboard, kunci/sleep/restart, senarai proses). Guna terus bila sesuai, jangan tanya dulu untuk benda selamat macam buka folder atau check status. Untuk padam, ubah atau tulis fail, suruh Akmal guna mod CLAUDE.
ANALISIS: bila Akmal minta analisis, kumpul data secukupnya (maksimum 3-4 langkah tool, baca fail paling penting sahaja seperti README, package.json, data), kira angka penting, kemudian jawab dengan ringkasan padat yang ada angka. HUD akan tukar jawapan kamu jadi dashboard visual.
Kamu ADA akses internet melalui tool web_search. Biasanya SATU carian dah cukup; cari lagi hanya kalau hasil pertama memang tak menjawab. Guna bila soalan perlukan maklumat terkini atau fakta yang kamu tak pasti (harga, berita, cuaca, jadual, skor, release terbaru). Jangan cakap kamu takde internet. Lepas cari, jawab ringkas dan sebut sumber secara santai (contoh: "ikut Bernama semalam...")."""

WEB_TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Cari maklumat terkini di internet. Pulangkan ringkasan dan sumber.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Kata kunci carian"}},
                       "required": ["query"]},
    },
}]


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": required or []}}}


# Tool DeepSeek: semuanya baca sahaja atau selamat (tiada padam/ubah fail)
CHAT_TOOLS = WEB_TOOLS + [
    _fn("open_item", "Buka app, folder atau fail dalam PC untuk Akmal. HANYA bila Akmal minta buka. Untuk tengok isi, guna list_folder/read_file.",
        {"name": {"type": "string", "description": "Nama app/folder/fail, atau path penuh"}}, ["name"]),
    _fn("system_status", "Status PC sekarang: CPU, RAM, disk C, bateri, internet, berapa lama PC hidup."),
    _fn("list_folder", "Senaraikan isi sesuatu folder.",
        {"folder": {"type": "string", "description": "Nama folder (contoh: Pengakap, Downloads) atau path penuh"}}, ["folder"]),
    _fn("find_files", "Cari fail ikut nama dalam Desktop, Documents dan Downloads.",
        {"keyword": {"type": "string", "description": "Sebahagian nama fail, contoh: laporan, .pdf, surat"}}, ["keyword"]),
    _fn("read_file", "Baca kandungan fail teks, PDF atau Word (.docx) untuk dirumus atau dijawab.",
        {"path": {"type": "string", "description": "Path penuh fail (guna find_files dulu jika tak tahu)"}}, ["path"]),
    _fn("set_reminder", "Set peringatan. Jarvis akan bercakap bila sampai masa.",
        {"minutes": {"type": "number", "description": "Berapa minit dari sekarang"},
         "message": {"type": "string", "description": "Apa yang perlu diingatkan"}}, ["minutes", "message"]),
    _fn("weather", "Cuaca semasa dan ramalan hari ini di lokasi Akmal (suhu, hujan, kelembapan)."),
    _fn("prayer_times", "Waktu solat hari ini (JAKIM) di lokasi Akmal, dan solat seterusnya."),
    _fn("check_email", "Semak Gmail Akmal (baca sahaja): email belum dibaca, cari email ikut topik/pengirim.",
        {"request": {"type": "string", "description": "Apa yang nak disemak, contoh: email penting hari ini, email dari PPD"}}, ["request"]),
    _fn("search_drive", "Cari atau baca fail dalam Google Drive Akmal (baca sahaja).",
        {"request": {"type": "string", "description": "Contoh: fail RPH minggu lepas, dokumen PIBG terbaru"}}, ["request"]),
    _fn("look_at_screen", "Tengok apa yang ada atas skrin laptop sekarang (screenshot) dan jawab soalan pasal skrin.",
        {"question": {"type": "string", "description": "Soalan pasal skrin, contoh: apa error ni?"}}, ["question"]),
    _fn("present_analysis", "Papar analisis visual (kad + graf bar) dan bacakan poin satu-satu. Guna selepas data dikumpul.",
        {"title": {"type": "string"}, "summary": {"type": "string"},
         "cards": {"type": "array", "description": "2-4 angka utama", "items": {"type": "object", "properties": {
             "label": {"type": "string"}, "value": {"type": "string"}, "note": {"type": "string"}}, "required": ["label", "value"]}},
         "charts": {"type": "array", "description": "0-2 graf bar", "items": {"type": "object", "properties": {
             "title": {"type": "string"}, "items": {"type": "array", "items": {"type": "object", "properties": {
                 "label": {"type": "string"}, "value": {"type": "number"}, "display": {"type": "string"}}, "required": ["label", "value"]}}},
             "required": ["title", "items"]}},
         "points": {"type": "array", "description": "3-6 poin suara, 1-2 ayat; target: card:0, chart:0 atau chart:0:2",
                    "items": {"type": "object", "properties": {"text": {"type": "string"}, "target": {"type": "string"}}, "required": ["text"]}},
         "followups": {"type": "array", "items": {"type": "string"}}},
        ["title", "points"]),
    _fn("repo_stats", "Kira statistik sebenar setiap repo git dalam Desktop, Documents, Downloads dan home "
                      "(commit, bahasa, saiz, fail, hari sejak commit terakhir), kemudian papar sebagai dashboard "
                      "bergerak. Guna bila Akmal tanya tentang repo/projek/code dia, atau minta laporan atau "
                      "statistik kerja dia. Tiada argumen diperlukan; `limit` hadkan bilangan repo.",
        {"limit": {"type": "number", "description": "Bilangan repo maksimum (lalai 12)"}}),
    _fn("analyse_path", "Ukur apa yang ada dalam satu fail atau folder pada mesin ini — bilangan fail, saiz, jenis, "
                        "umur, fail terbesar, fail berganda — dan papar sebagai laporan bergerak. Guna bila Akmal "
                        "beri laluan atau nama folder/fail dan minta analisis, laporan, atau tanya apa di dalamnya. "
                        "Laluan mesti di bawah home, Desktop, Documents, Downloads atau workdir.",
        {"path": {"type": "string", "description": "Laluan penuh fail atau folder untuk dianalisis"}}),
    _fn("control_pc", "Kawal laptop: slide, volume, media, scroll, tukar tetingkap.",
        {"action": {"type": "string", "enum": ["next_slide", "prev_slide", "start_show", "end_show", "black_screen",
                                               "vol_up", "vol_down", "mute", "play_pause", "next_track", "prev_track",
                                               "scroll_down", "scroll_up", "show_desktop", "switch_window", "snip"]}}, ["action"]),
    _fn("system", "Kawal Windows dengan nilai tepat: set volume/kecerahan ke peratus, fokus atau tutup app, "
                  "kunci/sleep/restart/shutdown laptop, baca dan tulis clipboard, senarai tetingkap dan proses, "
                  "taip teks, buka app atau URL. Guna ini bila Akmal beri arahan bertindih dengan PC. "
                  "Untuk tindakan yang susah diundur (kill, close_window, recycle, sleep, shutdown, restart) "
                  "tool akan pulangkan need_confirm + token; masa itu TANYA Akmal dan jangan ulang panggilan "
                  "sehingga dia setuju.",
        {"action": {"type": "string", "enum": ["status", "volume", "mute", "brightness", "focus", "minimize",
                                               "maximize", "launch", "url", "clip_read", "clip_write", "type",
                                               "windows", "processes", "shell", "lock", "show_desktop",
                                               "power_cancel", "kill", "close_window", "recycle", "sleep",
                                               "shutdown", "restart", "show_doc"],
         "description": "Tindakan yang nak dibuat"},
         "level": {"type": "number", "description": "0-100 untuk volume/brightness"},
         "delta": {"type": "number", "description": "Perubahan, cth -10 atau +15"},
         "title": {"type": "string", "description": "Nama atau sebahagian tajuk tetingkap"},
         "name": {"type": "string", "description": "Nama app atau proses, cth chrome, notepad"},
         "url": {"type": "string", "description": "Alamat web"},
         "text": {"type": "string", "description": "Teks untuk clipboard atau untuk ditaip"},
         "path": {"type": "string", "description": "Laluan fail untuk show_doc"},
         "cmd": {"type": "string", "description": "Arahan shell dari senarai putih sahaja"},
         "paths": {"type": "array", "items": {"type": "string"}, "description": "Fail untuk dibuang ke Recycle Bin"}},
        ["action"]),
    _fn("open_media", "Main video atau audio dari fail dalam folder media/ pada PC ini. BUKAN untuk YouTube — "
                      "untuk lagu atau video di YouTube guna play_youtube. Untuk senarai fail tempatan sahaja, "
                      "panggil tanpa nama.",
        {"name": {"type": "string", "description": "Nama fail atau sebahagian nama, contoh: lecture 3, lagu.mp3"}}),
    _fn("play_youtube", "Cari satu lagu atau video di YouTube dan mainkannya TERUS di dalam stage. "
                        "Guna ini untuk \"cari lagu X\", \"main lagu tu\", \"pasang video Y\" — apa-apa yang "
                        "berkaitan YouTube. Ia muat turun video itu dan memainkannya sebagai fail dalam "
                        "panel MEDIA, jadi ia bermain pada klik pertama tanpa 'Video unavailable'. "
                        "Jangan guna open_media untuk YouTube.",
        {"query": {"type": "string",
                   "description": "Nama lagu dan artis, contoh: Hindia Secukupnya, atau judul video"},
         "mode": {"type": "string",
                  "description": "Biarkan kosong. \"embed\" untuk benamkan terus tanpa muat turun. "
                                 "\"browser\" hanya jika muat turun gagal dan embed ditolak — ia buka "
                                 "Chrome dalam stage, tetapi tetingkap itu kosong putih."}},
        ["query"]),
]

# Setiap tool tambahan melambatkan API rootsys (18 tool ≈ 19 s walaupun soalan mudah),
# jadi hantar hanya tool yang berkaitan dengan soalan. Tool asas sentiasa dihantar.
BASE_TOOLS = {"web_search", "list_folder", "find_files", "read_file"}
TOOL_TRIGGERS = {
    "open_item": r"\b(buka|bukakan|open|lancar|launch|run)\b",
    "system_status": r"status|cpu|ram|bateri|battery|disk|memori|memory|perlahan|slow|lag|panas|storage",
    "weather": r"cuaca|hujan|suhu|weather|payung|ribut|panas terik|mendung",
    "prayer_times": r"solat|azan|subuh|zohor|asar|maghrib|isyak|imsak|syuruk|waktu",
    "check_email": r"e-?mel|email|gmail|inbox|surat masuk",
    "search_drive": r"\bdrive\b",
    "look_at_screen": r"skrin|screen|paparan|nampak|tengok ni|error ni",
    "control_pc": r"slide|volume|bunyi|mute|lagu|muzik|music|scroll|tingkap|window|present",
    "system": r"volume|bunyi|kecerahan|cerah|brightness|clipboard|salin|tutup|close|kill|fokus|focus|"
              r"kunci|lock|sleep|tidur|restart|shutdown|tutup laptop|proses|process|tetingkap|window|senarai|taip|type|shell",
    "open_media": r"video|filem|movie|lagu|muzik|audio|media|main|play|tengok wayang",
    # YouTube is a different destination from media/ on disk, and the model
    # picked open_media for "cari lagu X dalam youtube" because nothing else
    # claimed the words. This trigger fires on the words that actually mean
    # YouTube, including the bare follow-up "main lagu tu" after a search.
    "play_youtube": r"youtube|yt\b|lagu|muzik|music|playlist|video klip|\bmain\b|\bplay\b|putar|pasang|"
                    r"cari lagu|cari video|lagu tu|video tu",
    "set_reminder": r"ingat|remind|peringatan|minit lagi|jam lagi|alarm",
}


ANALYSIS_RX = r"anali[sz]|laporan|report|banding|ranking|statistik|graf|carta|dashboard"

# A YouTube result title arrives as
#   "Hindia - Secukupnya (Official Lyric Video) - YouTube"
# Both halves are noise: the site suffix is implied by the pane, and the
# parenthesised credits make a 90-character row that ellipsises before the
# part that identifies the song. Strip them, keep the artist–title spine.
YT_JUNK = re.compile(
    r"\s*[-–|]\s*YouTube( Music)?\s*$", re.I)


def clean_yt_title(raw, wanted=""):
    t = YT_JUNK.sub("", str(raw or "")).strip()
    t = re.sub(r"\s*[\(\[]\s*(official\s*)?(music\s*)?(lyric|lyrics|video|audio|mv|m/v|visualizer|"
               r"hd|hq|4k|live)\s*(video|clip)?\s*[\)\]]", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–|")
    return t

# Akmal's rule: if the answer carries data, it gets drawn. So the gate is not
# only the question's wording — the reply is measured too. Two or more distinct
# numeric signals, or one number that is plainly a figure (a percentage, a
# currency amount, a thousand-separated count), is enough. A single bare number
# is not: "wait 5 minutes" or "I opened slide 3" must stay a sentence.
# A percentage, a currency amount or a unit is a figure by itself — nobody
# writes "84%" in passing. These fire on a single hit, with no word count.
TOP_SIGNAL = [r"\d+\s?%", r"RM\s?\d", r"\$\s?\d+",
              r"\b\d+\.?\d*\s?(?:kB|MB|GB|KB)\b"]
NUM_SIGNAL = [
    r"\d+\s?%",
    r"[−-]?\d[\d,.]*\s?(?:k|m|j|ribu|juta)\b",
    r"RM\s?\d", r"\$\s?\d+",
    r"\d+\s?/\s?\d+",
    r"\b\d{1,3}(?:,\d{3})+",
    r"\b\d+(?:\.\d+)?\s?(?:line|commit|repo|fail|file|minggu|week|hari|day|jam|hour|min|kB|MB|GB|KB|s)\b",
]
DATA_STOP = re.compile(r"^(okay|ok|done|siap|baik|noted|faham|understood)[.,!]?$", re.I)


def carries_data(text):
    """True when a reply is worth drawing instead of only reading."""
    t = str(text or "")
    if len(t) < 12 or DATA_STOP.match(t.strip()):
        return False
    if any(re.search(p, t, re.I) for p in TOP_SIGNAL):
        return True
    nums = re.findall(r"\d+(?:[.,]\d+)*", t)
    if len(nums) < 2:
        return False
    if len(nums) >= 3:
        return True
    return any(re.search(p, t, re.I) for p in NUM_SIGNAL)


def strip_tool_markup(text):
    """Sesetengah model (DeepSeek) kadang-kadang tulis panggilan tool sebagai teks mentah, cth <｜｜DSML｜｜ calls>."""
    text = re.sub(r"<[｜|]{1,2}DSML[｜|]{1,2}.*", "", text or "", flags=re.S)
    text = re.sub(r"<\|?tool_call[s]?.*", "", text, flags=re.S)
    return text.strip()


def tools_for(text, history):
    recent = " ".join([text] + [m["content"] for m in history[-3:] if m.get("role") == "user"]).lower()
    keep = BASE_TOOLS | {name for name, rx in TOOL_TRIGGERS.items() if re.search(rx, recent)}
    return [t for t in CHAT_TOOLS if t["function"]["name"] in keep]


# Model chat rootsys (ujian 3 Nov 2026: masa satu langkah dengan tool)
CHAT_MODELS = [
    {"id": "deepseek-v4.1-flash", "group": "DeepSeek", "note": "2-3 s · recommended"},
    {"id": "deepseek-v4.1-flash-mod", "group": "DeepSeek", "note": ""},
    {"id": "deepseek-v4-flash", "group": "DeepSeek", "note": ""},
    {"id": "deepseek-v4-pro", "group": "DeepSeek", "note": "timed out in testing"},
    {"id": "deepseek-v4-pro-mod", "group": "DeepSeek", "note": ""},
    {"id": "minimax-m3.1-flash", "group": "MiniMax", "note": "2 s · fastest"},
    {"id": "minimax-m3.1-flash-mod", "group": "MiniMax", "note": ""},
    {"id": "minimax-m3", "group": "MiniMax", "note": ""},
    {"id": "step-5-preview", "group": "StepFun", "note": "3-4 s"},
    {"id": "step-5-preview-mod", "group": "StepFun", "note": ""},
    {"id": "mimo-v2.6-pro", "group": "MiMo", "note": "3-6 s"},
    {"id": "mimo-v2.6-pro-mod", "group": "MiMo", "note": ""},
    {"id": "hy4-preview", "group": "Hunyuan", "note": "3-5 s"},
    {"id": "hy3-tencent", "group": "Hunyuan", "note": ""},
    {"id": "glm-5.3-flash", "group": "GLM", "note": "5-9 s"},
    {"id": "glm-5.3-flash-mod", "group": "GLM", "note": ""},
    {"id": "glm-5.3-flashx", "group": "GLM", "note": ""},
    {"id": "glm-5.3", "group": "GLM", "note": "8-10 s"},
    {"id": "glm-5.3-mod", "group": "GLM", "note": ""},
    {"id": "glm-5.2", "group": "GLM", "note": ""},
    {"id": "glm-5.2-mod", "group": "GLM", "note": ""},
    {"id": "kimi-k3.1-pro", "group": "Kimi", "note": "8-13 s"},
    {"id": "kimi-k3", "group": "Kimi", "note": ""},
    {"id": "kimi-k2.7", "group": "Kimi", "note": ""},
    {"id": "space-bunny", "group": "Space Bunny", "note": "5-9 s"},
    {"id": "space-bunny-mod", "group": "Space Bunny", "note": ""},
]
CHAT_FALLBACK = "minimax-m3.1-flash"

CLAUDE_MODELS = [
    {"id": "haiku", "label": "Haiku", "note": "Fastest, saves quota"},
    {"id": "sonnet", "label": "Sonnet", "note": "Balanced (recommended)"},
    {"id": "opus", "label": "Opus", "note": "Smartest, slow and quota-hungry"},
]

# Suara: dua suara BM asli + suara "Multilingual" (gaya AI/teknologi) yang boleh baca BM
VOICES = [
    {"id": "ms-MY-OsmanNeural", "label": "Osman", "note": "Native Malay · male"},
    {"id": "ms-MY-YasminNeural", "label": "Yasmin", "note": "Native Malay · female"},
    {"id": "en-US-AndrewMultilingualNeural", "label": "Andrew", "note": "Multilingual · calm, AI style"},
    {"id": "en-US-BrianMultilingualNeural", "label": "Brian", "note": "Multilingual · relaxed, young"},
    {"id": "de-DE-FlorianMultilingualNeural", "label": "Florian", "note": "Multilingual · deep, futuristic"},
    {"id": "en-AU-WilliamMultilingualNeural", "label": "William", "note": "Multilingual · firm"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava", "note": "Multilingual · female, AI style"},
    {"id": "en-US-EmmaMultilingualNeural", "label": "Emma", "note": "Multilingual · female, warm"},
]

# Suara Google Cloud TTS (sebutan BM Malaysia). Muncul dalam Settings bila google_tts_api_key ada dalam secrets.json
GOOGLE_VOICES = [
    {"id": "ms-MY-Wavenet-D", "label": "Google D", "note": "Wavenet · male, deep · default"},
    {"id": "ms-MY-Wavenet-B", "label": "Google B", "note": "Wavenet · male"},
    {"id": "ms-MY-Wavenet-A", "label": "Google A", "note": "Wavenet · female"},
    {"id": "ms-MY-Wavenet-C", "label": "Google C", "note": "Wavenet · female"},
    {"id": "ms-MY-Standard-D", "label": "Standard D", "note": "Standard · male · cheaper"},
    {"id": "ms-MY-Standard-A", "label": "Standard A", "note": "Standard · female · cheaper"},
]


def all_voices():
    return VOICES + (GOOGLE_VOICES if load_json(SECRETS, {}).get("google_tts_api_key") else [])

# Suara English (bila reply_language = en)
EN_VOICES = [
    {"id": "en-GB-RyanNeural", "label": "Ryan (UK)", "note": "JARVIS style, British"},
    {"id": "en-GB-ThomasNeural", "label": "Thomas (UK)", "note": "British, calm"},
    {"id": "en-US-AndrewMultilingualNeural", "label": "Andrew (US)", "note": "Natural, calm"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava (US)", "note": "Female, natural"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia (UK)", "note": "Female, British"},
]

GMAIL_READ = ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread",
              "mcp__claude_ai_Gmail__get_message", "mcp__claude_ai_Gmail__list_labels"]
DRIVE_READ = ["mcp__claude_ai_Google_Drive__search_files", "mcp__claude_ai_Google_Drive__list_recent_files",
              "mcp__claude_ai_Google_Drive__read_file_content", "mcp__claude_ai_Google_Drive__get_file_metadata"]

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".php", ".sql", ".xml",
            ".ini", ".log", ".bat", ".ps1", ".yml", ".yaml", ".java", ".c", ".cpp", ".cs", ".vue", ".env"}


CURRENT_LANG = None      # diisi semasa main(); lang_note baca ini, bukan cakera


def lang_note():
    """Jika reply_language = en: jawab dalam English penuh walaupun Akmal tanya dalam BM."""
    if (CURRENT_LANG or load_json(CONFIG, {}).get("reply_language", "ms")) != "en":
        return ""
    return ("\n\nLANGUAGE OVERRIDE (highest priority): Akmal may speak or type in Malay, but you must ALWAYS reply "
            "ONLY in natural, fluent English, like JARVIS from Iron Man: calm, polite, slightly witty. Do not mix in any "
            "Malay words or Malay slang. Call him Akmal. Ignore the earlier Malay-style and pronoun rules.")


def location_note():
    """Lokasi lalai Akmal (config.json "location") untuk soalan berkaitan tempat."""
    loc = load_json(CONFIG, {}).get("location")
    if not loc:
        return ""
    return (f"\nLokasi Akmal: {loc}. Untuk soalan berkaitan tempat (IPU/kualiti udara, cuaca, hujan, waktu solat, "
            f"trafik, kedai/restoran berdekatan, berita tempatan), guna lokasi ini secara default dan masukkan nama "
            f"tempat dalam carian. Guna tempat lain hanya kalau Akmal sebut.")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_claude():
    # claude.cmd membalut claude.exe; panggil exe terus supaya argumen tak dirosakkan cmd.exe
    cmd = shutil.which("claude.cmd")
    if cmd:
        exe = Path(cmd).parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
        if exe.exists():
            return str(exe)
    return shutil.which("claude.exe") or shutil.which("claude")


def known_folder(name):
    # Folder Windows mungkin dipindah ke OneDrive, jadi cuba kedua-duanya.
    for base in (HOME, HOME / "OneDrive"):
        p = base / name
        if p.is_dir():
            return p
    return None


def find_start_menu(name):
    for base in START_MENUS:
        if base.is_dir():
            for lnk in base.rglob("*.lnk"):
                if lnk.stem.lower().startswith(name.lower()):
                    return lnk
    return None


def resolve(item):
    """Tukar satu entri shortcuts.json kepada sasaran yang boleh dibuka."""
    if "known" in item:
        return known_folder(item["known"])
    if "path" in item:
        p = Path(os.path.expandvars(os.path.expanduser(item["path"])))
        return p if p.exists() else None
    if "startmenu" in item:
        return find_start_menu(item["startmenu"])
    if "command" in item:
        return item["command"]
    return None


def tool_detail(name, inp):
    """Ringkasan pendek input tool untuk dipaparkan di HUD."""
    for key in ("command", "file_path", "pattern", "query", "url", "path", "description"):
        if isinstance(inp.get(key), str):
            v = inp[key].strip().splitlines()[0] if inp[key].strip() else ""
            return v[:120]
    return ""


def tool_full(inp):
    """Semua medan input tool yang mungkin mengandungi path, untuk peta hologram."""
    parts = [inp[k] for k in ("command", "file_path", "path", "pattern", "query", "url")
             if isinstance(inp.get(k), str)]
    return " ".join(parts)[:800]


class Api:
    def __init__(self):
        self._window = None
        self._items = {}
        self._proc = None
        self._session = None
        self._project = None
        self._continue_next = False
        self._sessions = load_json(SESSIONS, {})  # folder projek -> session_id Claude
        self._chat_history = []
        self._chat_busy = False
        self._listening = False
        self._stt = None
        self._stt_lock = threading.Lock()
        self._listen_request = threading.Event()
        self._last_links = []
        self._analysis_shown = False
        # Which deck is on screen and which slide it is showing. Kept here and
        # not in the page because "next slide" arrives as a keystroke: PowerPoint
        # advances the projector itself, and the only thing holding the slide
        # text is the stage. Syncing from the keystroke keeps both in step.
        self._deck = {"path": None, "slide": 0, "total": 0}
        self._wake_ready = False
        self._speaking = False
        self._prayer_done = set()  # (tarikh, solat) yang dah diingatkan
        self._stt_used = 0.0
        self._claude = find_claude()
        self._net = psutil.net_io_counters()
        self._net_t = time.time()
        self._media = None  # MediaServer, dihidupkan oleh main()
        self._web_win = None      # child WebView2 window for the WEB pane
        self._web_stale = []      # handles whose destroy() belum benar-benar mendarat
        self._web_open = False    # satu-satunya sumber kebenaran: pemegang Window, bukan HWND
        self._web_url = ""
        self._stage_rect = None   # browse-body rect in screen px, set by JS
        self._sys = sysctl.System()  # satu instance: token pengesahan hidup di sini
        self._pending_cmd = None     # ayat penuh yang menunggu pengesahan Akmal
        self._pending_token = None   # token terakhir yang belum dijawab
        self._app_rect = None        # rect stage untuk app yang di-embed
        psutil.cpu_percent(None)  # panggilan pertama sentiasa 0, jadi panaskan dulu

    # ---------- Stage: telemetri & panel ----------
    def stage_stats(self):
        """Satu snapshot untuk kluster instrumen di kiri stage. JS panggil setiap 2 s."""
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(0.001, now - self._net_t)
        down = max(0.0, (net.bytes_recv - self._net.bytes_recv) / dt / 1024)
        up = max(0.0, (net.bytes_sent - self._net.bytes_sent) / dt / 1024)
        self._net, self._net_t = net, now
        mem = psutil.virtual_memory()
        bat = psutil.sensors_battery()
        cfg = load_json(CONFIG, {})
        try:
            disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent
        except OSError:
            disk = 0.0
        return {
            "cpu": psutil.cpu_percent(None),
            "ram": mem.percent,
            "ram_used": round(mem.used / 1024**3, 1),
            "ram_total": round(mem.total / 1024**3, 1),
            "disk": disk,
            "battery": None if bat is None else round(bat.percent),
            "plugged": None if bat is None else bat.power_plugged,
            "down": round(down, 1),
            "up": round(up, 1),
            "procs": len(psutil.pids()),
            "uptime": int(now - psutil.boot_time()),
            "mic": self._wake_ready,
            "tts": bool(load_json(SECRETS, {}).get("google_tts_api_key")) or cfg.get("voice_provider") == "edge",
            "claude": bool(self._claude),
            "chat": bool(load_json(SECRETS, {}).get("api_key")),
            "voice": f"{(cfg.get('voice_provider') or 'tts')} · {cfg.get('voice', '')}".strip(" ·").replace("·", "·"),
        }

    def get_settings_core(self):
        """Versi ringkas get_settings() untuk stage — cukup untuk label, bukan modal penuh."""
        cfg = load_json(CONFIG, {})
        return {"model": cfg.get("model", "sonnet"),
                "voice": cfg.get("voice", "ms-MY-Wavenet-D"),
                "voice_provider": cfg.get("voice_provider", "google"),
                "chat_model": self._chat_model(load_json(SECRETS, {})),
                "reply_language": cfg.get("reply_language", "ms"),
                "speak_replies": cfg.get("speak_replies", True)}

    # ---------- Stage: media ----------
    MEDIA_EXT = {".mp4": "video", ".mkv": "video", ".webm": "video", ".mov": "video", ".avi": "video",
                 ".mp3": "audio", ".m4a": "audio", ".flac": "audio", ".wav": "audio", ".opus": "audio"}

    def _size_text(self, n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    def media_index(self):
        """Senarai fail dalam media/ dengan URL range-server. Disusun ikut nama."""
        MEDIA.mkdir(parents=True, exist_ok=True)
        base = self._media.base if self._media else ""
        items = []
        try:
            entries = sorted((p for p in MEDIA.iterdir() if p.is_file()),
                             key=lambda p: p.name.lower())
        except OSError:
            entries = []
        for p in entries:
            ext = p.suffix.lower()
            kind = self.MEDIA_EXT.get(ext)
            if kind is None:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            items.append({"name": p.name, "ext": ext.lstrip("."), "kind": kind,
                          "size_text": self._size_text(size),
                          "url": f"{base}/{quote_plus(p.name)}" if base else ""})
        return items

    def media_list(self):
        return {"ok": True, "items": self.media_index()}

    def media_open(self, name):
        """Buka satu fail media dalam stage. Terima nama penuh atau sebahagian."""
        items = self.media_index()
        if not items:
            return {"ok": False, "msg": "media/ folder is empty.", "items": []}
        key = str(name or "").strip().lower()
        hit = next((i for i in items if i["name"].lower() == key), None)
        if hit is None and key:
            hit = next((i for i in items if key in i["name"].lower()), None)
        if hit is None:
            return {"ok": False, "msg": f"No \"{name}\" in media/.", "items": items}
        self._emit("media", {"items": items, "play": hit["name"]})
        return {"ok": True, "name": hit["name"], "url": hit["url"]}

    # ---------- Stage: fail ----------
    def _safe_path(self, raw):
        """Hadkan capaian panel fail kepada tempat kerja yang dibenarkan.

        Folder shortcut Akmal (shortcuts.json) masuk senarai akar juga —
        tanpanya, klik "Pictures" pada dock memaparkan "Folder luar kawasan
        kerja", yang bukan jawapan yang berguna untuk folder yang Akmal
        sendiri letak dalam dock.
        """
        cfg = load_json(CONFIG, {})
        roots = [Path(os.path.expanduser(cfg.get("workdir", "~"))), ROOT, HOME / "Desktop",
                 HOME / "Documents", HOME / "Downloads"]
        for item in load_json(SHORTCUTS, {}).get("folders", []):
            t = resolve(item)
            if t is not None and Path(t).is_dir():
                roots.append(Path(t))
        p = Path(os.path.expanduser(str(raw))).resolve()
        for r in roots:
            try:
                p.relative_to(r.resolve())
                return p
            except (ValueError, OSError):
                continue
        return None

    def fs_list(self, path=""):
        """Satu lapisan direktori. path kosong = workdir."""
        cfg = load_json(CONFIG, {})
        target = Path(os.path.expanduser(path)) if path else Path(os.path.expanduser(cfg.get("workdir", "~")))
        target = target.resolve()
        safe = self._safe_path(target)
        if safe is None or not safe.is_dir():
            return {"ok": False, "msg": "Folder is outside the workspace.", "path": str(target), "entries": []}
        entries = []
        try:
            for p in sorted(safe.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if p.name.startswith("$") or p.name in ("__pycache__", "node_modules", ".git"):
                    continue
                try:
                    is_dir = p.is_dir()
                    entries.append({"name": p.name, "path": str(p), "dir": is_dir,
                                    "ext": "" if is_dir else p.suffix.lower().lstrip("."),
                                    "size": 0 if is_dir else p.stat().st_size})
                except OSError:
                    continue
                if len(entries) >= 400:
                    break
        except OSError as e:
            return {"ok": False, "msg": str(e), "path": str(safe), "entries": []}
        parent = "" if safe.parent == safe else str(safe.parent)
        return {"ok": True, "path": str(safe), "parent": parent, "entries": entries}

    def fs_read(self, path):
        """Pratonton teks. Fail binari ditolak, bukan dihantar sebagai mojibake."""
        p = self._safe_path(path)
        if p is None or not p.is_file():
            return {"ok": False, "msg": "File missing, or outside the workspace."}
        if p.stat().st_size > 2 * 1024 * 1024:
            return {"ok": False, "msg": "File is over 2 MB — open it outside the stage."}
        try:
            raw = p.read_bytes()
        except OSError as e:
            return {"ok": False, "msg": str(e)}
        if b"\x00" in raw[:4096]:
            return {"ok": False, "msg": "Binary file — no text preview.", "binary": True}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", "replace")
        return {"ok": True, "name": p.name, "path": str(p), "size": len(raw),
                "lines": text.count("\n") + 1, "text": text[:200_000]}

    def fs_open(self, path):
        """Escape hatch: buka fail dengan app lalai Windows. Butang 'Buka luar' sahaja."""
        p = self._safe_path(path)
        if p is None or not p.exists():
            return {"ok": False, "msg": "File missing, or outside the workspace."}
        try:
            os.startfile(str(p))
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "msg": str(e)}

    # ---------- ujian hidup: tool tanpa Claude ----------
    def chat_tool_probe(self, tool, arg):
        """Jalankan satu tool chat terus, supaya harness dapat mengesahkan
        `_emit("tool")` benar-benar sampai ke orb tanpa memanggil model."""
        try:
            key = "keyword" if tool == "find_files" else ("path" if tool == "read_file" else "folder")
            return {"ok": True, "out": str(self._chat_tool(tool, {key: arg}))}
        except Exception as e:
            return {"ok": False, "msg": f"{type(e).__name__}: {e}"}

    # ---------- Dock: satu peta untuk tiga tab ----------
    def dock_map(self):
        """Tiga senarai dock dalam satu panggilan: desktop, apps, folders.

        Dock di HUD dibina statik dalam HTML; ia tidak pernah tahu apa yang
        ada pada mesin ini. Peta ini menjadikannya hidup tanpa menulis semula
        markup — setiap tile membawa `open` yang cukup untuk api.dock_open().
        """
        desk = []
        d = known_folder("Desktop")
        if d is not None and d.is_dir():
            try:
                entries = [p for p in d.iterdir()
                           if not p.name.startswith(".") and p.name.lower() != "desktop.ini"]
            except OSError:
                entries = []
            entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
            for p in entries[:24]:
                desk.append({"name": (p.stem if p.suffix.lower() in (".lnk", ".url") else p.name),
                             "dir": p.is_dir(), "path": str(p)})
        apps, folders = [], []
        for item in load_json(SHORTCUTS, {}).get("apps", []):
            t = resolve(item)
            apps.append({"name": item.get("name", "?"), "path": str(t) if t else "",
                         "ok": t is not None})
        for item in load_json(SHORTCUTS, {}).get("folders", []):
            t = resolve(item)
            folders.append({"name": item.get("name", "?"), "path": str(t) if t else "",
                            "ok": t is not None and Path(t).is_dir()})
        return {"ok": True, "desktop": desk, "apps": apps, "folders": folders}

    def dock_open(self, kind, name):
        """Klik satu tile dock.

        `kind` ialah 'desktop' | 'apps' | 'folders'. Folder dibuka DALAM panel
        fail HUD (bukan tetingkap Explorer bertimbun); app dilancarkan.
        Desktop juga folder, jadi ia melalui laluan yang sama.
        """
        kind = (kind or "").strip().lower()
        want = (name or "").strip().lower()
        if not want:
            return {"ok": False, "msg": "No name given."}
        if kind in ("desktop",):
            base = known_folder("Desktop")
            if base is None:
                return {"ok": False, "msg": "No Desktop folder."}
            try:
                for p in base.iterdir():
                    if ((p.stem if p.suffix.lower() in (".lnk", ".url") else p.name).lower() == want
                            or p.name.lower() == want):
                        if p.is_dir():
                            return {"ok": True, "folder": str(p)}
                        os.startfile(str(p))
                        return {"ok": True, "opened": str(p)}
            except OSError as e:
                return {"ok": False, "msg": str(e)}
            return {"ok": False, "msg": f'"{name}" is not on the Desktop.'}
        group = "apps" if kind in ("apps", "app") else "folders"
        for item in load_json(SHORTCUTS, {}).get(group, []):
            if item.get("name", "").strip().lower() != want:
                continue
            t = resolve(item)
            if t is None:
                return {"ok": False, "msg": f'"{name}" is not on this machine.'}
            if Path(t).is_dir():
                return {"ok": True, "folder": str(t)}
            try:
                os.startfile(str(t))
                return {"ok": True, "opened": str(t)}
            except OSError:
                try:
                    subprocess.Popen(str(t), shell=True, creationflags=NO_WINDOW)
                    return {"ok": True, "opened": str(t)}
                except Exception as e:
                    return {"ok": False, "msg": str(e)}
        return {"ok": False, "msg": f'"{name}" is not in shortcuts.json.'}

    # ---------- Stage: dokumen (Fasa 6) ----------
    # Dibaca di Python, bukan di browser. PDF.js + docx-preview + SheetJS akan
    # jadi ~3 MB JS yang perlu npm build dan versi yang mesti dijaga; sebaliknya
    # pymupdf, python-docx, python-pptx dan openpyxl sudah ada dalam env ini dan
    # berjalan pada mesin yang sama. Yang dihantar ke stage ialah blok struktur
    # kecil, dan CSS stage yang mewarnakannya.
    DOC_MAX_BYTES = 40 * 1024 * 1024

    def docs_open(self, path, page=None):
        """Buka satu dokumen untuk dibaca dalam stage. Tiada tulis, tiada ubah."""
        p = self._safe_path(path)
        if p is None or not p.is_file():
            return {"ok": False, "msg": "File missing, or outside the workspace."}
        if p.stat().st_size > self.DOC_MAX_BYTES:
            return {"ok": False, "msg": "File is over 40 MB — open it outside the stage."}
        ext = p.suffix.lower().lstrip(".")
        handler = {"pdf": self._doc_pdf, "docx": self._doc_docx, "pptx": self._doc_pptx,
                   "xlsx": self._doc_xlsx, "xlsm": self._doc_xlsx,
                   "md": self._doc_text, "markdown": self._doc_text, "txt": self._doc_text,
                   "csv": self._doc_csv, "json": self._doc_text, "log": self._doc_text}.get(ext)
        if handler is None:
            return {"ok": False, "msg": ".%s files are not supported in the stage yet." % ext}
        try:
            out = handler(p, page)
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}
        out.setdefault("ok", True)
        out.update({"name": p.name, "path": str(p), "ext": ext,
                    "size": p.stat().st_size, "kind": out.get("kind", ext)})
        if out.get("kind") == "pptx":
            # A deck is now the thing being presented. Later keystrokes move it.
            self._deck = {"path": str(p), "slide": out.get("page") or 1,
                          "total": out.get("total") or len(out.get("slides") or [])}
        else:
            self._deck["path"] = None
        return out

    def _wire_drop(self, window):
        """Hidupkan seret-lepas: daftar satu listener 'drop' supaya WebView2
        menghantar laluan sebenar, kemudian kutip laluan itu dan hantar ke stage.

        pywebview menyimpan laluan dalam _dnd_state['paths'] dan tidak
        memanggil balik sesiapa. Ia juga berhenti awal dalam on_script_notify
        bila num_listeners == 0, jadi listener mesti didaftar melalui
        webview.dom — bukan addEventListener biasa dalam halaman.
        """
        try:
            from webview.dom import _dnd_state
        except ImportError:
            return
        try:
            # create_element menunggu events.loaded, jadi ini selamat di sini.
            sink = window.dom.create_element('<div id="dropSink" hidden></div>', window.dom.body)
            sink.on('drop', lambda e: None)
        except Exception:
            return     # dialog File… / Folder… kekal sebagai jalan yang berfungsi

        seen = 0
        # Bounded, not "while True": this runs on the GUI thread, and once the
        # window is gone there is nothing to push to. Two hours of watching is
        # far past any session; a stale loop is a leak with no upside.
        for _ in range(18_000):
            time.sleep(0.4)
            try:
                paths = _dnd_state['paths']
                if len(paths) <= seen:
                    continue
                fresh = paths[seen:]
                seen = len(paths)
                real = []
                for _name, full in fresh:
                    p = self._safe_path(full)
                    if p is not None and p.exists():
                        real.append(str(p))
                if not real:
                    self._push("window.stageDropFail && window.stageDropFail()")
                    continue
                kind = "file" if len(real) == 1 and Path(real[0]).is_file() else "folder"
                self._push("window.stagePick && window.stagePick(%s, %s)"
                           % (json.dumps(real), json.dumps(kind)))
            except Exception:
                continue


    # Dua jalan masuk, satu laporan. Dialog ialah jalan yang akan berfungsi
    # setiap kali — ia API dokumentasi pywebview. Seret-lepas bergantung pada
    # WebView2 menghantar laluan sebenar melalui FilesDropped, yang hanya
    # hidup bila ada listener 'drop' didaftarkan pada DOM.
    # ---------- Stage: apa dalam fail / folder ----------

    def pick_upload(self, kind="file"):
        """Buka dialog Windows. Pulangkan laluan yang lulus _safe_path sahaja.

        Memilih fail sendiri bukan alasan untuk melangkau _safe_path: dialog
        boleh dihantar ke mana-mana folder melalui kotak alamatnya, jadi
        sempadan kerja masih perlu diperiksa selepas pilihan.
        """
        try:
            import webview as _wv
            FD = _wv.FileDialog
            if kind == "folder":
                res = self._window.create_file_dialog(FD.FOLDER)
            else:
                res = self._window.create_file_dialog(FD.OPEN, allow_multiple=True)
        except Exception as e:
            return {"ok": False, "msg": "The picker did not open: %s" % e}
        if not res:
            return {"ok": False, "msg": "", "cancel": True}
        if isinstance(res, str):
            res = (res,)
        picked, rejected = [], []
        for raw in res:
            p = self._safe_path(raw)
            if p is None or not p.exists():
                rejected.append(Path(str(raw)).name)
            else:
                picked.append(str(p))
        if not picked:
            return {"ok": False, "msg": "That is outside the workspace.", "rejected": rejected}
        return {"ok": True, "paths": picked, "rejected": rejected}

    def _resolve_target(self, raw):
        """Laluan penuh, atau nama folder/fail yang dicari dalam akar kerja.

        Model sering memulangkan "Downloads" dan bukan
        "C:\\Users\\akmal\\Downloads". Mencari nama itu dalam akar yang sama
        dengan _safe_path lebih berguna daripada menolaknya — tetapi carian
        masih terkurung dalam akar itu, jadi ia tidak membuka apa-apa yang
        _safe_path tidak benarkan.
        """
        p = self._safe_path(raw)
        if p is not None and p.exists():
            return p
        want = Path(os.path.expanduser(str(raw))).name.lower()
        if not want:
            return None
        cfg = load_json(CONFIG, {})
        roots = [Path(os.path.expanduser(cfg.get("workdir", "~"))), ROOT, HOME / "Desktop",
                 HOME / "Documents", HOME / "Downloads"]
        for item in load_json(SHORTCUTS, {}).get("folders", []):
            t = resolve(item)
            if t is not None:
                roots.append(Path(t))
        for r in roots:
            try:
                cand = r.resolve() / want
                if cand.exists():
                    return self._safe_path(cand)
            except OSError:
                continue
        return None

    def analyse_path(self, path=None, paths=None):
        """Ukur fail atau folder, kemudian lukis laporan itu.

        Angka datang dari inspect_path (os.scandir), bukan dari model. Model
        hanya dipanggil kemudian, di _run_chat, untuk menutup dengan satu
        ayat — laporan yang salah kira tetapi nampak meyakinkan lebih teruk
        daripada laporan yang gagal.
        """
        targets = []
        for raw in (paths or ([path] if path else [])):
            p = self._resolve_target(raw)
            if p is not None and p.exists():
                targets.append(p)
        if not targets:
            return {"ok": False, "msg": "Nothing readable in that selection."}
        if len(targets) > 12:
            return {"ok": False, "msg": "Twelve at a time, otherwise the report says nothing."}

        self._emit("tool", {"name": "Inspecting",
                            "detail": "measuring %d object%s" % (len(targets),
                                                                 "" if len(targets) == 1 else "s"),
                            "full": ""})
        reports, failed = [], []
        for p in targets:
            d = ip.inspect(p)
            if d.get("ok"):
                reports.append(d)
            else:
                failed.append("%s — %s" % (p.name, d.get("msg", "unreadable")))

        if not reports:
            return {"ok": False, "msg": "; ".join(failed) or "Nothing could be read."}

        if len(reports) == 1:
            dash = ip.dashboard(reports[0])
            rows = ip.listing(reports[0])
            title = reports[0]["name"]
        else:
            dash, rows, title = self._multi_report(reports)

        if not dash:
            return {"ok": False, "msg": "That came back empty."}

        self._analysis_shown = True
        self._chat_tool("present_analysis", dash)
        if rows:
            self._push("window.stageFeed && window.stageFeed(%s)"
                       % json.dumps({"title": title, "rows": rows[:200]},
                                    ensure_ascii=False))
        lines = self._report_lines(reports, failed)
        return {"ok": True, "title": title, "summary": dash.get("summary", ""),
                "spoken": lines, "count": len(rows)}

    def _multi_report(self, reports):
        """Beberapa fail dipilih sekali gus — satu laporan, bukan lima."""
        rows, cards, charts, pts = [], [], [], []
        total = sum(r.get("size", 0) for r in reports)
        kinds = {}
        for r in reports:
            k = r.get("type") if r.get("kind") == "file" else "folder"
            kinds[k] = kinds.get(k, 0) + 1
            rows.append({"path": r["name"], "size": r.get("size", 0),
                         "size_h": r.get("size_h", ""), "date": r.get("modified", ""),
                         "type": k})
        cards = [
            {"label": "Selected", "value": str(len(reports)), "note": "files and folders"},
            {"label": "Total size", "value": ip._human(total),
             "note": "avg %s each" % ip._human(total / len(reports))},
            {"label": "Mostly", "value": max(kinds, key=kinds.get) if kinds else "mixed",
             "note": "by count"},
            {"label": "Largest", "value": max(r.get("size_h") or "0 B", key=len),
             "note": "single object"},
        ]
        charts = [{"title": "What was picked", "kind": "donut",
                   "items": [{"label": k, "value": v, "display": str(v)}
                             for k, v in sorted(kinds.items(), key=lambda x: -x[1])]},
                  {"title": "Size by object", "kind": "bar",
                   "items": [{"label": r["name"][:18], "value": r.get("size", 0),
                              "display": r.get("size_h", "")}
                             for r in sorted(reports, key=lambda x: -x.get("size", 0))[:8]]}]
        pts = [{"text": "%d objects, %s together." % (len(reports), ip._human(total)),
                "target": "card:0"},
               {"text": "Largest is %s." % max(reports, key=lambda r: r.get("size", 0))["name"],
                "target": "card:3"}]
        return ({"title": "Report — %d objects" % len(reports),
                 "summary": "%d objects · %s" % (len(reports), ip._human(total)),
                 "cards": cards, "charts": charts, "points": pts,
                 "followups": ["Which one is the biggest?", "What is duplicated?"]},
                rows, "%d objects" % len(reports))

    def _report_lines(self, reports, failed):
        """Fakta tepat untuk model — supaya ayat penutup tidak mereka angka."""
        out = []
        for r in reports[:6]:
            if r["kind"] == "folder":
                out.append("%s: folder, %d files, %d dirs, %s, mostly %s, newest %s"
                           % (r["name"], r["files"], r["dirs"], r["size_h"],
                              r["types"][0][0] if r["types"] else "mixed", r["newest"]))
            else:
                out.append("%s: %s file, %s, %s, modified %s"
                           % (r["name"], r["ext"] or "no extension", r["size_h"],
                              r["type"], r["age"]))
        if failed:
            out.append("could not read: " + "; ".join(failed))
        return "\n".join(out)

    def _doc_pdf(self, p, page=None):
        """Teks per halaman, dan imej halaman semasa untuk bentuk asal."""
        try:
            import pymupdf as fitz  # nama baru; `fitz` sudah deprecated dalam 1.28
        except ImportError:
            import fitz
        doc = fitz.open(str(p))
        try:
            total = doc.page_count
            i = max(0, min(total - 1, int(page or 0)))
            pages = [{"n": k + 1, "text": doc[k].get_text("text").strip()} for k in range(min(total, 60))]
            # imej pada 130 dpi: cukup tajam untuk dibaca, kecil untuk dihantar
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(130 / 72, 130 / 72))
            png = base64.b64encode(pix.tobytes("png")).decode()
            return {"kind": "pdf", "pages": pages, "total": total, "page": i,
                    "image": "data:image/png;base64," + png,
                    "w": pix.width, "h": pix.height}
        finally:
            doc.close()

    def _doc_docx(self, p, page=None):
        """Perenggan + jadual, bukan HTML — gaya kekal di CSS stage."""
        import docx
        d = docx.Document(str(p))
        blocks = []
        for para in d.paragraphs:
            txt = para.text.strip()
            if not txt:
                continue
            style = (para.style.name or "").lower()
            level = 0
            if style.startswith("heading"):
                try:
                    level = int(style.split()[-1])
                except ValueError:
                    level = 1
            elif style == "title":
                level = 1
            blocks.append({"t": "h" if level else "p", "l": level, "x": txt})
        for t_i, table in enumerate(d.tables):
            rows = []
            for row in table.rows[:80]:
                rows.append([c.text.strip()[:200] for c in row.cells])
            if rows:
                blocks.append({"t": "table", "n": t_i + 1, "rows": rows})
        return {"kind": "docx", "blocks": blocks[:600],
                "counts": {"paras": len(d.paragraphs), "tables": len(d.tables)}}

    def _doc_pptx(self, p, page=None):
        import pptx
        pr = pptx.Presentation(str(p))
        total = len(pr.slides)
        slides = []
        # slides[:n] memulangkan list, dan pemanggil dalaman python-pptx
        # kemudian panggil .rId padanya — jadi akses ikut indeks, bukan slice.
        for i in range(min(total, 80)):
            s = pr.slides[i]
            title_shape = s.shapes.title
            title_id = title_shape.shape_id if title_shape is not None else None
            title, body = "", []
            for sh in s.shapes:
                if not sh.has_text_frame:
                    continue
                txt = sh.text_frame.text.strip()
                if not txt:
                    continue
                if title_id is not None and sh.shape_id == title_id and not title:
                    title = txt
                else:
                    body.append(txt)
            slides.append({"n": i + 1, "title": title or ("Slide %d" % (i + 1)), "body": body})
        # `page` is the slide the deck is showing right now. The doc pane marks
        # it and scrolls to it, so when Akmal says "next slide" the text pane
        # and the projector agree instead of drifting apart.
        cur = None
        try:
            cur = max(1, min(int(page), total)) if page else 1
        except (TypeError, ValueError):
            cur = 1
        return {"kind": "pptx", "slides": slides, "total": total, "page": cur}

    def _doc_xlsx(self, p, page=None):
        """Setiap helaian jadi grid, tetapi hanya 200 baris pertama setiap satu."""
        import openpyxl
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        try:
            sheets = []
            for name in wb.sheetnames[:12]:
                ws = wb[name]
                rows, truncated = [], False
                for r_i, row in enumerate(ws.iter_rows(values_only=True)):
                    if r_i >= 200:
                        truncated = True
                        break
                    cells = ["" if v is None else (v if isinstance(v, (int, float)) else str(v)[:120])
                             for v in row[:30]]
                    if any(str(c).strip() for c in cells):
                        rows.append(cells)
                sheets.append({"name": name, "rows": rows, "truncated": truncated,
                               "dims": ws.max_row and "%d×%d" % (ws.max_row, ws.max_column or 0)})
            return {"kind": "xlsx", "sheets": sheets}
        finally:
            wb.close()

    def _doc_csv(self, p, page=None):
        import csv
        rows = []
        with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
            for i, row in enumerate(csv.reader(f)):
                if i >= 300:
                    break
                rows.append([c[:120] for c in row[:30]])
        return {"kind": "csv", "sheets": [{"name": p.stem, "rows": rows, "truncated": len(rows) >= 300}]}

    def _doc_text(self, p, page=None):
        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", "replace")
        return {"kind": "text", "text": text[:200_000], "lines": text.count("\n") + 1}

    # ---------- Stage: tulis fail (EDITOR) ----------
    def fs_write(self, path, text, expected_size=None):
        """Simpan teks ke fail. Gated oleh _safe_path + semakan konflik.

        Tiga pagar, sebab satu-satunya fungsi yang mengubah fail Akmal:

        1. _safe_path — skop sama seperti fs_list/fs_read. Luar kawasan kerja tolak.
        2. expected_size — saiz fail semasa masa ianya dibuka. Kalau berubah di
           antara, fail telah disentuh di luar editor, jadi tulis ditolak dan
           editor boleh tanya Akmal nak timpa atau tidak. Ini yang menghalang
           tab lama memadam kerja yang lebih baru.
        3. simpanan .bak sekali — bukan versioning, cuma jaring untuk satu
           pusingan salah. Ditulis sebelum tulis baru, ditimpa setiap simpan.

        Tiada direktori baru dicipta. Kalau folder tiada, itu silap pemanggil.
        """
        p = self._safe_path(path)
        if p is None:
            return {"ok": False, "msg": "Path outside the workspace — nothing written."}
        if not p.parent.is_dir():
            return {"ok": False, "msg": f"Parent folder missing: {p.parent}"}
        if p.exists():
            if p.is_dir():
                return {"ok": False, "msg": "That is a folder, not a file."}
            try:
                current = p.stat().st_size
            except OSError as e:
                return {"ok": False, "msg": str(e)}
            # only enforce when the caller tracked a size; a fresh save of a new
            # file passes no expected_size and skips straight through
            if expected_size is not None and int(expected_size) != current:
                return {"ok": False, "conflict": True, "size": current,
                        "msg": f"File changed outside the editor ({current} bytes, "
                               f"expected {expected_size}). Press Save again to overwrite."}
            try:
                shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
            except OSError:
                pass  # a missing backup must never block the actual save
        data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
        try:
            p.write_bytes(data)
        except OSError as e:
            return {"ok": False, "msg": str(e)}
        line_count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        self._emit("fs", {"saved": str(p), "size": len(data)})
        return {"ok": True, "path": str(p), "size": len(data), "lines": max(1, line_count)}

    # ---------- Stage: buka media melalui arahan suara/teks ----------
    def open_media(self, which=""):
        return self.media_open(which) if which else self.media_list()

    # ---------- Shortcut ----------
    def get_shortcuts(self):
        data = load_json(SHORTCUTS, None)
        if data is None:
            return {"error": "Could not read shortcuts.json.", "folders": [], "apps": []}
        self._items = {k: v for k, v in self._items.items() if k.startswith("desk:")}
        out = {}
        for group in ("folders", "apps"):
            out[group] = []
            for i, item in enumerate(data.get(group, [])):
                key = f"{group}:{i}"
                target = resolve(item)
                self._items[key] = target
                out[group].append({"id": key, "name": item.get("name", "?"), "ok": target is not None})
        return out

    def open_item(self, key):
        target = self._items.get(key)
        if target is None:
            return {"ok": False, "msg": "Target not found on this PC."}
        try:
            os.startfile(str(target))
        except OSError:
            try:
                subprocess.Popen(str(target), shell=True, creationflags=NO_WINDOW)
            except Exception as e:
                return {"ok": False, "msg": str(e)}
        return {"ok": True}

    def list_desktop(self):
        """Senarai folder dan fail atas Desktop, folder dulu."""
        desk = known_folder("Desktop")
        if desk is None:
            return []
        entries = [p for p in desk.iterdir()
                   if p.name.lower() != "desktop.ini" and not p.name.startswith("~$")]
        entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
        out = []
        for i, p in enumerate(entries):
            key = f"desk:{i}"
            self._items[key] = p
            is_dir = p.is_dir()
            name = p.stem if p.suffix.lower() in (".lnk", ".url") else p.name
            out.append({"id": key, "name": name, "dir": is_dir, "ext": "" if is_dir else p.suffix.lower().lstrip("."), "ok": True})
        return out

    def search_web(self, query):
        webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
        return {"ok": True}

    def open_url(self, url):
        """Buka hasil carian (klik nod dalam hologram). Hanya pautan web."""
        if not re.match(r"^https?://", str(url)):
            return {"ok": False}
        webbrowser.open(url)
        return {"ok": True}

    # ---------- Stage: WEB (Fasa 6) ----------
    # Two paths, chosen per site, because neither one covers the web alone:
    #   iframe     — fast, in-surface, but half the internet sends
    #                X-Frame-Options/X-Frame-DENY and simply will not load
    #   child win  — a real WebView2 window with its own history, cookies and
    #                JS engine. Renders everything, at the cost of being a
    #                separate window that has to track the stage's rect.
    # A DOM snapshot was rejected: it looks right for a second, then every
    # script-driven site renders dead and scrolling never works.
    def _browse_rect(self):
        """Rect the child window should occupy, in screen px."""
        r = self._stage_rect or {}
        try:
            x, y, w, h = (int(r.get(k, 0)) for k in ("x", "y", "w", "h"))
        except (TypeError, ValueError):
            return None
        # a rect arriving before the HUD has drawn is not a position, it is a
        # default. Refuse rather than park a browser in the corner.
        if w < 320 or h < 240:
            return None
        return x, y, w, h

    def web_stage_rect(self, x, y, w, h):
        """The stage tells Python where its browse-body sits. Cheap; call on
        pane open, resize and scroll, never on a timer."""
        self._stage_rect = {"x": x, "y": y, "w": w, "h": h}
        win = getattr(self, "_web_win", None)
        rect = self._browse_rect()
        if win is not None and rect:
            try:
                win.move(rect[0], rect[1])
                win.resize(rect[2], rect[3])
            except Exception:
                pass  # window closing; on_closed will clean up
        return {"ok": True}

    def web_open(self, url, notify=True):
        """Open a URL in the child window, creating it the first time.

        `notify` wujud kerana gelung: panel WEB sendiri memanggil web_open
        melalui `go()`, dan `go()` sudah menetapkan curUrl serta melukis
        keadaannya. Kalau web_open pula menghantar `_emit("web", {"url": u})`,
        onClaude memanggil `stageWeb.open(d.url)`, yang memanggil `go()` sekali
        lagi, yang memanggil `web_open` sekali lagi — tanpa henti. Ujian hidup
        menangkapnya: 6 panggilan web_open dalam 12 saat dan pendua tetingkap
        bertindih pada panel yang sama. Pemanggil dari JS menghantar
        notify=false; suara dan model kekal notify=true supaya panel ikut
        bertukar.
        """
        u = str(url or "").strip()
        if not u:
            return {"ok": False, "msg": "Empty address."}
        if not re.match(r"^https?://", u):
            u = "https://" + u
        # a bare host with no dot is a search, not a site — same call the
        # address bar makes, so the two never disagree
        if not re.match(r"^https?://[^/\s]+\.[^/\s]+", u):
            return self.web_search(u.split("://", 1)[-1])

        rect = self._browse_rect() or (0, 0, 1100, 720)
        win = getattr(self, "_web_win", None)
        if win is not None:
            try:
                win.load_url(u)
                win.show()
                win.move(rect[0], rect[1])
                win.resize(rect[2], rect[3])
                self._web_url = u
                self._web_open = True
                if notify:
                    self._emit("web", {"query": "", "links": [], "url": u})
                return {"ok": True, "url": u, "reused": True}
            except Exception:
                # the child died between the last call and this one; drop the
                # handle and rebuild below rather than leaving a dead binding
                self._web_win = None

        # Satu tetingkap sahaja pada satu masa. Kalau baki tetingkap lama masih
        # ada (pengguna tutup HUD tanpa web_close, atau destroy() lambat), kita
        # akan bertindih dengan tetingkap hantu yang kekal atas stage.
        for stale in [x for x in self._web_stale if x]:
            try:
                stale.destroy()
            except Exception:
                pass
        self._web_stale = []

        # create_window from a non-main thread is the supported pywebview path
        # (the JS bridge runs off the main thread), so this does not block and
        # does not need a separate thread of our own.
        try:
            win = webview.create_window(
                "Jarvis · Web",
                u,
                width=rect[2], height=rect[3], x=rect[0], y=rect[1],
                background_color="#140d26",
                on_top=True,
            )
        except Exception as e:
            return {"ok": False, "msg": f"Web window failed to open: {e}"}
        if win is None:
            return {"ok": False, "msg": "The web window could not be started."}
        self._web_win = win
        self._web_url = u
        self._web_open = True

        def _closed():
            # HUD's WEB pane must not keep claiming a browser is open — but
            # only if this handle is still the current one. Bila tetingkap
            # lama dimusnahkan selepas yang baharu dibina, callback lama ini
            # akan menulenkan pemegang baharu dan panel kehilangan browser
            # yang sebenarnya masih hidup.
            if self._web_win is not win:
                return
            self._web_win = None
            self._web_url = ""
            self._web_open = False
            self._emit("web", {"query": "", "links": [], "closed": True})

        try:
            win.events.closed += _closed
        except Exception:
            pass
        if notify:
            self._emit("web", {"query": "", "links": [], "url": u})
        return {"ok": True, "url": u, "reused": False}

    def web_show(self):
        """Balik ke panel WEB: tunjukkan semula tetingkap yang diparkir.

        `Window.show()` ternyata boleh dipercayai — diukur, bukan diandaikan:
        show() → gui.show(uid) → BrowserForm.Show() + Activate(), handle Form
        kekal sama, IsWindowVisible bertukar False → True, dan halaman tidak
        dimuat semula. (Kisah "show() mencipta semula tetingkap" datang dari
        on_shown → set_title() → `self._window.Text = ...`; bacaan sumber
        mengesahkannya wujud, tetapi ukuran menunjukkan handle tidak berubah,
        jadi ia bukan punca tetingkap hantu yang kita lihat.)

        Sebab itu kita cuba show() dahulu — murah, dan skrol serta borang
        separuh isi kekal. Penciptaan semula hanya berlaku kalau pemegang sudah
        mati atau web_close sudah menandakan _web_open = False.
        """
        win = getattr(self, "_web_win", None)
        url = getattr(self, "_web_url", "") or ""
        rect = self._browse_rect()

        if win is not None and self._web_open:
            try:
                win.show()
                if rect:
                    try:
                        win.move(rect[0], rect[1])
                        win.resize(rect[2], rect[3])
                    except Exception:
                        pass      # geometri gagal tidak bermakna laman hilang
                return {"ok": True, "already": True, "reloaded": False}
            except Exception:
                # pemegang mati; jatuh ke penciptaan semula di bawah
                self._web_win = None
                self._web_open = False

        if not url:
            return {"ok": False, "already": False, "reloaded": False}
        # notify=False: panel WEB yang memanggil ini sedang memaparkan URL itu;
        # _emit di sini akan memanggil go() → web_open sekali lagi.
        r = self.web_open(url, notify=False)
        r["reloaded"] = bool(r.get("ok"))
        return r

    def web_hide(self):
        """Parkir tetingkap anak bila panel bertukar.

        Tukar panel memanggil ini, bukan web_close: butang × dan setMode('embed')
        yang memusnahkan. `win.hide()` menghalakan Hide() ke GUI thread dan pada
        amalannya berkesan — tetapi kita tidak bergantung padanya untuk
        kebenaran. `_web_open` kekal benar selagi pemegang wujud, dan web_show()
        yang memutuskan sama ada ia boleh dihidupkan semula atau perlu dibina
        semula. Itu menjadikan keadaan di pihak Python, bukan di pihak HWND
        yang tidak boleh dipercayai.
        """
        win = getattr(self, "_web_win", None)
        if win is None:
            return {"ok": True, "already": True}
        try:
            win.hide()
        except Exception:
            self._web_win = None
            self._web_open = False
            return {"ok": True, "already": False}
        return {"ok": True, "already": True}

    def web_close(self):
        """Musnahkan tetingkap anak dan lupakan URL.

        `win.destroy()` menjadualkan Close() pada GUI thread, jadi ia tidak
        selesai bila fungsi ini pulang. Cara lama menunggu dengan memeriksa
        `app_hwnd("Jarvis · Web")` — itu tidak boleh dipercayai, kerana satu
        tetingkap pywebview meninggalkan puluhan HWND dengan tajuk yang sama
        walaupun selepas ia mati. Yang jujur ialah `win.events.closed`, yang
        pywebview set dari on_close() selepas FormClosed benar-benar berlaku.

        Tunggu 3 saat; kalau masih belum tertutup, simpan pemegang dalam
        _web_stale supaya web_open berikutnya cuba destroy sekali lagi. Itu
        jaring keselamatan, bukan laluan biasa.
        """
        win = getattr(self, "_web_win", None)
        self._web_win = None
        self._web_url = ""
        self._web_open = False
        if win is None:
            return {"ok": True, "already": True}
        try:
            win.destroy()
        except Exception:
            return {"ok": True, "already": False}
        try:
            if win.events.closed.wait(3):
                return {"ok": True, "already": False}
        except Exception:
            pass
        self._web_stale.append(win)
        return {"ok": True, "already": False, "lingering": True}

    def web_search(self, query, notify=True):
        """Search in the child window, not the system browser — the whole point
        of the WEB pane is that it stays inside the HUD.

        `notify` sama seperti web_open: pemanggil dari panel WEB sendiri sudah
        tahu URL yang ia minta, jadi mengembalikan URL itu melalui `_emit`
        hanya mencetuskan go() sekali lagi.
        """
        q = str(query or "").strip()
        if not q:
            return {"ok": False, "msg": "Empty search."}
        r = self.web_open("https://duckduckgo.com/?q=" + quote_plus(q), notify=notify)
        if notify is False and r.get("ok"):
            r["query"] = q
        return r

    def edit_shortcuts(self):
        subprocess.Popen(["notepad", str(SHORTCUTS)])
        return {"ok": True}

    # ---------- Statistik ----------
    def get_stats(self):
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(0.001, now - self._net_t)
        down = (net.bytes_recv - self._net.bytes_recv) / dt / 1024
        up = (net.bytes_sent - self._net.bytes_sent) / dt / 1024
        self._net, self._net_t = net, now
        mem = psutil.virtual_memory()
        bat = psutil.sensors_battery()
        return {
            "cpu": psutil.cpu_percent(None),
            "ram": mem.percent,
            "ram_used": round(mem.used / 1024**3, 1),
            "ram_total": round(mem.total / 1024**3, 1),
            "disk": psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent,
            "battery": None if bat is None else round(bat.percent),
            "plugged": None if bat is None else bat.power_plugged,
            "down": round(down, 1),
            "up": round(up, 1),
            "procs": len(psutil.pids()),
            "boot": psutil.boot_time(),
        }

    # ---------- Claude Code ----------
    def claude_info(self):
        cfg = load_json(CONFIG, {})
        s = load_json(SECRETS, {})
        return {"ok": bool(self._claude), "model": cfg.get("model", "default"),
                "chat": bool(s.get("api_key")), "chat_model": self._chat_model(s), "home": str(HOME),
                "location": cfg.get("location", "")}

    def ask(self, text, engine="claude"):
        if self._proc or self._chat_busy:
            return {"ok": False, "msg": "Jarvis is still working on the previous command."}
        if engine == "chat":
            if not load_json(SECRETS, {}).get("api_key"):
                return {"ok": False, "msg": "Chat API key is not set in secrets.json."}
            self._chat_busy = True
            threading.Thread(target=self._run_chat, args=(text,), daemon=True).start()
            return {"ok": True}
        if not self._claude:
            return {"ok": False, "msg": "Claude Code not found. Make sure the 'claude' command works."}
        threading.Thread(target=self._run_claude, args=(text,), daemon=True).start()
        return {"ok": True}

    def stop(self):
        p = self._proc
        if p:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
        return {"ok": True}

    def new_session(self):
        self._session = None
        self._continue_next = False
        self._chat_history = []
        self._save_session()
        return {"ok": True}

    # ---------- Projek ----------
    def _project_roots(self):
        cfg = load_json(CONFIG, {})
        roots = [known_folder("Desktop"), HOME / "Projects", HOME / "source" / "repos"]
        roots += [Path(os.path.expandvars(os.path.expanduser(r))) for r in cfg.get("project_roots", [])]
        return [r for r in roots if r and r.is_dir()]

    def list_projects(self):
        seen, out = set(), []
        for root in self._project_roots():
            for p in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                if p.is_dir() and not p.name.startswith(".") and p not in seen:
                    seen.add(p)
                    out.append({"name": p.name, "path": str(p), "saved": str(p) in self._sessions})
        return out

    def set_project(self, query):
        """Pilih folder projek ikut nama (atau path penuh). Kosong = keluar mod projek."""
        if not query:
            self._project, self._session = None, None
            return {"ok": True, "name": None}
        target = Path(os.path.expanduser(query))
        if not target.is_dir():
            n = lambda s: "".join(c for c in s.lower() if c.isalnum())
            q, cands = n(query), self.list_projects()
            hit = (next((c for c in cands if n(c["name"]) == q), None)
                   or next((c for c in cands if n(c["name"]).startswith(q)), None)
                   or next((c for c in cands if q in n(c["name"])), None))
            if not hit:
                return {"ok": False, "msg": f'Project "{query}" not found.'}
            target = Path(hit["path"])
        self._project = target
        self._session = self._sessions.get(str(target))
        self._continue_next = False
        return {"ok": True, "name": target.name, "path": str(target), "resumed": bool(self._session)}

    def continue_last(self):
        """Sesi seterusnya sambung perbualan Claude terakhir dalam folder ini (termasuk dari VS Code)."""
        self._session = None
        self._continue_next = True
        return {"ok": True}

    def open_in_vscode(self):
        target = self._project or HOME
        code = shutil.which("code.cmd") or shutil.which("code")
        if not code:
            return {"ok": False, "msg": "VS Code not found."}
        subprocess.Popen([code, str(target)], creationflags=NO_WINDOW)
        return {"ok": True}

    def _save_session(self):
        if self._project:
            if self._session:
                self._sessions[str(self._project)] = self._session
            else:
                self._sessions.pop(str(self._project), None)
            try:
                SESSIONS.write_text(json.dumps(self._sessions, indent=2), encoding="utf-8")
            except OSError:
                pass

    def _chat_model(self, s):
        return load_json(CONFIG, {}).get("chat_model") or s.get("model")

    def _chat_call(self, s, messages, tools=None):
        """Panggil model chat rootsys. Jika lambat/gagal, cuba sekali lagi dengan model sandaran."""
        model = self._chat_model(s)
        fallback = load_json(CONFIG, {}).get("chat_fallback", CHAT_FALLBACK)
        for attempt, m in enumerate([model] + ([fallback] if fallback and fallback != model else [])):
            body = {"model": m, "messages": messages}
            if tools:
                body["tools"] = tools
            req = urllib.request.Request(
                s.get("base_url", "").rstrip("/") + "/chat/completions", method="POST",
                data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": "Bearer " + s["api_key"], "Content-Type": "application/json",
                         "User-Agent": "jarvis-desktop/0.9"},
            )
            try:
                with urllib.request.urlopen(req, timeout=45 if attempt == 0 else 90) as r:
                    return json.load(r)["choices"][0]["message"]
            except Exception as e:
                if attempt == 0 and m != fallback and fallback:
                    self._emit("note", {"text": f"{m} slow/failed ({str(e)[:40]}), switching to {fallback}"})
                    continue
                raise

    def _yt_find(self, query):
        """Cari YouTube dan pulangkan calon video yang BOLEH dimainkan.

        Carian web biasa memulangkan homepage channel dan senarai main, yang
        tiada video id — jadi ia tidak boleh di-embed. Menapis dengan
        `site:youtube.com/watch` memaksa hasil kepada halaman tonton sahaja.
        """
        q = str(query or "").strip()
        q = re.sub(r"\b(dalam|di|on|in|dekat)\s+youtube\b", "", q, flags=re.I).strip() or q
        s = load_json(SECRETS, {})
        raw, tried = [], 0
        if s.get("serper_api_key"):
            for term in (f"site:youtube.com/watch {q}", f"site:youtube.com/watch {q} official video"):
                tried += 1
                try:
                    raw += self._serper_raw(s["serper_api_key"], term, num=10)
                except Exception:
                    pass
                if len([x for x in raw if "watch?v=" in (x.get("link") or "")]) >= 4:
                    break
        seen, out = set(), []
        for x in raw:
            u = x.get("link") or ""
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,20})", u)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            title = clean_yt_title(x.get("title", ""), q)
            out.append({"id": m.group(1), "url": "https://www.youtube.com/watch?v=" + m.group(1),
                        "raw": x.get("title", ""), "title": title or q})
        if not out and not tried:
            return []
        return out

    def play_youtube(self, query, mode="auto"):
        """Main satu video YouTube di dalam stage. Pulangkan {ok, id, title, mode}.

        Tiga jalan, dan yang pertama hampir selalu betul.

        1. "local" (lalai) — muat turun audio/video ke media/ dengan yt-dlp dan
           mainkan sebagai fail tempatan. Ini satu-satunya jalan yang berfungsi
           untuk muzik, dan sebabnya diukur, bukan diandaikan: embed YouTube
           memulangkan **ralat 150** ("pemilik tidak membenarkan embed") untuk
           setiap video muzik yang diuji dalam WebView2 — Hindia, Rick Astley,
           Gangnam Style — pada kedua-dua youtube.com dan youtube-nocookie.com.
           Video bukan muzik (Me at the zoo) pula main dengan baik di nocookie.
           Jadi 150 itu bukan pepijat kita dan bukan salah video; ia polisi
           content ID, dan tiada pembaikan dari dalam kod kita. Fail tempatan
           tidak tertakluk kepada polisi itu langsung.

        2. "embed" — iframe sahaja. Berguna untuk video bukan muzik yang memang
           dibenarkan embed, dan tiada muat turun.

        3. "browser" — buka Chrome sebenar dan masukkan tetingkapnya ke stage.
           Ini jalan terakhir. Ia berfungsi, tetapi tetingkap Chromium yang
           di-reparent menjadi **kosong putih**: Chromium tidak melukis semula
           selepas SetParent. Disahkan dengan tangkapan skrin, bukan diandaikan.

        Dua perkara lain yang diukur dan menentukan bentuk kod ini:

        * WebView2 tidak boleh main VP9/Opus (webm) — `error 4`, codec tiada.
          m4a/AAC dan mp4/H.264 main. Jadi format muxed `18` (mp4) diutamakan:
          satu fail, gambar dan bunyi, tiada ffmpeg diperlukan.
        * Autoplay disekat secara lalai. `--autoplay-policy=
          no-user-gesture-required` dalam WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
          membukanya — tanpa itu fail dimuatkan tetapi tidak bermain.
        """
        q = str(query or "").strip()
        if not q:
            return {"ok": False, "msg": "YouTube: no song or video named."}
        mode = str(mode or "auto").strip().lower()
        if mode in ("", "auto", "true", "yes"):
            mode = "local"
        prev = getattr(self, "_last_yt", None)
        if mode != "browser" and prev and prev.get("title"):
            # "main lagu tu" — the follow-up usually names nothing, because the
            # song is already in the conversation. Reuse the last resolved song
            # rather than searching for the literal words "lagu tu".
            if re.fullmatch(r"(main|play|putar|pasang|lagu tu|video tu|yang tadi|itu)[\s\W]*", q, re.I):
                q = prev["title"]
        cands = self._yt_find(q)
        if not cands:
            return {"ok": False, "msg": f'YouTube: nothing playable found for "{q}".'}
        tokens = [t for t in re.split(r"\W+", q.lower()) if len(t) > 2]
        best = max(cands, key=lambda c: (
            sum(1 for t in tokens if t in (c["title"] or "").lower()),
            -cands.index(c),
        ))
        self._last_yt = best
        title = best.get("title") or q

        if mode == "local":
            r = self._fetch_local(best)
            if r.get("ok"):
                self._emit("media", {"items": self.media_index(), "play": r["name"]})
                return {"ok": True, "id": best["id"], "url": best["url"], "title": title,
                        "mode": "local", "name": r["name"], "size": r.get("size", 0)}
            # A download that fails should not swallow the request: fall back to
            # the embed, which still works for non-music videos.
            self._emit("web", {"query": q, "links": [], "url": best["url"]})
            return {"ok": True, "id": best["id"], "url": best["url"], "title": title,
                    "mode": "embed", "fell_back": r.get("msg", "")}

        if mode == "browser":
            r = self._play_in_browser(best["url"])
            return {"ok": r.get("ok", False), "id": best["id"], "url": best["url"],
                    "title": title, "mode": "browser", "msg": r.get("msg", "")}

        self._emit("web", {"query": q, "links": [], "url": best["url"]})
        return {"ok": True, "id": best["id"], "url": best["url"],
                "title": title, "mode": "embed", "candidates": len(cands)}

    def _fetch_local(self, cand):
        """Muat turun satu video ke media/ dan pulangkan failnya.

        Format `18` didahulukan: mp4 muxed (H.264 + AAC). Satu fail bermakna
        tiada ffmpeg diperlukan untuk mencantumkan gambar dan bunyi, dan
        gabungan codec itu yang paling pasti dimainkan WebView2.
        """
        try:
            import yt_dlp
        except Exception as e:
            return {"ok": False, "msg": "yt-dlp is not installed: %s" % e}
        MEDIA.mkdir(parents=True, exist_ok=True)
        opts = {
            "format": "18/best[ext=mp4][vcodec!=none][acodec!=none]/bestaudio[ext=m4a]/bestaudio",
            "outtmpl": str(MEDIA / "%(id)s.%(ext)s"),
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            # YouTube now needs a JS runtime to solve its player challenge; node
            # is present on this machine. Without it extraction stalls and then
            # reports missing formats.
            "js_runtimes": {"node": {}},
            "remote_components": ["ejs:github"],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(cand["url"], download=True)
                path = Path(y.prepare_filename(info))
            if not path.is_file():
                # yt-dlp may pick a different container than the template implies.
                hits = sorted(MEDIA.glob(path.stem + ".*"), key=lambda p: -p.stat().st_size)
                if not hits:
                    return {"ok": False, "msg": "Downloaded but the file is missing."}
                path = hits[0]
            if path.suffix.lower() not in self.MEDIA_EXT:
                return {"ok": False, "msg": "Downloaded %s, which the stage cannot play." % path.suffix}
            return {"ok": True, "name": path.name, "size": path.stat().st_size}
        except Exception as e:
            return {"ok": False, "msg": "Download failed: %s" % str(e)[:200]}

    def _browser_exe(self):
        """Chrome dahulu, Edge sebagai sandaran. '' kalau tiada."""
        local = os.environ.get("LOCALAPPDATA", "")
        for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if p and os.path.isfile(p):
                return p
        return ""

    def _play_in_browser(self, url):
        """Buka url dalam Chrome sebenar dan masukkan tetingkapnya ke stage.

        Tetingkap dicari dengan membeza set tetingkap sebelum dan selepas,
        bukan dengan pid pelancaran. Sebabnya diukur: bila Chrome sudah
        berjalan, `chrome.exe --new-window` hanya menyuruh proses sedia ada
        membuka tab, dan proses yang kita lancarkan keluar serta-merta —
        `window_for_pid(proc.pid)` memulangkan 0 walaupun tab itu jelas ada
        atas skrin. Beza-set menangkap tab itu juga, sama ada Chrome baru
        dimulakan atau tidak.
        """
        exe = self._browser_exe()
        if not exe:
            return {"ok": False, "msg": "No Chrome or Edge on this PC."}
        hud = self.hud_hwnd()
        if not hud:
            return {"ok": False, "msg": "Jarvis window not found."}
        before = sysctl.visible_hwnds()
        try:
            proc = subprocess.Popen(
                [exe, "--new-window", "--start-maximized", url],
                creationflags=NO_WINDOW)
        except Exception as e:
            return {"ok": False, "msg": "Could not start the browser: %s" % e}
        hwnd = 0
        # Chrome ialah satu proses induk: anak-anaknya yang memiliki tetingkap,
        # jadi cari ikut pid dahulu, kemudian beza-set.
        for _ in range(80):  # Chrome cold start on a spinning disk can take 8 s
            time.sleep(0.2)
            hwnd = sysctl.window_for_pid(proc.pid) or sysctl.new_window_since(before)
            if hwnd:
                break
        if not hwnd:
            return {"ok": False, "msg": "The browser opened but no window appeared."}
        ok, msg = self._sys.embed.attach_hwnd(hud, hwnd, "YouTube")
        if not ok:
            return {"ok": False, "msg": msg}
        scale = sysctl.dpi_scale(hud)
        rect = getattr(self, "_app_rect", None)
        if not rect or float(rect[2] or 0) < 240:
            rect = (0.17 * 1920, 0.16 * 1080, 0.66 * 1920, 0.68 * 1080, scale)
        self._app_rect = rect
        self._app_place()
        self._emit("app", {"attached": "YouTube", "browser": True})
        self._push("window.stageShow && window.stageShow('native')")
        return {"ok": True}

    def _serper_raw(self, key, query, num=8):
        """Hasil Serper mentah, untuk pemanggil yang perlukan link bukan teks."""
        req = urllib.request.Request(
            "https://google.serper.dev/search", method="POST",
            data=json.dumps({"q": query, "gl": "my", "hl": "ms", "num": num}).encode("utf-8"),
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        out = []
        for x in (d.get("organic") or []):
            out.append({"title": x.get("title", ""), "link": x.get("link", ""),
                        "snippet": x.get("snippet", "")})
        return out

    def _serper(self, key, query):
        """Hasil carian Google melalui API rasmi Serper.dev (~1-2 saat)."""
        req = urllib.request.Request(
            "https://google.serper.dev/search", method="POST",
            data=json.dumps({"q": query, "gl": "my", "hl": "ms", "num": 8,
                             **({"location": loc} if (loc := load_json(CONFIG, {}).get("location")) else {})}).encode("utf-8"),
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        lines = []
        ab = d.get("answerBox") or {}
        if ab:
            lines.append("Jawapan Google: " + " ".join(str(ab.get(k, "")) for k in ("title", "answer", "snippet") if ab.get(k)))
        kg = d.get("knowledgeGraph") or {}
        if kg:
            attrs = "; ".join(f"{k}: {v}" for k, v in (kg.get("attributes") or {}).items())
            lines.append(f"Info: {kg.get('title', '')} — {kg.get('description', '')} {attrs}".strip())
        self._last_links = [{"title": x.get("title", ""), "url": x.get("link", "")} for x in (d.get("organic") or [])[:6]]
        for x in (d.get("organic") or [])[:7]:
            date = f" [{x['date']}]" if x.get("date") else ""
            lines.append(f"- {x.get('title')}{date} ({x.get('link')}): {x.get('snippet', '')}")
        for x in (d.get("topStories") or [])[:3]:
            lines.append(f"- Berita: {x.get('title')} ({x.get('source')}, {x.get('date', '')})")
        return "\n".join(lines) or "No results."

    def _web_search(self, query):
        """Carian web rasmi: Serper (Google) → Tavily → Claude Code WebSearch, ikut key yang ada."""
        s = load_json(SECRETS, {})
        if s.get("serper_api_key"):
            try:
                return self._serper(s["serper_api_key"], query)
            except Exception as e:
                if not (s.get("tavily_api_key") or self._claude):
                    return f"Google search failed: {e}"
        if s.get("tavily_api_key"):
            req = urllib.request.Request(
                "https://api.tavily.com/search", method="POST",
                data=json.dumps({"query": query, "max_results": 5, "include_answer": True}).encode("utf-8"),
                headers={"Authorization": "Bearer " + s["tavily_api_key"], "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            lines = [f"Ringkasan: {d['answer']}"] if d.get("answer") else []
            lines += [f"- {x.get('title')} ({x.get('url')}): {x.get('content', '')[:400]}" for x in d.get("results", [])]
            return "\n".join(lines) or "No results."
        if not self._claude:
            return "Web search unavailable: no Tavily key and Claude Code not found."
        result = self._claude_quick(
            f"Cari di web dan beri ringkasan fakta terkini yang padat (maksimum 8 baris) berserta "
            f"sumber dalam format [tajuk](url) dan tarikh jika ada, untuk: {query}", ["WebSearch", "WebFetch"])
        self._last_links = [{"title": t, "url": u} for t, u in re.findall(r"\[([^\]]{3,80})\]\((https?://[^)\s]+)\)", result)][:6]
        return result

    def _claude_quick(self, prompt, tools, model="haiku", timeout=120):
        """Panggilan Claude Code ringkas dengan tool terhad (carian web, Gmail, Drive, tengok skrin)."""
        if not self._claude:
            return "Claude Code not found."
        if any(t.startswith("mcp__") for t in tools):
            # Sambungan Gmail/Drive dibuat di latar; tanpa ToolSearch dulu, Claude selalu kata "server masih menyambung"
            service = "gmail" if any("Gmail" in t for t in tools) else "google drive"
            tools = ["ToolSearch"] + tools
            prompt = (f'Langkah 1: guna ToolSearch dengan query "{service}" untuk muatkan tool. Jika ia kata server '
                      f"masih menyambung, cuba ToolSearch sekali lagi.\nLangkah 2: {prompt}")
        p = subprocess.run(
            [self._claude, "-p", "--output-format", "json", "--model", model,
             "--allowedTools", ",".join(tools), "--max-turns", "14"],
            input=(prompt + ("\n\nReply in natural English only." if load_json(CONFIG, {}).get("reply_language") == "en" else "\n\nJawab dalam Bahasa Melayu MALAYSIA (bukan Bahasa Indonesia), guna \"saya\" dan panggil pengguna \"Akmal\".")).encode("utf-8"),
            capture_output=True, timeout=timeout, cwd=HOME, creationflags=NO_WINDOW,
        )
        try:
            return json.loads(p.stdout.decode("utf-8", "replace")).get("result") or "Tiada hasil."
        except json.JSONDecodeError:
            return "Failed: " + p.stderr.decode("utf-8", "replace")[-300:]

    # ---------- Info harian: cuaca, solat, laporan pagi ----------
    def _cfg_place(self):
        cfg = load_json(CONFIG, {})
        return (float(cfg.get("latitude", 4.5975)), float(cfg.get("longitude", 101.0901)),
                cfg.get("prayer_zone", "PRK02"))

    def today_info(self):
        """Widget 'Hari ini' di panel kanan: cuaca + solat seterusnya."""
        lat, lon, zone = self._cfg_place()
        cfg = load_json(CONFIG, {})
        out = {"place": str(cfg.get("location", "")).split(",")[0]}
        try:
            out["weather"] = sv.weather(lat, lon)
        except Exception:
            pass
        out["prayer"] = self.next_prayer()
        return out

    def next_prayer(self):
        _, _, zone = self._cfg_place()
        nxt = sv.next_prayer(sv.prayer_today(zone))
        if nxt:
            return {"name": nxt[0], "time": nxt[1], "mins": nxt[2]}
        # dah lepas Isyak: tunjuk Subuh esok
        import datetime as _dt
        tmr = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
        fajr = (sv.cache_get("prayer") or {}).get("days", {}).get(tmr, {}).get("fajr")
        if not fajr:
            return {}
        at = _dt.datetime.combine(_dt.date.today() + _dt.timedelta(days=1), _dt.datetime.strptime(fajr, "%H:%M").time())
        return {"name": "Subuh", "time": fajr, "mins": int((at - _dt.datetime.now()).total_seconds() // 60)}

    def _prayer_watch(self):
        """Ingatkan N minit sebelum masuk waktu solat (config: prayer_reminder_minutes, 0 = tutup)."""
        while True:
            time.sleep(20)
            try:
                lead = int(load_json(CONFIG, {}).get("prayer_reminder_minutes", 5))
                if lead <= 0:
                    continue
                _, _, zone = self._cfg_place()
                times = sv.prayer_today(zone)
                nxt = sv.next_prayer(times)
                today = time.strftime("%Y-%m-%d")
                if nxt and nxt[2] < lead and (today, nxt[0]) not in self._prayer_done:
                    self._prayer_done.add((today, nxt[0]))
                    self._window.evaluate_js(
                        f"window.onPrayer && window.onPrayer({json.dumps({'name': nxt[0], 'time': nxt[1], 'mins': nxt[2] + 1})})")
            except Exception:
                pass

    def morning_brief(self, force=False):
        """Laporan harian sekali sehari (atau bila diminta). Dihantar sebagai event 'brief'."""
        today = time.strftime("%Y-%m-%d")
        if not force and (not load_json(CONFIG, {}).get("morning_brief", True) or sv.cache_get("brief_date") == today):
            return {"ok": False}
        sv.cache_set("brief_date", today)
        threading.Thread(target=self._brief_worker, daemon=True).start()
        return {"ok": True}

    def _brief_worker(self):
        lat, lon, zone = self._cfg_place()
        facts, results = [], {}

        def grab(key, fn):
            try:
                results[key] = fn()
            except Exception as e:
                results[key] = f"(tak dapat: {e})"
        jobs = [("cuaca", lambda: sv.weather_text(sv.weather(lat, lon))),
                ("solat", lambda: sv.prayer_text(sv.prayer_today(zone), zone)),
                ("ipu", lambda: self._web_search(f"bacaan IPU {load_json(CONFIG, {}).get('location', 'Ipoh')} hari ini")[:900])]
        if self._claude and load_json(CONFIG, {}).get("brief_email", True):
            jobs.append(("email", lambda: self._claude_quick(
                "Guna Gmail (baca sahaja): berapa email belum dibaca dalam inbox sejak semalam? Sebut subjek "
                "maksimum 3 yang nampak penting (abaikan promosi/iklan). Jawab dalam 3 baris.", GMAIL_READ, timeout=60)))
        threads = [threading.Thread(target=grab, args=j, daemon=True) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=70)
        for key, _ in jobs:
            if key in results:
                facts.append(f"{key.upper()}: {results[key]}")
        s = load_json(SECRETS, {})
        prompt = ("Buat laporan harian untuk dibaca dengan SUARA bila Akmal baru buka laptop. 4-6 ayat pendek, "
                  "gaya KL santai, mula dengan sapaan ikut waktu sekarang. Sebut cuaca (dan kalau nak hujan), IPU, "
                  "waktu solat seterusnya, dan email penting jika ada. Jangan guna senarai atau simbol.\n\nDATA:\n" + "\n".join(facts))
        try:
            text = self._chat_call(s, [{"role": "system", "content": PERSONA + lang_note() + f"\nSekarang: {time.strftime('%A %d %B %Y, %H:%M')}."},
                                       {"role": "user", "content": prompt}])["content"]
        except Exception:
            text = " ".join(str(results.get(k, "")) for k in ("cuaca", "solat"))
        try:
            self._window.evaluate_js(f"window.onBrief && window.onBrief({json.dumps(text)})")
        except Exception:
            pass

    # ---------- Tool DeepSeek ----------
    def _resolve_place(self, name):
        """Nama atau path -> Path dalam folder pengguna, atau None."""
        if not name:
            return None
        p = Path(os.path.expandvars(os.path.expanduser(name.strip().strip('"'))))
        if p.is_absolute():
            return p if p.exists() else None
        n = lambda s: "".join(c for c in s.lower() if c.isalnum())
        q = n(name)
        known = known_folder(name.strip().title())
        if known:
            return known
        cands = []
        for base in filter(None, (known_folder("Desktop"), known_folder("Documents"), known_folder("Downloads"), HOME)):
            try:
                cands += list(base.iterdir())
            except OSError:
                pass
        for test in (lambda c: n(c.stem) == q or n(c.name) == q, lambda c: n(c.name).startswith(q), lambda c: q in n(c.name)):
            hit = next((c for c in cands if test(c)), None)
            if hit:
                return hit
        return None

    def _tool_open(self, name):
        # 1) shortcut Jarvis (app & folder), 2) item Desktop/folder, 3) Start Menu
        n = lambda s: "".join(c for c in s.lower() if c.isalnum())
        data = load_json(SHORTCUTS, {})
        for group in ("apps", "folders"):
            for item in data.get(group, []):
                if n(item.get("name", "")) == n(name) or n(name) in n(item.get("name", "")):
                    target = resolve(item)
                    if target:
                        os.startfile(str(target))
                        return f"Opened {item['name']}.", str(target) if isinstance(target, Path) else ""
        place = self._resolve_place(name)
        if place:
            os.startfile(str(place))
            return f"Opened {place.name} ({place}).", str(place)
        lnk = find_start_menu(name)
        if lnk:
            os.startfile(str(lnk))
            return f"Opened {lnk.stem}.", ""
        return f'Could not find "{name}" on this PC.', ""

    def _tool_list(self, folder):
        p = self._resolve_place(folder)
        if not p or not p.is_dir():
            return f'Folder "{folder}" was not found.', "", "", []
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        lines = [("[folder] " if e.is_dir() else "") + e.name for e in entries[:80]]
        more = f"\n…and {len(entries) - 80} more" if len(entries) > 80 else ""
        listing = "\n".join(str(e) for e in entries[:12])  # untuk cabang peta hologram
        return (f"Isi {p} ({len(entries)} item):\n" + "\n".join(lines) + more,
                str(p), listing, self._as_items(entries, 6))

    @staticmethod
    def _as_items(entries, limit=6):
        """Entri folder sebagai {text, dir} untuk senarai tugas orb.
        Orb hanya ada ~260px lebar; enam baris adalah senarai yang boleh
        dibaca sekali pandang, bukan skrol."""
        return [{"text": e.name, "dir": e.is_dir()} for e in entries[:limit]]

    def _tool_find(self, keyword):
        kw, hits, deadline = keyword.lower().strip(), [], time.time() + 6
        for base in filter(None, (known_folder("Desktop"), known_folder("Documents"), known_folder("Downloads"))):
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "vendor", ".git", "__pycache__")]
                for f in files:
                    if kw in f.lower():
                        hits.append(os.path.join(root, f))
                if len(hits) >= 30 or time.time() > deadline:
                    break
        if not hits:
            return f'No files named "{keyword}".', "", []
        return (f"Found {len(hits)} files:\n" + "\n".join(hits[:30]),
                "\n".join(hits[:12]),
                [{"text": os.path.basename(h), "dir": False} for h in hits[:6]])

    def _tool_read(self, path):
        p = self._resolve_place(path)
        if not p or not p.is_file():
            return f'File "{path}" was not found. Use find_files first.', ""
        ext, limit = p.suffix.lower(), 12000
        try:
            if ext == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(str(p))
                text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:30])
                head = f"PDF {len(reader.pages)} muka surat"
            elif ext in (".xlsx", ".xlsm"):
                import openpyxl
                wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
                parts = []
                for ws in wb.worksheets[:4]:
                    rows = []
                    for row in ws.iter_rows(max_row=300, values_only=True):
                        if any(v is not None for v in row):
                            rows.append(",".join("" if v is None else str(v) for v in row))
                    parts.append(f"## Sheet: {ws.title} ({len(rows)} baris)\n" + "\n".join(rows))
                text = "\n\n".join(parts)
                head = f"Excel {len(wb.worksheets)} sheet"
            elif ext == ".docx":
                import docx
                text = "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
                head = "Dokumen Word"
            elif ext in TEXT_EXT or p.stat().st_size < 200_000:
                text = p.read_text(encoding="utf-8", errors="replace")
                head = "Fail teks"
            else:
                return f"{ext} files cannot be read in this mode.", str(p)
        except Exception as e:
            return f"Could not read the file: {e}", str(p)
        text = text.strip() or "(no text — probably a scanned/image PDF)"
        cut = f"\n…(dipotong, jumlah {len(text)} aksara)" if len(text) > limit else ""
        return f"{head}: {p.name}\n\n{text[:limit]}{cut}", str(p)

    def _tool_reminder(self, minutes, message):
        secs = max(5, float(minutes) * 60)
        due = time.strftime("%H:%M", time.localtime(time.time() + secs))
        threading.Timer(secs, self._fire_reminder, args=(message,)).start()
        return f"Reminder set for {due}: {message}"

    def _fire_reminder(self, message):
        try:
            self._window.restore()
        except Exception:
            pass
        try:
            self._window.evaluate_js(f"window.onReminder && window.onReminder({json.dumps(message)})")
        except Exception:
            pass

    def _chat_tool(self, name, args):
        """Jalankan satu tool DeepSeek, papar di HUD, pulangkan teks hasil untuk model."""
        label = {"web_search": "WebSearch", "open_item": "Open", "system_status": "Status", "list_folder": "List",
                 "find_files": "Find", "read_file": "Read", "set_reminder": "Reminder", "weather": "Weather",
                 "prayer_times": "Prayer", "check_email": "Gmail", "search_drive": "Drive",
                 "look_at_screen": "Screen", "control_pc": "Control", "open_media": "Media",
                 "play_youtube": "YouTube",
                 "system": "System", "repo_stats": "Repos"}.get(name, name)
        lat, lon, zone = self._cfg_place()
        if name == "open_media":
            want = str(args.get("name", "") or "").strip()
            self._emit("tool", {"name": label, "detail": want or "listing media/", "full": ""})
            res = self.open_media(want)
            if not res.get("ok"):
                return res.get("msg", "No media found.") + " List: " + ", ".join(
                    i["name"] for i in res.get("items", [])[:20])
            # media_list() returns {"ok": True, "items": [...]} with no "name".
            # Indexing res["name"] on that path raised KeyError: 'name', so a
            # bare `open_media {}` crashed the tool loop instead of answering.
            if not want:
                items = res.get("items") or []
                if not items:
                    return "media/ is empty. For YouTube, use play_youtube."
                return ("media/ holds %d file(s): %s. Call again with a name to play one. "
                        "For YouTube, use play_youtube instead."
                        % (len(items), ", ".join(i["name"] for i in items[:20])))
            return f"Playing {res.get('name', want)} in the MEDIA panel."
        if name == "play_youtube":
            q = str(args.get("query", "") or "").strip()
            mode = str(args.get("mode", "") or "").strip().lower()
            self._emit("tool", {"name": "YouTube", "detail": q, "full": mode})
            res = self.play_youtube(q, mode=mode or "local")
            if not res.get("ok"):
                return res.get("msg") or "YouTube search failed."
            if res.get("mode") == "local":
                mb = (res.get("size") or 0) / (1024 * 1024)
                return ("Playing %r in the MEDIA panel now as a local file (%.1f MB). "
                        "It has already started and the sound comes out of the speakers — "
                        "do not call this again." % (res.get("title"), mb))
            if res.get("mode") == "browser":
                return ("Opened %r in a real browser window inside the stage. Note that this "
                        "route often shows a blank window, because Chromium does not repaint "
                        "after being re-parented." % res.get("title"))
            return ("Embedding %r in the WEB panel (id %s). If it says 'Video unavailable', "
                    "that is YouTube error 150 — call again without a mode to play it as a "
                    "downloaded file instead." % (res.get("title"), res.get("id")))
        if name == "weather":
            self._emit("tool", {"name": label, "detail": load_json(CONFIG, {}).get("location", ""), "full": ""})
            return sv.weather_text(sv.weather(lat, lon))
        if name == "prayer_times":
            self._emit("tool", {"name": label, "detail": f"JAKIM {zone}", "full": ""})
            return sv.prayer_text(sv.prayer_today(zone), zone)
        if name in ("check_email", "search_drive"):
            req = args.get("request", "")
            self._emit("tool", {"name": label, "detail": req, "full": ""})
            if name == "check_email":
                return self._claude_quick(f"Guna Gmail, BACA SAHAJA (jangan hantar/padam apa-apa). {req}. "
                                          "Jawab ringkas: pengirim, subjek, tarikh, dan isi penting.", GMAIL_READ)
            return self._claude_quick(f"Guna Google Drive, BACA SAHAJA. {req}. Jawab ringkas dengan nama fail, "
                                      "tarikh ubah dan link.", DRIVE_READ)
        if name == "look_at_screen":
            q = args.get("question", "Apa yang ada atas skrin?")
            self._emit("tool", {"name": label, "detail": q, "full": ""})
            shot = Path(os.environ.get("TEMP", str(HOME))) / f"jarvis-screen-{int(time.time())}.png"
            try:
                sv.screenshot(str(shot))
                return self._claude_quick(f"Baca imej {shot} (screenshot skrin laptop Akmal). Soalan: {q}\n"
                                          "Jawab dalam BM santai, ringkas dan tepat.", ["Read"], model="sonnet")
            finally:
                shot.unlink(missing_ok=True)
        if name == "repo_stats":
            self._emit("tool", {"name": "Repos", "detail": "measuring every repo", "full": ""})
            data = self.repo_scan(args.get("limit") or 12)
            if not data.get("ok"):
                return data.get("msg") or "Could not read any repositories."
            dash = self._repo_dashboard(data)
            if not dash:
                return "No git repositories were found in Home, Desktop, Documents or Downloads."
            self._chat_tool("present_analysis", dash)
            lines = [f'{r["name"]}: {r["commits"]} commits, branch {r["branch"]}, '
                     f'{r["dirty"]} uncommitted, last {r["last"][:10]}, '
                     f'+{r["ins"]}/-{r["dels"]} lines in 6 months' for r in data["repos"]]
            return ("Dashboard shown. Exact figures:" + chr(10).join(lines) +
                    chr(10) + "Reply with ONE short closing sentence. Do not repeat the numbers.")
        if name == "analyse_path":
            res = self.analyse_path(args.get("path"))
            if not res.get("ok"):
                return "Could not analyse it: " + (res.get("msg") or "unknown reason")
            return ("Report drawn and narrated to Akmal, titled %r. Exact measured facts:\n%s\n"
                    "Reply with ONE short closing sentence. Do not invent or restate numbers."
                    % (res.get("title", ""), res.get("spoken", "")))
        if name == "present_analysis":
            self._analysis_shown = True
            self._emit("tool", {"name": "Analysis", "detail": args.get("title", ""), "full": ""})
            self._emit("analysis", args)
            return ("Analisis sedang dipaparkan dan dibacakan satu-satu kepada Akmal. Balas dengan SATU ayat penutup "
                    "yang sangat pendek sahaja (jangan ulang angka).")
        if name == "control_pc":
            act = args.get("action", "")
            done = sv.do_control(act)
            self._emit("tool", {"name": label, "detail": done or act, "full": ""})
            return f"Done: {done}." if done else f"Action {act} not recognised."
        if name == "system":
            act = str(args.get("action", "") or "")
            rest = {k: v for k, v in args.items() if k != "action" and v is not None}
            self._emit("tool", {"name": label, "detail": act + (" " + str(next(iter(rest.values()))) if rest else ""),
                                "full": json.dumps(rest, ensure_ascii=False)[:300]})
            if act == "show_doc":
                # System tidak tahu tentang HUD, jadi show_doc diselesaikan di sini
                r = self._open_doc_in_stage(rest.get("path", ""))
                return r.get("label", "Tried to open it.")
            res = self._sys.do(act, **rest)
            if res.get("need_confirm"):
                # Token disimpan supaya "ya" dari Akmal menyambung kerja yang sama
                self._pending_token = res["token"]
                self._pending_cmd = act
                self._push(f"window.jarvisConfirm && window.jarvisConfirm({json.dumps(res)})")
                return (f"Perlu pengesahan Akmal: {res['ask']} JANGAN panggil tool ini lagi. "
                        f"Tanya Akmal dalam satu ayat pendek dan berhenti.")
            return res.get("msg") or ("Done." if res.get("ok") else "Failed.")
        detail = str(next(iter(args.values()), "")) if args else ""
        if name == "set_reminder":
            detail = f"{args.get('minutes')} min · {args.get('message', '')}"
        if name == "system_status":
            self._emit("tool", {"name": label, "detail": "CPU, RAM, disk, battery", "full": ""})
            st = self.get_stats()
            up = int(time.time() - st["boot"])
            bat = "n/a" if st["battery"] is None else f"{st['battery']}%" + (" (charging)" if st["plugged"] else "")
            return (f"CPU {st['cpu']}%, RAM {st['ram']}% ({st['ram_used']}/{st['ram_total']} GB), disk C {st['disk']}%, "
                    f"battery {bat}, down {st['down']} KB/s, uptime {up // 3600} h {up % 3600 // 60} min.")
        if name == "web_search":
            q = args.get("query", "")
            self._emit("tool", {"name": label, "detail": q, "full": q})
            if not q:
                return "Empty query."
            self._last_links = []
            result = self._web_search(q)
            if self._last_links:  # cabang hasil carian (tajuk + ikon laman) dalam peta hologram
                self._emit("web", {"query": q, "links": self._last_links})
            return result
        if name == "set_reminder":
            self._emit("tool", {"name": label, "detail": detail, "full": ""})
            return self._tool_reminder(args.get("minutes", 1), args.get("message", "Reminder"))
        if name == "open_item":
            msg, path = self._tool_open(args.get("name", ""))
            self._emit("tool", {"name": label, "detail": detail, "full": path or ""})
            return msg
        if name == "list_folder":
            msg, path, listing, items = self._tool_list(args.get("folder", ""))
            self._emit("tool", {"name": label, "detail": detail, "full": f'"{path}"' if path else "",
                                "items": items})
            if listing:
                self._emit("result", {"name": label, "text": listing})
            return msg
        if name == "find_files":
            msg, listing, items = self._tool_find(args.get("keyword", ""))
            self._emit("tool", {"name": label, "detail": detail, "full": "", "items": items})
            if listing:
                self._emit("graph", {"full": " ".join(f'"{h}"' for h in listing.splitlines()[:6])})
            return msg
        if name == "read_file":
            msg, path = self._tool_read(args.get("path", ""))
            self._emit("tool", {"name": label, "detail": Path(path).name if path else detail, "full": f'"{path}"' if path else ""})
            return msg
        return f"Tool {name} does not exist."

    # ---------- Repo statistics ----------
    # Walked, not asked. The model can describe a repo; only git can count one.
    # Everything below is exact: commit counts, lines changed, branches, dates.
    # A repo whose git call fails is kept with zeros and flagged, never dropped —
    # a partial row beats a missing one when the answer is "all my repos".
    REPO_SKIP = {"node_modules", ".venv", "venv", "env", "site-packages", "__pycache__",
                 "AppData", "Windows", "Program Files", "Program Files (x86)", "ProgramData",
                 "$Recycle.Bin", ".cache", "dist", "build", "target", ".next", ".nuxt",
                 "Library", "OneDrive", "Dropbox", "anaconda3", "miniconda3"}
    REPO_DEPTH = 4

    def _git(self, repo, *args, timeout=12):
        import subprocess
        try:
            r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.stdout if r.returncode == 0 else ""
        except Exception:
            return ""

    def _repos_found(self):
        """Every directory holding a .git, four levels deep under the usual roots."""
        roots, out, seen = [], [], set()
        for name in ("", "Desktop", "Documents", "Downloads", "Projects", "source", "dev"):
            d = (HOME / name) if name else HOME
            try:
                if d.is_dir():
                    roots.append(d.resolve())
            except OSError:
                pass
        for root in roots:
            for cur, dirs, _files in os.walk(root):
                cur_p = Path(cur)
                try:
                    depth = len(cur_p.relative_to(root).parts)
                except ValueError:
                    depth = 0
                if depth >= self.REPO_DEPTH:
                    dirs[:] = []
                dirs[:] = [d for d in dirs
                           if (not d.startswith(".") or d == ".git") and d not in self.REPO_SKIP]
                if (cur_p / ".git").exists():
                    rp = cur_p.resolve()
                    if rp not in seen:
                        seen.add(rp)
                        out.append(rp)
                    dirs[:] = []   # a repo does not contain a second repo worth walking
        return out

    def _repo_shape(self, repo):
        """One repo, measured. Missing pieces come back as zero, never as a guess."""
        head = self._git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() or "-"
        raw = self._git(repo, "rev-list", "--count", "HEAD").strip()
        commits = int(raw) if raw.isdigit() else 0
        dirty = len([l for l in self._git(repo, "status", "--porcelain").splitlines() if l.strip()])
        last = self._git(repo, "log", "-1", "--format=%cI").strip()
        first = self._git(repo, "log", "--reverse", "--format=%cI", "-1").strip()
        # 26 weeks of dates, one line per commit — cheapest route to an active-day count
        hist = self._git(repo, "log", "--since=26 weeks ago", "--date=short", "--format=%ad")
        days = [d for d in hist.splitlines() if d.strip()]
        stat = self._git(repo, "log", "--since=26 weeks ago", "--shortstat", "--format=")
        ins = dels = files = 0
        for m in re.finditer(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?", stat):
            files += int(m.group(1))
            ins += int(m.group(2) or 0)
            dels += int(m.group(3) or 0)
        authors = {}
        for line in self._git(repo, "shortlog", "-sne", "HEAD").splitlines():
            m = re.match(r"\s*(\d+)\s+(.+?)\s*<", line)
            if m:
                nm = m.group(2).strip()
                authors[nm] = authors.get(nm, 0) + int(m.group(1))
        # language mix by tracked-file extension, not by bytes on disk — a
        # vendored bundle would otherwise call every project a JavaScript one
        ext_count = {}
        for f in self._git(repo, "ls-files").splitlines():
            e = Path(f).suffix.lower().lstrip(".")
            if e:
                ext_count[e] = ext_count.get(e, 0) + 1
        # 26 weekly buckets, oldest first. This is what lets the report draw a
        # curve of when the work actually happened, not just a lifetime total.
        weeks = [0] * 26
        today = datetime.now().date()
        for d in days:
            try:
                dd = datetime.strptime(d.strip(), "%Y-%m-%d").date()
            except ValueError:
                continue
            k = (today - dd).days // 7
            if 0 <= k < 26:
                weeks[25 - k] += 1
        return {
            "name": repo.name, "path": str(repo), "branch": head, "commits": commits,
            "weeks": weeks,
            "dirty": dirty, "last": last, "first": first,
            "active_days": len(set(days)), "window_commits": len(days),
            "ins": ins, "dels": dels, "files": files,
            "authors": sorted(authors.items(), key=lambda kv: -kv[1])[:5],
            "ext": sorted(ext_count.items(), key=lambda kv: -kv[1])[:5],
        }

    def repo_scan(self, limit=12):
        """Measure every repo on the machine and return the raw rows."""
        if not self._git(HOME, "--version"):
            return {"ok": False, "msg": "git is not installed, or not on PATH.", "repos": []}
        rows = []
        for rp in self._repos_found():
            try:
                rows.append(self._repo_shape(rp))
            except Exception as e:
                rows.append({"name": rp.name, "path": str(rp), "branch": "-", "commits": 0,
                             "dirty": 0, "last": "", "first": "", "active_days": 0,
                             "window_commits": 0, "ins": 0, "dels": 0, "files": 0,
                             "authors": [], "ext": [], "error": str(e)})
        rows.sort(key=lambda r: (-r["commits"], r["name"].lower()))
        try:
            limit = max(1, min(int(limit or 12), 40))
        except (TypeError, ValueError):
            limit = 12
        return {"ok": True, "total": len(rows), "repos": rows[:limit], "all": rows}

    def _repo_dashboard(self, data):
        """Raw rows -> the shape present_analysis takes, so render() draws it as-is."""
        rows = data.get("repos") or []
        if not rows:
            return None
        n = len(rows)
        commits = sum(r["commits"] for r in rows)
        dirty = sum(1 for r in rows if r["dirty"])
        ins = sum(r["ins"] for r in rows)
        dels = sum(r["dels"] for r in rows)
        windows = sum(r["window_commits"] for r in rows)
        newest = max((r["last"] for r in rows if r["last"]), default="")
        ago = ""
        if newest:
            try:
                when = datetime.fromisoformat(newest.replace("Z", "+00:00"))
                delta = datetime.now(when.tzinfo) - when
                if delta.days < 0:
                    raise ValueError("clock skew")
                ago = ("today" if delta.days == 0 else
                       "1 day ago" if delta.days == 1 else f"{delta.days} days ago")
            except Exception:
                ago = ""

        def short(x):
            return f"{x / 1000:.1f}k" if x >= 1000 else str(x)

        cards = [
            {"label": "Repos", "value": str(n), "note": f"{dirty} with uncommitted work" if dirty else "all clean"},
            {"label": "Commits", "value": short(commits), "note": f"{windows} in the last 6 months"},
            {"label": "Lines changed", "value": short(ins + dels), "note": f"+{short(ins)} / −{short(dels)}"},
            {"label": "Last commit", "value": ago or "—", "note": newest[:10] if newest else "no history"},
        ]
        trend = [sum(r.get("weeks", [0] * 26)[k] for r in rows) for k in range(26)]
        charts = [
            {"title": "Commits per week · 26 weeks", "kind": "line", "items": [
                {"label": f"w{k + 1}", "value": v, "display": str(v)} for k, v in enumerate(trend)]},
            {"title": "Commits per repo", "kind": "bar", "items": [
                {"label": r["name"], "value": r["commits"], "display": str(r["commits"])} for r in rows[:8]]},
            {"title": "Lines changed · 6 months", "kind": "bar", "items": [
                {"label": r["name"], "value": r["ins"] + r["dels"],
                 "display": f"+{short(r['ins'])} / −{short(r['dels'])}"} for r in rows[:8]]},
        ]
        ext_tot = {}
        for r in rows:
            for e, c in r["ext"]:
                ext_tot[e] = ext_tot.get(e, 0) + c
        top_ext = sorted(ext_tot.items(), key=lambda kv: -kv[1])[:6]
        if top_ext:
            charts.append({"title": "What it is written in", "kind": "donut", "items": [
                {"label": e, "value": c, "display": str(c)} for e, c in top_ext]})

        busiest = max(rows, key=lambda r: r["commits"])
        pts = [
            {"text": f"I found {n} repositories, {commits} commits in total, and {dirty} with work not yet committed.",
             "target": "card:0"},
            {"text": f"The busiest is {busiest['name']} on branch {busiest['branch']}, with {busiest['commits']} commits.",
             "target": "chart:1:0"},
            {"text": f"Across all of them {short(ins)} lines went in and {short(dels)} came out over six months.",
             "target": "card:2"},
        ]
        if top_ext:
            pts.append({"text": f"Most of it is {top_ext[0][0]} — {top_ext[0][1]} files.", "target": "chart:3:0"})
        if ago:
            pts.append({"text": f"The most recent commit was {ago}.", "target": "card:3"})
        return {
            "title": "Repository report",
            "summary": f"{n} repos · {commits} commits · {short(ins + dels)} lines changed over six months.",
            "cards": cards, "charts": charts, "points": pts[:5],
            "followups": ["Which repo needs attention?", "What did I work on this week?",
                          "Which one has the most uncommitted work?"],
        }

    def _make_analysis(self, s, question, answer, collected):
        """Tukar jawapan analisis jadi dashboard (JSON) dalam panggilan berasingan tanpa tool. Berfungsi untuk semua model."""
        prompt = (f"Soalan Akmal: {question}\n\nJawapan analisis:\n{answer}\n\nData mentah (rujukan):\n" + "\n\n".join(collected)[-8000:] +
                  "\n\nTukar analisis ini kepada SATU objek JSON sahaja (tiada teks lain) dengan format:\n"
                  '{"title": "...", "summary": "1 ayat", "cards": [{"label": "...", "value": "...", "note": "..."}], '
                  '"charts": [{"title": "...", "kind": "bar|line|donut", "items": '
                  '[{"label": "...", "value": 123, "display": "123"}]}], '
                  '"points": [{"text": "1-2 ayat untuk dibaca dengan suara, guna saya dan panggil Akmal", "target": "card:0"}], '
                  '"followups": ["soalan susulan pendek"]}\n'
                  "2-4 kad, 0-3 graf (value mesti nombor; kind: bar untuk perbandingan, line untuk trend "
                  "mengikut masa, donut untuk pecahan), 3-6 poin. target: card:N, chart:N atau chart:N:M (bar ke-M). "
                  "Bahasa Melayu Malaysia santai.")
        try:
            out = self._chat_call(s, [{"role": "system", "content": "Kamu menukar analisis kepada JSON dashboard. Balas JSON sahaja."},
                                      {"role": "user", "content": prompt}])["content"] or ""
            blob = re.search(r"\{[\s\S]*\}", strip_tool_markup(out))
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", blob.group(0))) if blob else None
            if data and data.get("points"):
                self._chat_tool("present_analysis", data)
        except Exception:
            pass

    def _run_chat(self, text):
        s = load_json(SECRETS, {})
        t0 = time.time()
        self._emit("start", {})
        self._emit("init", {"model": self._chat_model(s)})
        self._analysis_shown = False
        self._chat_history.append({"role": "user", "content": text})
        today = time.strftime("%A, %d %B %Y, %H:%M")
        messages = [{"role": "system", "content": CHAT_PROMPT + f"\n\nSekarang: {today} (waktu Malaysia)." + location_note() + lang_note()}] + self._chat_history[-20:]
        try:
            reply, steps, collected = "", 5, []
            tools = tools_for(text, self._chat_history)
            wants_analysis = bool(re.search(ANALYSIS_RX, text.lower()))
            for _ in range(steps):  # model boleh guna beberapa tool berturut sebelum menjawab
                m = self._chat_call(s, messages, tools)
                calls = m.get("tool_calls") or []
                if not calls:
                    reply = m.get("content") or ""
                    break
                messages.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
                for c in calls:
                    fn = c.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = self._chat_tool(fn.get("name", ""), args)
                    except Exception as e:
                        result = f"Tool gagal: {e}"
                    collected.append(f"[{fn.get('name')} {json.dumps(args, ensure_ascii=False)[:120]}]\n{result[:3000]}")
                    messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": result[:14000]})
            reply = strip_tool_markup(reply)
            if not reply:
                # Model tak berhenti menyiasat: jawab dalam perbualan bersih berdasarkan data yang dah dikumpul
                reply = strip_tool_markup(self._chat_call(s, [
                    {"role": "system", "content": PERSONA + location_note() + lang_note()},
                    {"role": "user", "content": f"Soalan Akmal: {text}\n\nData yang dah dikumpul:\n" +
                                                "\n\n".join(collected)[-24000:] + "\n\nJawab sekarang berdasarkan data ini, ringkas."}])["content"] or "")
            reply = reply or "Okay Akmal, dah siap."
            self._chat_history.append({"role": "assistant", "content": reply})
            self._emit("text", {"text": reply})
            # The question can ask for a dashboard, or the answer can simply be
            # full of figures — both routes end in the same pane. `_analysis_shown`
            # guards a reply that already called present_analysis or repo_stats:
            # dashboard on screen, nothing to add.
            if not self._analysis_shown and (wants_analysis or carries_data(reply)):
                self._emit("note", {"text": "Building analysis dashboard…"})
                self._make_analysis(s, text, reply, collected)
            self._emit("done", {"ok": True, "secs": round(time.time() - t0, 1), "error": None})
        except Exception as e:
            self._chat_history.pop()
            self._emit("done", {"ok": False, "secs": round(time.time() - t0, 1), "error": f"API error: {e}"})
        finally:
            self._chat_busy = False

    def _emit(self, kind, data):
        try:
            self._window.evaluate_js(f"window.onClaude && window.onClaude({json.dumps(kind)}, {json.dumps(data)})")
        except Exception:
            pass

    def _push(self, js: str):
        """Satu tempat untuk semua evaluate_js. Gagal bridge = senyap, bukan crash."""
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js(js)
        except Exception:
            pass

    def _deck_step(self, action):
        """Slide keystroke went out — move the doc pane with it.

        PowerPoint answers the keystroke itself, in its own window, and Jarvis
        never sees that. So the step is counted here, optimistically, and the
        pane re-renders at the new slide. Anything that would desync — pressing
        Home, clicking the thumbnail strip, jumping to slide 12 by hand — is
        corrected the moment Akmal says a slide number ("slide 12", "pergi
        slide lapan"), because that path re-opens the deck at an explicit page
        instead of stepping from a guess.
        """
        d = self._deck
        if not d.get("path") or not d.get("total"):
            return
        if action == "next_slide":
            d["slide"] = min(d["slide"] + 1, d["total"])
        elif action == "prev_slide":
            d["slide"] = max(d["slide"] - 1, 1)
        elif action in ("start_show", "end_show"):
            d["slide"] = 1
        else:
            return
        self._push("window.stageDocs && window.stageDocs.slide(%d)" % d["slide"])

    def _deck_label(self, action, base):
        """Say which slide it landed on, not just "next" — the number is the point."""
        d = self._deck
        if not d.get("path") or not d.get("total"):
            return base
        if action in ("next_slide", "prev_slide"):
            return "%s · slide %d/%d" % (base, d["slide"], d["total"])
        return base

    def stage_pane(self, name):
        """Tukar panel stage dari Python (contoh: dari arahan suara)."""
        name = re.sub(r"[^a-z]", "", str(name or "").lower())
        if name not in ("comms", "media", "term", "files", "editor", "browse", "docs", "ana", "native"):
            return {"ok": False, "msg": "Unknown panel."}
        self._push(f"window.stageShow && window.stageShow({json.dumps(name)})")
        if name == "docs" and self._deck.get("path"):
            # Bring the deck back when the docs pane is opened during a talk.
            # The page paints whatever was last loaded; if that was a different
            # deck it must be re-read at the slide the projector is on.
            self._push("window.stageDocs && window.stageDocs.open(%s, %d)"
                       % (json.dumps(self._deck["path"]), self._deck.get("slide") or 1))
        return {"ok": True, "pane": name}

    def _run_claude(self, text):
        cfg = load_json(CONFIG, {})
        cmd = [self._claude, "-p", "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", SYSTEM_PROMPT + location_note() + lang_note()]
        if cfg.get("model"):
            cmd += ["--model", cfg["model"]]
        if cfg.get("allowed_tools"):
            cmd += ["--allowedTools", ",".join(cfg["allowed_tools"])]
        if cfg.get("disallowed_tools"):
            cmd += ["--disallowedTools", ",".join(cfg["disallowed_tools"])]
        if self._session:
            cmd += ["--resume", self._session]
        elif self._continue_next:
            cmd += ["--continue"]
            self._continue_next = False
        workdir = self._project or Path(os.path.expanduser(cfg.get("workdir", "~")))
        if self._project:
            text = f"[Projek aktif: {self._project}]\n{text}"

        t0 = time.time()
        self._emit("start", {})
        got_result = False
        tool_names = {}  # tool_use_id -> nama tool
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=NO_WINDOW,
            )
            self._proc.stdin.write(text.encode("utf-8"))
            self._proc.stdin.close()
            for raw in self._proc.stdout:
                try:
                    ev = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type")
                if kind == "system" and ev.get("subtype") == "init":
                    self._session = ev.get("session_id") or self._session
                    self._emit("init", {"model": ev.get("model", "")})
                elif kind == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if block.get("type") == "text" and block.get("text", "").strip():
                            self._emit("text", {"text": block["text"]})
                        elif block.get("type") == "tool_use":
                            inp = block.get("input") or {}
                            tool_names[block.get("id")] = block.get("name", "?")
                            self._emit("tool", {"name": block.get("name", "?"),
                                                "detail": tool_detail(block.get("name"), inp),
                                                "full": tool_full(inp)})
                elif kind == "user":
                    # hasil tool: senarai fail/folder dipakai untuk lukis cabang peta hologram
                    for block in ev.get("message", {}).get("content", []) or []:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        name = tool_names.get(block.get("tool_use_id"), "")
                        content = block.get("content")
                        if isinstance(content, list):
                            content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                        if name == "WebSearch" and isinstance(content, str):
                            m = re.search(r'Web search results for query: "([^"]*)".*?Links: (\[.*?\])\s*(?:\n|$)', content, re.S)
                            if m:
                                try:
                                    links = [{"title": x.get("title", ""), "url": x.get("url", "")} for x in json.loads(m.group(2))][:6]
                                    self._emit("web", {"query": m.group(1), "links": links})
                                except json.JSONDecodeError:
                                    pass
                            continue
                        if name not in ("PowerShell", "Bash", "Glob", "Grep"):
                            continue
                        if isinstance(content, str) and content.strip():
                            self._emit("result", {"name": name, "text": content[:3000]})
                elif kind == "result":
                    got_result = True
                    self._session = ev.get("session_id") or self._session
                    self._save_session()
                    self._emit("done", {"ok": not ev.get("is_error"), "secs": round(time.time() - t0, 1),
                                        "error": ev.get("result") if ev.get("is_error") else None})
            err = self._proc.stderr.read().decode("utf-8", "replace").strip()
            code = self._proc.wait()
            if not got_result:
                msg = "Stopped." if code in (1, -9, 15) and not err else (err.splitlines()[-1] if err else f"Claude exited with code {code}.")
                self._emit("done", {"ok": False, "secs": round(time.time() - t0, 1), "error": msg})
        except Exception as e:
            self._emit("done", {"ok": False, "secs": round(time.time() - t0, 1), "error": str(e)})
        finally:
            self._proc = None

    # ---------- Suara ----------
    def tts(self, text, voice=None, rate=None, pitch=None, force=False):
        """Tukar teks jadi suara neural. Lalai Google Cloud BM; fallback edge-tts bila kunci tiada/gagal.

        Penapis `speak_replies` hidup DI SINI, bukan di pemanggil. Sebelum ini ia
        hanya diperiksa oleh satu laluan di UI, jadi setiap laluan lain — narasi
        analisis, brief pagi, peringatan solat — terus bersuara walaupun suis itu
        dimatikan, dan sintesis Google mengambil beberapa saat setiap baris
        sehingga suara kedengaran lama selepas jawapan sudah dipaparkan. Menapis
        di pintu masuk bermakna tiada audio yang dijana langsung, jadi tiada
        baris lama yang boleh berbunyi kemudian.
        """
        if not force and not load_json(CONFIG, {}).get("speak_replies", True):
            return {"ok": False, "muted": True, "note": "speak_replies is off"}
        import asyncio
        import base64
        import edge_tts
        cfg = load_json(CONFIG, {})
        if rate:
            cfg["voice_rate"] = rate
        if pitch:
            cfg["voice_pitch"] = pitch
        english = cfg.get("reply_language", "ms") == "en"
        voice = voice or (cfg.get("voice_en", "en-GB-RyanNeural") if english else cfg.get("voice", "ms-MY-Wavenet-D"))
        text = sv.speech_normalize(text, "en" if english else "ms")

        # ---------------- Google Cloud TTS (utama) ----------------
        if voice.startswith(("ms-MY-", "en-GB-Wavenet", "en-GB-Neural2", "en-GB-Studio",
                             "en-US-Wavenet", "en-US-Neural2")):
            res = self._google_tts(text, voice, cfg)
            if res.get("ok") or res.get("hard"):
                return res          # hard = ralat konfigurasi; jangan jatuh ke edge tanpa sebab
            # kunci tiada atau Google gagal -> fallback edge-tts (dicatat ringkas)
            cfg["_tts_fallback"] = res.get("msg", "")

        # ---------------- edge-tts (fallback) ----------------
        async def synth():
            buf = bytearray()
            comm = edge_tts.Communicate(text, voice if not voice.startswith("ms-MY-") else "ms-MY-OsmanNeural",
                                        rate=cfg.get("voice_rate", "+8%"), pitch=cfg.get("voice_pitch", "+0Hz"))
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            return bytes(buf)
        try:
            audio = asyncio.run(synth())
            out = {"ok": True, "src": "data:audio/mpeg;base64," + base64.b64encode(audio).decode(),
                   "via": "edge"}
            if cfg.get("_tts_fallback"):
                out["note"] = "Google failed, using edge-tts: " + cfg["_tts_fallback"][:120]
            return out
        except Exception as e:
            return {"ok": False, "msg": str(e), "via": "edge"}

    def _google_tts(self, text, voice, cfg):
        """Google Cloud Text-to-Speech (API rasmi).
        Pulangkan {"hard": True} untuk ralat konfigurasi (kunci tiada) supaya pemanggil
        tidak berulang kali cuba laluan yang memang tak akan jadi."""
        key = load_json(SECRETS, {}).get("google_tts_api_key")
        if not key:
            return {"ok": False, "hard": True, "msg": "google_tts_api_key is missing from secrets.json"}

        lang = "en-GB" if voice.startswith("en-") else "ms-MY"
        rate = 1 + int(str(cfg.get("voice_rate", "+0%")).rstrip("%")) / 100
        pitch = int(str(cfg.get("voice_pitch", "+0Hz")).rstrip("Hz")) / 2.5

        # *to_ssml hanya untuk ms-MY: ia bungkus perkataan English dalam <lang>. Untuk suara
        #  en-* itu memaksa en-US atas en-GB — sebutan jadi salah.*
        if cfg.get("voice_english_words", True) and lang == "ms-MY":
            inp = {"ssml": sv.to_ssml(text)}
        else:
            inp = {"text": text}

        body = {"input": inp, "voice": {"languageCode": lang, "name": voice},
                "audioConfig": {"audioEncoding": "MP3",
                                "speakingRate": max(0.25, min(round(rate, 2), 4.0)),
                                "pitch": max(-20.0, min(round(pitch, 1), 20.0))}}
        req = urllib.request.Request(
            "https://texttospeech.googleapis.com/v1/text:synthesize", method="POST",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                audio = json.load(r)["audioContent"]
            return {"ok": True, "src": "data:audio/mpeg;base64," + audio, "via": "google"}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            # 403/401 = kunci salah atau API belum diaktifkan -> konfigurasi, bukan gangguan sementara
            hard = e.code in (400, 401, 403)
            return {"ok": False, "hard": hard, "msg": f"Google TTS {e.code}: {detail}"}
        except Exception as e:
            return {"ok": False, "msg": f"Google TTS: {e}"}

    # ---------- Settings (panel dalam HUD) ----------
    def get_settings(self):
        cfg = load_json(CONFIG, {})
        return {"model": cfg.get("model", "sonnet"), "voice": cfg.get("voice", "ms-MY-OsmanNeural"),
                "voice_rate": cfg.get("voice_rate", "+8%"), "voice_pitch": cfg.get("voice_pitch", "+0Hz"),
                "voice_fx": cfg.get("voice_fx", False), "speak_replies": cfg.get("speak_replies", True), "reply_language": cfg.get("reply_language", "ms"),
                "voice_en": cfg.get("voice_en", "en-GB-RyanNeural"), "en_voices": EN_VOICES,
                "voices": all_voices(), "models": CLAUDE_MODELS,
                "chat_model": self._chat_model(load_json(SECRETS, {})), "chat_models": CHAT_MODELS,
                # rail menulis "google · <id>"; provider dihantar supaya JS tidak
                # meneka dan tidak perlu tahu nama penyedia suara
                "voice_provider": "google"}

    def set_setting(self, key, value):
        allowed = {"model": lambda v: v in [m["id"] for m in CLAUDE_MODELS],
                   "voice": lambda v: v in [x["id"] for x in all_voices()],
                   "voice_rate": lambda v: bool(re.fullmatch(r"[+-]\d{1,2}%", v)),
                   "voice_pitch": lambda v: bool(re.fullmatch(r"[+-]\d{1,2}Hz", v)),
                   "voice_fx": lambda v: isinstance(v, bool),
                   "speak_replies": lambda v: isinstance(v, bool),
                   "reply_language": lambda v: v in ("ms", "en"),
                   "voice_en": lambda v: v in [x["id"] for x in EN_VOICES],
                   "chat_model": lambda v: v in [m["id"] for m in CHAT_MODELS]}
        if key not in allowed or not allowed[key](value):
            return {"ok": False, "msg": f"Invalid setting {key}={value}"}
        cfg = load_json(CONFIG, {})
        cfg[key] = value
        CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        if key == "reply_language":
            # Tanpa ini, tukar bahasa dalam Settings tak berkesan sampai restart:
            # lang_note() dulu baca cakera setiap panggilan, tapi modul ini
            # menyimpan cache CURRENT_LANG yang diisi semasa main() sahaja.
            global CURRENT_LANG
            CURRENT_LANG = value
        return {"ok": True}

    def _voice_emit(self, kind, data=None):
        try:
            self._window.evaluate_js(f"window.onVoice && window.onVoice({json.dumps(kind)}, {json.dumps(data)})")
        except Exception:
            pass

    def listen(self):
        if self._listening or self._listen_request.is_set():
            return {"ok": False, "msg": "Already listening."}
        self._listen_request.set()  # pengurus mic akan mula merakam
        return {"ok": True}

    def stop_listen(self):
        self._listening = False
        return {"ok": True}

    def wake_status(self):
        # "on" bermaksud mic sedang mendengar "Hey Jarvis" SEKARANG, bukan
        # sekadar tetapan dalam config. Bila dimatikan, aliran mic langsung
        # tidak dibuka, jadi ini satu-satunya kebenaran yang berguna pada UI.
        return {"on": self._wake_ready,
                "enabled": bool(load_json(CONFIG, {}).get("wake_word", True))}

    def set_wake(self, on):
        """Hidup/matikan pendengar "Hey Jarvis" tanpa memulakan semula Jarvis.

        Bila dimatikan, gelung mic tidak membuka aliran langsung, jadi Jarvis
        tidak mendengar apa-apa sehingga butang mic ditekan. Ini yang Akmal
        minta: bunyi latar yang menyerupai suara tidak lagi menangkap arahan.
        """
        on = bool(on)
        cfg = load_json(CONFIG, {})
        cfg["wake_word"] = on
        try:
            CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return {"ok": False, "msg": "Could not save wake_word: %s" % e}
        # Bila menghidupkan semula, `wake_status()` hanya akan berkata true
        # selepas gelung benar-benar membuka aliran. Jangan berbohong di sini.
        if not on:
            self._wake_ready = False
        return {"ok": True, "enabled": on}

    def _mic_loop(self):
        """Satu-satunya pemilik mic. Dengar "Hey Jarvis" (jika dihidupkan) dan rakam arahan
        dalam aliran yang sama, jadi perkataan selepas "Hey Jarvis" tak terpotong."""
        import collections
        import numpy as np
        import sounddevice as sd
        thr = float(load_json(CONFIG, {}).get("wake_threshold", 0.35))
        # The mic opening is an event worth showing. "Dia dengar sendiri" is what
        # a silent stream looks like from the outside: the room hears something
        # and Jarvis answers without anyone having pressed anything. Emitting it
        # means the orb goes to 'listening' at the exact frame the device opens,
        # so a wake that fires on background noise is visible as it happens
        # instead of arriving as an unexplained answer.
        announced = False

        def build():
            """Muat model wake HANYA bila ia dihidupkan dalam config.

            Dibaca semula setiap kali, bukan sekali: menghidupkan semula "Hey
            Jarvis" mesti berkesan serta-merta tanpa memulakan semula Jarvis.
            Model ONNX mengambil masa ~1 s untuk dimuatkan, jadi ia dibina di
            dalam gelung ini dan bukan dalam set_wake().
            """
            if not load_json(CONFIG, {}).get("wake_word", True):
                return None
            try:
                from openwakeword.model import Model
                return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            except Exception as e:
                self._voice_emit("status", f"Hey Jarvis unavailable: {e}")
                return None

        ww = build()
        ring = collections.deque(maxlen=15)  # ~1.2 s audio terakhir
        noise = None
        while True:
            if ww is None:  # tanpa wake word: buka mic hanya bila butang ditekan
                # Mic mesti benar-benar berhenti, bukan sekadar berhenti bertindak
                # atas apa yang didengar. Menutup aliran adalah satu-satunya cara
                # Windows berhenti menunjukkan mic sedang digunakan, dan satu-satunya
                # cara bunyi bilik tidak lagi diproses langsung.
                self._wake_ready = False
                self._voice_emit("wake_ready", False)
                # Tunggu butang mic ATAU suis wake dihidupkan. poll(0.5) dan bukan
                # wait() kerana suis itu bukan Event — ia tulisan config dari
                # thread lain, dan inilah satu-satunya tempat yang boleh membina
                # semula model tanpa memulakan semula proses.
                if not self._listen_request.wait(0.5):
                    ww = build()
                    continue
            try:
                with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280) as st:
                    self._wake_ready = ww is not None
                    self._voice_emit("wake_ready", self._wake_ready)
                    if ww is not None and not announced:
                        announced = True
                        self._voice_emit("listening")
                    while True:
                        if self._listen_request.is_set():
                            self._listen_request.clear()
                            self._capture(st, list(ring)[-3:], noise, from_wake=False)
                            ring.clear()
                            if ww is None:
                                break
                            ww.reset()
                            continue
                        if ww is None:
                            break
                        # Suis dimatikan semasa aliran terbuka: keluar serta-merta
                        # supaya mikrofon benar-benar tertutup, bukan sekadar
                        # berhenti bertindak atas apa yang didengar.
                        if not load_json(CONFIG, {}).get("wake_word", True):
                            ww = None
                            break
                        data, _ = st.read(1280)
                        x = data[:, 0].copy()
                        ring.append(x)
                        rms = float(np.sqrt(np.mean((x / 32768.0) ** 2)))
                        noise = rms if noise is None else noise * 0.97 + rms * 0.03
                        if not self._speaking and ww.predict(x).get("hey_jarvis", 0) >= thr:
                            sv.beep("wake")
                            self._voice_emit("wake")
                            self._capture(st, list(ring)[-8:], noise, from_wake=True)
                            ring.clear()
                            ww.reset()
            except Exception as e:
                self._wake_ready = False
                self._listening = False
                self._voice_emit("error", str(e))
                time.sleep(5)
            try:
                with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280) as st:
                    self._wake_ready = ww is not None
                    self._voice_emit("wake_ready", self._wake_ready)
                    if ww is not None and not announced:
                        announced = True
                        self._voice_emit("listening")
                    while True:
                        if self._listen_request.is_set():
                            self._listen_request.clear()
                            self._capture(st, list(ring)[-3:], noise, from_wake=False)
                            ring.clear()
                            if ww is None:
                                break
                            ww.reset()
                            continue
                        if ww is None:
                            break
                        data, _ = st.read(1280)
                        x = data[:, 0].copy()
                        ring.append(x)
                        rms = float(np.sqrt(np.mean((x / 32768.0) ** 2)))
                        noise = rms if noise is None else noise * 0.97 + rms * 0.03
                        if not self._speaking and ww.predict(x).get("hey_jarvis", 0) >= thr:
                            sv.beep("wake")
                            self._voice_emit("wake")
                            self._capture(st, list(ring)[-8:], noise, from_wake=True)
                            ring.clear()
                            ww.reset()
            except Exception as e:
                self._wake_ready = False
                self._listening = False
                self._voice_emit("error", str(e))
                time.sleep(5)

    def set_speaking(self, on):
        # Jangan kesan "Hey Jarvis" dari suara Jarvis sendiri
        self._speaking = bool(on)
        return {"ok": True}

    def _capture(self, st, preroll, noise, from_wake):
        """Rakam satu arahan dari aliran mic yang sedia terbuka, transkripsi, dan laksana."""
        import numpy as np
        self._listening = True
        threading.Thread(target=self._whisper, daemon=True).start()  # panaskan model sambil dengar
        cfg_min = float(load_json(CONFIG, {}).get("mic_min_level", 0.0008))
        frames = [p.astype(np.float32) / 32768.0 for p in preroll]
        started, silent, waited, last_emit = False, 0, 0, 0
        floor = max(noise or 0, 2e-5)
        while self._listening:
            data, _ = st.read(1280)
            x = data[:, 0].astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(x ** 2)))
            if not started and waited < 4 and not from_wake:  # anggar bunyi latar sebelum bercakap
                floor = max(rms if noise is None else (floor * 0.7 + rms * 0.3), 2e-5)
            level = min(1.0, max(0.0, (rms / floor - 1) / 12))
            if time.time() - last_emit > 0.08:
                self._voice_emit("level", round(level, 3))
                last_emit = time.time()
            loud = rms > max(floor * 4, cfg_min) and (from_wake or waited >= 4)
            if loud:
                started, silent = True, 0
            if started:
                frames.append(x)
                silent = 0 if loud else silent + 1
                if silent >= 13 or len(frames) >= 250:  # senyap ~1 s, atau 20 s maksimum
                    break
            else:
                waited += 1
                if waited >= (60 if from_wake else 85):  # tiada suara
                    break
        self._listening = False
        if len(frames) <= len(preroll) + 2:
            self._voice_emit("none")
            return
        self._voice_emit("transcribing")
        try:
            audio = np.concatenate(frames)
            peak = float(np.abs(audio).max())
            if 0 < peak < 0.5:  # kuatkan suara perlahan supaya Whisper dengar jelas
                audio = audio * min(0.9 / peak, 60.0)
            text = self._transcribe(audio)
        except Exception as e:
            self._voice_emit("error", str(e))
            return
        command = sv.clean_command(text) if text else ""
        if not command:
            self._voice_emit("none" if not from_wake else "wake_only")
            return
        # Kawalan laptop (next slide, volume, ...) terus dilaksana tanpa AI dan tanpa munculkan Jarvis
        done = self.quick_control(command, allow_open=True)
        if done.get("handled"):
            self._voice_emit("control", {"text": text, "label": done["label"]})
            return
        self._voice_emit("text", text)

    # ---------- Kawalan laptop: ayat -> satu panggilan system.py ----------
    def resolve_system(self, text):
        """Padan ayat dengan satu tindakan sistem. Pulangkan {"handled","label"}.

        Ini bukan AI dan sengaja bukan AI: bila Akmal cakap "volume 30", dia
        mahu 30, bukan model yang berfikir dan mungkin memberi 40. Corak di
        bawah tertib dari spesifik ke longgar, dan yang tidak padan langsung
        jatuh ke false — ayat itu terus ke Claude seperti biasa.

        Pengesahan: kalau tindakan itu tingkat 'pukal' (bunuh proses, tutup
        tetingkap, recycle, kuasa), token disimpan dalam self._pending_token
        dan ayat asal dalam self._pending_cmd, supaya "ya" selepas itu
        menyambung kerja yang sama tanpa Akmal perlu ulang ayat penuh.
        """
        raw = str(text or "").strip()
        t = sv.clean_command(raw)
        low = t.lower()
        if not low:
            return {"handled": False}

        # "ya" / "tak" hanya bermakna kalau ada tindakan yang menunggu
        if re.match(r"^(ya|yes|ok|okay|buat|teruskan|jalan|go|confirm|sahkan)\b", low):
            if self._pending_token:
                tok, self._pending_token = self._pending_token, None
                self._pending_cmd = None
                return self._sys_report(self._sys.confirm(tok))
            return {"handled": False}
        if re.match(r"^(tak|no|jangan|batal|cancel|stop|jangan buat)\b", low):
            if self._pending_token:
                self._sys.cancel(self._pending_token)
                self._pending_token = None
                self._pending_cmd = None
                return {"handled": True, "label": "Dibatalkan"}
            return {"handled": False}

        m = self._match_system(low)
        if m is None:
            return {"handled": False}
        action, args = m
        if action == "show_doc":
            return self._open_doc_in_stage(args.get("path", ""))
        res = self._sys.do(action, **args)
        if res.get("need_confirm"):
            self._pending_token = res["token"]
            self._pending_cmd = raw
            self._push(f"window.jarvisConfirm && window.jarvisConfirm({json.dumps(res)})")
        return self._sys_report(res)

    @staticmethod
    def _sys_report(res):
        msg = res.get("msg") or ("Done." if res.get("ok") else "Failed.")
        label = ("✔ " if res.get("ok") else "✖ ") + msg
        if res.get("need_confirm"):
            label = "? " + msg
        return {"handled": True, "label": label, "confirm": bool(res.get("need_confirm"))}

    def _match_system(self, low):
        """Satu jadual corak -> (action, args). Tiada kesan sampingan di sini."""
        pct = sysctl.parse_pct

        def num(*keys):
            for k in keys:
                if k in low:
                    return pct(low)
            return None

        # -- kuasa dulu: ayat kuasa mesti tidak boleh tersalah masuk cabang lain
        if re.search(r"\b(batal|batalkan|cancel)\b.*\b(shutdown|restart|tutup|restart)\b|^batal shutdown$", low):
            return "power_cancel", {}
        if re.search(r"\b(mati|tutup|shutdown|shut down|power off)\b.*\b(laptop|pc|komputer|computer)\b"
                     r"|\b(shutdown|tutup laptop)\b", low):
            return "shutdown", {}
        if re.search(r"\b(restart|reboot|mula semula|restartkan)\b.*\b(laptop|pc|komputer|computer)?\b", low):
            return "restart", {}
        if re.search(r"\b(sleep|tidur|hibernate)\b.*\b(laptop|pc)?\b", low):
            return "sleep", {}
        if re.search(r"^(kunci|lock)\b.*\b(laptop|pc|skrin|screen|windows)?|^lock$", low):
            return "lock", {}

        # -- audio
        if re.search(r"\b(mute|unmute|senyap|bisukan)\b", low):
            return "mute", {"on": not re.search(r"\b(unmute|hidupkan|bukakan|on)\b", low)}
        if "volume" in low or "bunyi" in low or "suara" in low:
            if re.search(r"\b(berapa|check|status|tengok|semak)\b", low):
                return "status", {}
            p = num("volume", "bunyi", "suara")
            if p is not None:
                return "volume", {"level": p}
            if re.search(r"\b(naik|up|kuat|besar|tinggi)\b", low):
                return "volume", {"delta": 10}
            if re.search(r"\b(turun|down|kecil|perlahan|rendah)\b", low):
                return "volume", {"delta": -10}
            if re.search(r"\b(maksimum|max|penuh)\b", low):
                return "volume", {"level": 100}

        # -- kecerahan. Akhiran -kan mesti dibenarkan: "cerahkan skrin", bukan
        # "cerah skrin" — \b selepas "cerah" tidak akan padan dengan "cerahkan".
        if re.search(r"\b(brightness|kecerahan|cerah(?:kan)?|terang(?:kan)?|malap(?:kan)?|gelap(?:kan)?)\b", low):
            if re.search(r"\b(berapa|status|tengok|semak)\b", low):
                return "brightness", {}
            p = num("brightness", "kecerahan")
            if p is not None:
                return "brightness", {"level": p}
            if re.search(r"\b(naik(?:kan)?|up|cerah(?:kan)?|terang(?:kan)?)\b", low):
                return "brightness", {"delta": 10}
            if re.search(r"\b(turun(?:kan)?|down|malap(?:kan)?|gelap(?:kan)?|kurang(?:kan)?)\b", low):
                return "brightness", {"delta": -10}

        # -- clipboard
        if re.search(r"\b(clipboard|salin|copy|paste|tampal)\b", low):
            if re.search(r"\b(baca|apa|tengok|read|show)\b", low):
                return "clip_read", {}
            m = re.search(r"(?:salin|copy|clipboard)\s+(.+)", low)
            if m:
                return "clip_write", {"text": m.group(1).strip()}

        # -- tetingkap
        m = re.search(r"\b(?:fokus|focus|pergi ke|tukar ke|switch to|depan kan|depankan)\s+(.+)$", low)
        if m:
            return "focus", {"title": m.group(1).strip()}
        m = re.search(r"\b(?:minimi[sz]e|kecilkan)\s+(.+)$", low)
        if m:
            return "minimize", {"title": m.group(1).strip()}
        m = re.search(r"\b(?:maximi[sz]e|besarkan|penuhkan)\s+(.+)$", low)
        if m:
            return "maximize", {"title": m.group(1).strip()}
        m = re.search(r"\b(?:tutup|close|kill)\s+(.+)$", low)
        if m:
            target = m.group(1).strip()
            # kalau tajuk tetingkap wujud, itu yang Akmal maksudkan; kalau tidak,
            # mungkin dia sebut nama proses ("tutup chrome")
            if sysctl.find_window(target):
                return "close_window", {"title": target}
            return "kill", {"name": target}
        if re.search(r"\b(tunjuk|show|pergi)\b.*\bdesktop\b", low):
            return "show_desktop", {}

        # -- senarai & status (baca sahaja)
        if re.search(r"\b(tetingkap|window|app)\b.*\b(apa|senarai|list|terbuka|buka)\b"
                     r"|\b(apa|senarai)\b.*\b(tetingkap|window)\b", low):
            return "windows", {}
        if re.search(r"\b(proses|process)\b.*\b(apa|senarai|list|banyak|berat|makan)\b"
                     r"|\b(apa|senarai)\b.*\b(proses|process)\b", low):
            return "processes", {}
        if re.search(r"^(status|keadaan)\b.*\b(laptop|pc|sistem|system)?$", low) or low in ("status", "status laptop"):
            return "status", {}

        # -- shell senarai putih
        m = re.match(r"^(?:run|jalankan|shell|terminal)\s+(.+)$", low)
        if m and sysctl.shell_allowed(m.group(1)):
            return "shell", {"cmd": m.group(1).strip()}

        # -- buka fail dokumen: cari nama itu dalam folder kerja, papar dalam stage
        m = re.match(r"^(?:buka|open|tunjuk|show|papar)\s+(\S+\.(?:pdf|docx|xlsx|xlsm|pptx|csv|md|txt))$", low)
        if m:
            hit = self._find_doc(m.group(1))
            if hit:
                return "show_doc", {"path": str(hit)}

        # -- buka app / url (paling longgar, jadi paling akhir)
        m = re.match(r"^(?:buka|open|lancar|launch|run)\s+(https?://\S+|\S+\.\w{2,4}(?:/\S*)?)$", low)
        if m and ("." in m.group(1) and " " not in m.group(1)):
            target = m.group(1)
            if re.match(r"^https?://", target) or re.match(r"^\S+\.(com|net|org|io|my|id|co|dev|ai|app|gg)\b", target):
                return "url", {"url": target}
        return None

    def _find_doc(self, name):
        """Cari fail dokumen ikut nama dalam workdir, Desktop, Documents, Downloads.

        Satu lapisan sahaja bagi setiap folder, bukan rekursif: rekursif pada
        ~ akan menyentuh puluhan ribu fail dan menjadikan satu ayat suara ambil
        dua saat. Padanan: tepat dahulu, kemudian nama tanpa sambungan,
        kemudian mengandung.
        """
        name = (name or "").strip().lower()
        if not name:
            return None
        roots = [Path(os.path.expanduser(load_json(CONFIG, {}).get("workdir", "~"))),
                 ROOT, HOME / "Desktop", HOME / "Documents", HOME / "Downloads"]
        seen, cands = set(), []
        for root in roots:
            try:
                for p in root.iterdir():
                    if not p.is_file() or p in seen:
                        continue
                    if p.suffix.lower().lstrip(".") not in ("pdf", "docx", "xlsx", "xlsm", "pptx", "csv", "md", "txt"):
                        continue
                    seen.add(p)
                    cands.append(p)
            except OSError:
                continue
        exact = next((p for p in cands if p.name.lower() == name), None)
        if exact:
            return exact
        stem = next((p for p in cands if p.stem.lower() == Path(name).stem.lower()), None)
        if stem:
            return stem
        return next((p for p in cands if name in p.name.lower()), None)

    def _open_doc_in_stage(self, path, page=None):
        """Papar satu dokumen dalam panel DOK, dari suara atau dari model."""
        r = self.docs_open(path, page)
        if not r.get("ok"):
            return {"handled": True, "label": "✖ " + r.get("msg", "The document could not be read.")}
        self.stage_pane("docs")
        pj = "null" if page is None else str(int(page))
        # Python membaca dulu supaya label jujur, JS membaca semula untuk melukis.
        # _push, bukan _emit: onClaude tiada cabang 'docs', dan evaluate_js tidak
        # menunggu promise — jadi tiada gunanya menghantar dua kali.
        self._push(f"window.stageDocs && window.stageDocs.open({json.dumps(r['path'])}, {pj})")
        return {"handled": True, "label": "✔ " + r["name"],
                "msg": r["name"], "path": r["path"]}

    def cancel_system(self, token=None):
        """Butang 'Tak' di HUD. Buang token tanpa menjalankan apa-apa."""
        self._pending_token = None
        self._pending_cmd = None
        return self._sys.cancel(token)

    # ---------- Stage: APP (Fasa 7) ----------
    # Tetingkap asal di-embed dengan SetParent, bukan ditangkap sebagai imej.
    # App yang di-embed masih hidup — video masih main, skrol masih jalan — tetapi
    # ia duduk ATAS WebView2, jadi ia mesti disembunyikan setiap kali panel lain
    # dipilih. Itu bukan pilihan; tanpa itu app terapung di atas panel lain.
    def app_stage_rect(self, x, y, w, h, scale=1.0):
        """JS ukur rect stage dalam CSS px; di sini ia ditukar ke fizikal px.

        Rect sebenar disimpan mentah, tanpa penapis saiz. Penapis lama menolak
        apa-apa yang lebih kecil daripada 240×180 dan *tidak menyimpan* — jadi
        bila panel NATIVE baru dibuka, host masih tersembunyi, rect datang
        0×0, dan app yang sudah di-attach kekal di rect lalai 0,0,640,480 di
        penjuru kiri atas. Sekarang nilai kecil hanya bermakna "belum boleh
        letak", bukan "buang ukuran".
        """
        self._app_rect = (float(x), float(y), float(w), float(h), float(scale))
        if w < 240 or h < 180:
            return {"ok": True, "placed": False}
        if self._sys.embed.hwnd:
            return self._app_place()
        return {"ok": True, "placed": False}

    def _app_place(self):
        rect = getattr(self, "_app_rect", None)
        if not rect:
            return {"ok": False, "msg": "Stage rect has not been measured."}
        x, y, w, h, scale = rect
        ok = self._sys.embed.place(x, y, w, h, scale)
        return {"ok": ok, "msg": "" if ok else "The window could not be placed."}

    def hud_hwnd(self):
        """HWND HUD yang sebenar — dari objek Window, bukan gelintar tajuk.

        FindWindowW(None, "Jarvis") memulangkan HWND pertama dengan tajuk itu,
        dan satu tetingkap pywebview menghasilkan puluhan. Yang betul ialah
        Form pywebview itu sendiri: `self._window.native.Handle`. Kalau belum
        ada (semasa import, sebelum start()), jatuh balik ke gelintar tajuk.
        """
        w = getattr(self, "_window", None)
        try:
            h = int(w.native.Handle.ToInt64())
            if sysctl.is_window(h):
                return h
        except Exception:
            pass
        return sysctl.hud_hwnd("Jarvis")

    def web_hwnd(self):
        """HWND tetingkap web anak, atau 0. Dipakai ujian hidup sahaja."""
        w = getattr(self, "_web_win", None)
        try:
            h = int(w.native.Handle.ToInt64())
            return h if sysctl.is_window(h) else 0
        except Exception:
            return 0

    def app_attach(self, title):
        """Ambil tetingkap lain masuk ke dalam stage."""
        hud = self.hud_hwnd()
        if not hud:
            return {"ok": False, "msg": "Jarvis window not found."}
        # Cari HWND app SEBELUM menyentuh HUD. find_window membaca senarai
        # tetingkap dan mencari padanan kabur; kalau HUD dapat fokus dahulu,
        # "notepad" tidak lagi di hadapan dan padanan boleh tersasar.
        target = sysctl.find_window(title)
        if not target:
            return {"ok": False, "msg": "Window \"%s\" not found." % title,
                    "title": ""}
        ok, msg = self._sys.embed.attach(hud, title)
        if ok:
            scale = sysctl.dpi_scale(hud)
            # Jangan letak pada rect lalai. Jarvis buat sementara waktu jadi
            # foreground untuk dapatkan HWND-nya, jadi app mesti diberi satu
            # tempat yang wajar sehingga JS menghantar ukuran sebenar —
            # kalau tidak app muncul di penjuru kiri atas selama satu saat.
            rect = getattr(self, "_app_rect", None)
            if not rect or float(rect[2] or 0) < 240:
                rect = (0.17 * 1920, 0.16 * 1080, 0.66 * 1920, 0.68 * 1080, scale)
            self._app_rect = rect
            self._app_place()
            self._emit("app", {"attached": self._sys.embed.title})
        return {"ok": ok, "msg": msg, "title": self._sys.embed.title}

    def app_detach(self):
        """Pulihkan tetingkap ke desktop dengan gaya dan ibu asalnya."""
        ok = self._sys.embed.detach()
        self._emit("app", {"attached": ""})
        return {"ok": True, "msg": "Window returned to the desktop." if ok else "No app is embedded."}

    def app_show(self, on):
        """Dipanggil setiap kali panel bertukar."""
        if not self._sys.embed.hwnd:
            return {"ok": False}
        self._sys.embed.show(bool(on))
        return {"ok": True, "visible": bool(on)}

    def app_state(self):
        e = self._sys.embed
        return {"ok": True, "attached": bool(e.hwnd), "title": e.title, "visible": e.visible}

    def app_windows(self, limit=30):
        """Senarai tetingkap untuk dipilih dalam panel APP. Jarvis sendiri dibuang."""
        wins = [w for w in sysctl.list_windows(int(limit) + 4)
                if w["title"] not in ("Jarvis",)]
        return {"ok": True, "windows": wins[:int(limit)]}

    def quick_control(self, text, allow_open=False):
        """Arahan pantas tanpa AI. Pulangkan {"handled": bool, "label": str}.

        Susunan penting — yang paling murah dan paling tepat dahulu:
          1. kekunci media dalam services.py ("next slide", "volume naik")
          2. resolver system.py ("volume 30", "tutup Chrome", "kunci laptop")
          3. panel stage ("panel media")
          4. buka app/fail/media (hanya bila allow_open)
        Resolver di atas kekunci kerana ayat bernombor mesti dibaca sebagai
        nombor; "volume 30" yang lalu melalui tekan-kekunci 30 kali akan
        bunyikan bunyi bising dan berakhir di 100%. Kata kunci media pula
        ("lagu", "muzik", "slide") dikecualikan, supaya "main lagu" masih
        jatuh ke services.py dan bukan ditelan resolver.
        """
        if not re.search(r"\b(lagu|muzik|music|track|song|slide|slideshow|pembentangan|"
                         r"presentation|scroll)\b", str(text or "").lower()):
            sysr = self.resolve_system(text)
            if sysr.get("handled"):
                sv.beep()
                return sysr
        # "pergi slide 8" — the deck pane jumps straight there. This path exists
        # because stepping is a guess: eight keypresses desync the instant Akmal
        # clicks a thumbnail or presses Home on the projector. A spoken number
        # is ground truth, so it re-opens the deck at that page instead.
        m_sl = re.match(r"^(?:(?:pergi|pig|gi|ke|to|jump|go)\s+)?slide\s*(\d{1,3})$|"
                        r"^(?:pergi|ke|to|jump)\s+(?:slide\s+)?(\d{1,3})$",
                        sv.clean_command(text))
        if m_sl and self._deck.get("path"):
            n = int(m_sl.group(1) or m_sl.group(2))
            total = self._deck.get("total") or 0
            if 1 <= n <= max(total, 1):
                self._deck["slide"] = n
                self._push("window.stageDocs && window.stageDocs.slide(%d)" % n)
                sv.beep()
                return {"handled": True, "label": "Slide %d/%d" % (n, total)}
        action = sv.match_control(text)
        if action:
            label = sv.do_control(action)
            self._deck_step(action)
            sv.beep()
            return {"handled": True, "label": self._deck_label(action, label)}
        # panel stage ikut suara: "panel media", "tukar fail", "buka terminal"
        m_pane = re.match(r"^(?:panel|tukar|pergi|buka)\s+(comms|media|terminal|term|fail|files|editor|edit|web|browse|dokumen|docs|analisis|ana|app|native)$",
                          sv.clean_command(text).lower())
        if m_pane:
            alias = {"terminal": "term", "fail": "files", "edit": "editor", "web": "browse",
                     "dokumen": "docs", "analisis": "ana", "app": "native"}
            pane = alias.get(m_pane.group(1), m_pane.group(1))
            self.stage_pane(pane)
            sv.beep()
            return {"handled": True, "label": f"Panel {pane}"}
        if allow_open:
            m = re.match(r"^(buka|open|lancar|launch|bukakan|main|play|putar)\s+(.+)$", sv.clean_command(text))
            if m and not re.search(r"\b(slide|email|emel|gmail|drive)\b", m.group(2)):
                # media dulu: kalau nama fail ada dalam media/, main dalam stage
                res = self.media_open(m.group(2))
                if res.get("ok"):
                    sv.beep()
                    return {"handled": True, "label": f"Media {res['name']}"}
                msg, _ = self._tool_open(m.group(2))
                if not msg.startswith("Could not find"):
                    sv.beep()
                    return {"handled": True, "label": msg}
        return {"handled": False}

    def _whisper(self):
        self._stt_used = time.time()
        with self._stt_lock:
            if self._stt is None:
                from faster_whisper import WhisperModel
                size = load_json(CONFIG, {}).get("whisper_model", "small")
                try:  # guna salinan tempatan; tanpa ini setiap muat semak internet (~3 minit)
                    self._stt = WhisperModel(size, device="cpu", compute_type="int8", local_files_only=True)
                except Exception:
                    self._voice_emit("status", "Downloading Whisper model " + size + "… (one time only)")
                    self._stt = WhisperModel(size, device="cpu", compute_type="int8")
            return self._stt

    def _stt_janitor(self):
        """Buang model Whisper (~2 GB) dari memori bila mic tak digunakan 5 minit."""
        import gc
        idle = int(load_json(CONFIG, {}).get("whisper_unload_after", 300))
        while True:
            time.sleep(30)
            with self._stt_lock:
                if self._stt is not None and not self._listening and time.time() - self._stt_used > idle:
                    self._stt = None
                    gc.collect()

    def _stt_names(self):
        # Nama folder Desktop & app bantu pengecaman eja nama khas dengan betul
        desk = known_folder("Desktop")
        names = [p.name for p in desk.iterdir() if p.is_dir()][:30] if desk else []
        apps = [a.get("name", "") for a in load_json(SHORTCUTS, {}).get("apps", [])]
        return ["Jarvis", "Akmal"] + names + apps

    def _stt_hint(self):
        # Contoh gaya cakap Akmal (BM KL campur English) supaya Whisper tak tukar ke ejaan Indonesia
        return ("Hey Jarvis, tolong check email aku. Buka folder Pengakap. Analisis fail sipeng kat desktop. "
                "Next slide, volume naik. Cuaca hari ni macam mana? Okay, settle. " + ", ".join(self._stt_names()))

    def _transcribe(self, audio):
        """Suara -> teks. Google Speech-to-Text (jika dipilih & key dibenarkan), jika tidak Whisper tempatan."""
        cfg = load_json(CONFIG, {})
        if cfg.get("stt_engine") in ("google", "hybrid"):
            # Hibrid: Google laju (~2 s); jika keyakinan rendah, semak semula dengan Whisper (tepat untuk loghat & nama khas)
            try:
                text, conf = self._google_stt(audio)
                if text and (cfg.get("stt_engine") == "google" or conf >= float(cfg.get("stt_min_confidence", 0.85))):
                    return text
                near = sv.fuzzy_control(text)   # arahan kawalan pendek: jangan tunggu Whisper
                if near:
                    return near
                self._voice_emit("status", f'Double-checking "{text[:40]}"…')
            except Exception as e:
                self._voice_emit("status", f"Google STT failed ({str(e)[:50]}), using Whisper")
        segs, _ = self._whisper().transcribe(
            audio, language=cfg.get("whisper_language", "ms"), beam_size=int(cfg.get("whisper_beam", 5)), best_of=5,
            temperature=[0.0, 0.2, 0.4], condition_on_previous_text=False,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt=self._stt_hint(), hotwords=" ".join(self._stt_names()[:40]))
        return " ".join(s.text.strip() for s in segs).strip()

    def _google_stt(self, audio):
        import base64
        import numpy as np
        sec = load_json(SECRETS, {})
        key = sec.get("google_stt_api_key") or sec.get("google_tts_api_key")
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        body = {"config": {"encoding": "LINEAR16", "sampleRateHertz": 16000, "languageCode": "ms-MY", "enableAutomaticPunctuation": True,
                           "speechContexts": [{"phrases": ["Hey Jarvis", "Jarvis"] + self._stt_names()[:200] + ["next slide", "previous slide", "check email", "volume naik", "volume turun", "analisis", "buka folder"], "boost": 15}]},
                "audio": {"content": base64.b64encode(pcm).decode()}}
        req = urllib.request.Request("https://speech.googleapis.com/v1/speech:recognize", method="POST",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Goog-Api-Key": key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        alts = [x["alternatives"][0] for x in d.get("results", []) if x.get("alternatives")]
        return " ".join(a["transcript"] for a in alts).strip(), min([a.get("confidence", 0) for a in alts] or [0])

    # ---------- Tetingkap ----------
    def power(self, action):
        """Shutdown/restart laptop selepas 5 saat (boleh dibatalkan dengan action='cancel')."""
        cmd = {"shutdown": ["shutdown", "/s", "/t", "5"],
               "restart": ["shutdown", "/r", "/t", "5"],
               "cancel": ["shutdown", "/a"]}.get(action)
        if not cmd:
            return {"ok": False, "msg": "Unknown power action."}
        r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
        return {"ok": r.returncode == 0, "msg": r.stderr.decode("utf-8", "replace").strip()}

    def minimize(self):
        self._window.minimize()

    def quit(self):
        self.stop()
        self._window.destroy()


def _note(msg):
    """Tulis satu baris ke runtime/startup.log. Tidak pernah membaling."""
    try:
        STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        if STARTUP_LOG.exists() and STARTUP_LOG.stat().st_size > 256 * 1024:
            STARTUP_LOG.write_text("", encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write("%s  pid=%d  %s\n" % (stamp, os.getpid(), msg))
    except Exception:
        pass


def _alive(pid):
    """Adakah pid ini proses Jarvis yang masih bernyawa? Bukan sekadar wujud."""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    # Diri sendiri sentiasa hidup. Ini perlu kerana cmdline sebuah proses
    # yang dimulakan dengan `python -c ...` tidak mengandungi "main.py" —
    # dahulu semakan ini menyebabkan proses tidak mengenali dirinya, jadi
    # ia sendiri dianggap lock basi dan boleh dirampas.
    if pid == os.getpid():
        return True
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
        # Padankan nama fail, bukan substring: sesiapa yang membuka
        # "main.py.bak" dalam editor bukan Jarvis.
        for part in p.cmdline():
            if os.path.basename(part).lower() in ("main.py", "launch.vbs"):
                return True
        return False
    except Exception:
        return False


def _jarvis_pids():
    """Semua pid yang menjalankan main.py — termasuk yang bukan kita."""
    out = []
    try:
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                for part in p.info["cmdline"] or []:
                    if os.path.basename(part).lower() == "main.py":
                        out.append(p.info["pid"])
                        break
            except Exception:
                continue
    except Exception:
        pass
    owner = _lock_owner()
    if owner:
        out.append(owner)
    if os.getpid() not in out:
        out.append(os.getpid())
    return out


def _hud_hwnd(pids=None):
    """Cari tetingkap HUD yang sebenar, milik mana-mana proses Jarvis.

    Dua perkara perlu betul di sini.

    Pertama, ia mesti menyiasat semua proses Jarvis, bukan hanya pid dirinya.
    Versi pertama fungsi ini menyemak `pid.value != os.getpid()` dan melangkau
    yang lain — jadi pelancaran kedua tidak pernah nampak tetingkap pelancaran
    pertama, menyangka tiada HUD, dan tersekat pada lock. Itu pepijat yang sama
    seperti asal, cuma berpakaian baru.

    Kedua, padanan tajuk dibuat longgar ("JARVIS" atau "STAGE"). Diukur pada
    binaan pywebview 6.2.1 ini, tetingkap kekal bergelar "Jarvis" walaupun
    stage.html menukar document.title — jadi padanan ketat sebenarnya berfungsi
    di sini. Longgar itu pertahanan, bukan pembaikan: satu tajuk yang dikodkan
    keras akan patah bila ia diterjemah atau dinamakan semula, dan gelintar
    tajuk sudah pun menjadi punca kegagalan senyap sebelum ini.
    """
    import ctypes
    u32 = ctypes.windll.user32
    want = set(int(p) for p in (pids or _jarvis_pids()))
    hits = []

    def visit(hwnd, _lparam):
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in want:
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if not n:
            # Tetingkap tanpa tajuk bukan HUD — HUD selalu ada tajuk selepas
            # stage.html selesai dimuatkan.
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.upper()
        if "JARVIS" in title or "STAGE" in title:
            hits.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    u32.EnumWindows(WNDENUMPROC(visit), 0)
    return hits[0] if hits else 0


def _say(title, text, style=0x00000004):
    """MsgBox melalui user32 — satu-satunya saluran yang kelihatan di bawah
    pythonw, yang menelan setiap print dan traceback. Pulangkan id butang."""
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, str(text), str(title), style)
    except Exception:
        return 0


def _lock_owner():
    """Baca runtime/jarvis.lock. Pulangkan pid jika pemiliknya masih hidup.

    Lock basi — proses yang dah mati, atau pid yang dah diguna proses lain —
    dianggap tiada, jadi ia tidak boleh menyekat pelancaran seterusnya.
    """
    try:
        raw = json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:
        return 0
    pid = int(raw.get("pid") or 0)
    return pid if _alive(pid) else 0


def _take_lock():
    """Ambil lock. Pulangkan (ok, pid_lama)."""
    old = _lock_owner()
    if old and old != os.getpid():
        return False, old
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps({"pid": os.getpid(),
                                    "started": time.strftime("%Y-%m-%d %H:%M:%S")}),
                        encoding="utf-8")
    except Exception:
        pass  # tiada lock pun HUD masih boleh dibuka; jangan matikan ia sebab ini
    return True, 0


def _drop_lock():
    try:
        if LOCK.exists() and _lock_owner() == os.getpid():
            LOCK.unlink()
    except Exception:
        pass


def already_running():
    """Jika HUD memang ada di skrin, bawa ia ke depan dan pulangkan True.

    Ini pernah salah teruk: mutex bernama kekal wujud selagi *sesiapa* yang
    menciptanya masih bernyawa, walaupun tetingkapnya sudah tiada. Satu proses
    pythonw yang tergantung sejak 1:22 tengah hari memegang mutex itu, jadi
    setiap klik pada shortcut selepas itu nampak seperti tiada apa-apa
    berlaku — main.py terus keluar di baris ini. Kehadiran mutex bukan bukti
    ada HUD; tetingkap yang boleh ditunjuk itu buktinya.
    """
    import ctypes
    u32 = ctypes.windll.user32

    hwnd = _hud_hwnd()
    if not hwnd:
        return False

    _note("hud already up: hwnd=%s" % hwnd)
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    else:
        u32.ShowWindow(hwnd, 5)  # SW_SHOW — no-op if already visible
    try:
        u32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return True


def _reap(pids):
    """Tamatkan proses Jarvis yang tersangkut. Pulangkan yang berjaya dibunuh."""
    gone = []
    for pid in pids:
        if int(pid) == os.getpid():
            continue
        try:
            p = psutil.Process(int(pid))
            p.terminate()
            try:
                p.wait(timeout=6)
            except psutil.TimeoutExpired:
                p.kill()
                p.wait(timeout=6)
            gone.append(int(pid))
        except Exception:
            continue
    return gone


def main():
    _note("start")
    if already_running():
        return

    owner = _lock_owner()
    if owner and owner != os.getpid():
        # Hidup, memegang lock, tetapi tiada tetingkap yang boleh ditunjuk.
        # Dahulu ini keluar senyap. Sekarang ia bertanya — satu dialog,
        # bukan satu-satunya jalan buntu.
        _note("stale instance pid=%s, asking" % owner)
        answer = _say("Jarvis",
                      "An earlier Jarvis (pid %s) is still running but its window is gone.\n\n"
                      "End it and start a fresh HUD?" % owner,
                      0x00000004 | 0x00000001)  # MB_YESNO | MB_ICONWARNING
        if answer != 6:  # IDYES
            _note("user declined to end pid %s" % owner)
            return
        gone = _reap([owner])
        _note("reaped %s" % gone)
        if owner in gone:
            try:
                LOCK.unlink()
            except Exception:
                pass

    ok, old = _take_lock()
    if not ok:
        # Dua klik laju: instance pertama sudah menulis lock tetapi tetingkapnya
        # belum sempat wujud, jadi `already_running()` di atas belum nampak apa
        # apa. Tunggu sebentar dan periksa semula — lebih baik daripada dialog
        # yang menyuruh Manuel cuba lagi untuk sesuatu yang sedang naik.
        for _ in range(24):  # ~7 saat
            time.sleep(0.3)
            if already_running():
                _note("second instance waited, hud came up")
                return
            if _lock_owner() == 0:
                break  # pemilik lock sudah mati — cuba rampas semula
        ok, old = _take_lock()
    if not ok:
        _note("still blocked by pid %s after waiting" % old)
        _say("Jarvis",
             "Another Jarvis (pid %s) is starting up and holds the lock.\n"
             "Give it a moment, then try again." % old, 0x00000030)
        return
    try:
        _run()
    except BaseException:
        err = traceback.format_exc()
        _note("CRASH\n" + err)
        _say("Jarvis - crashed on startup",
             err.strip().splitlines()[-1] + "\n\nFull traceback:\n" + str(STARTUP_LOG),
             0x00000010)  # MB_ICONERROR
        raise
    finally:
        _drop_lock()
        _note("exit")


def _run():
    global CURRENT_LANG
    CURRENT_LANG = load_json(CONFIG, {}).get("reply_language", "ms")
    # benarkan suara Jarvis dimainkan tanpa perlu klik dulu
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    api = Api()
    api._media = MediaServer(MEDIA).serve_ui(ROOT / "ui").start()
    _note("media server on %s" % api._media.stage_url)
    # The HUD is loaded over http from the range server, not from file://.
    # A file:// document has a null origin, and the YouTube embed rejects a
    # null-origin referrer outright ("Video player configuration error 153"),
    # so an inline player is impossible from the filesystem path. Same page,
    # same bytes, real origin — served on loopback by a socket that already
    # exists for the media panel.
    # Autoplay: WebView2 blocks media that starts without a click, so a local
    # file loads but sits at t=0 with a NotAllowedError. Measured: with this
    # flag the same file plays (`paused=false`, currentTime advancing). It has
    # to be set before webview.start(); WebView2 reads the env var once, when it
    # creates its browser process.
    os.environ.setdefault(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--autoplay-policy=no-user-gesture-required")
    api._window = webview.create_window(
        "Jarvis",
        api._media.stage_url,
        js_api=api,
        fullscreen=True,
        background_color="#140d26",
    )
    threading.Thread(target=api._stt_janitor, daemon=True).start()
    threading.Thread(target=api._mic_loop, daemon=True).start()       # "Hey Jarvis" + rakaman
    threading.Thread(target=api._prayer_watch, daemon=True).start()   # peringatan waktu solat
    sv.prayer_today(api._cfg_place()[2])                               # ambil waktu solat sebulan jika belum ada
    _note("webview.start")
    webview.start(api._wire_drop, api._window)
    # Pulangkan di sini bermakna GUI loop sudah berhenti. Tanpa baris
    # seterusnya, benang bukan-daemon yang masih hidup (rakaman mikrofon,
    # penjaga STT) akan menahan proses ini bernyawa tanpa tetingkap — dan
    # itulah rupa sebenar pepijat pelancaran ini: satu pythonw tergantung
    # sejak 1:22 tengah hari, 1468 saat CPU, sifar tetingkap.
    _note("gui loop returned")
    _drop_lock()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(0)


if __name__ == "__main__":
    main()
