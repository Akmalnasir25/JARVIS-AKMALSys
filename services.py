"""Perkhidmatan Jarvis: cuaca, waktu solat JAKIM, kawalan laptop (kekunci), tangkap skrin.

Semua sumber data guna API rasmi/percuma: Open-Meteo (cuaca & udara), JAKIM e-Solat (waktu solat).
"""
import ctypes
import json
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache.json"
_cache_lock = threading.Lock()


# ---------- Cache kecil (cache.json) ----------
def cache_get(key, default=None):
    try:
        return json.loads(CACHE.read_text(encoding="utf-8")).get(key, default)
    except Exception:
        return default


def cache_set(key, value):
    with _cache_lock:
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data[key] = value
        CACHE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-desktop/0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------- Cuaca & kualiti udara (Open-Meteo) ----------
WEATHER_CODES = {
    0: "cerah", 1: "cerah sikit berawan", 2: "berawan", 3: "mendung", 45: "berkabus", 48: "berkabus",
    51: "gerimis", 53: "gerimis", 55: "gerimis lebat", 61: "hujan renyai", 63: "hujan", 65: "hujan lebat",
    80: "hujan sekejap-sekejap", 81: "hujan", 82: "hujan lebat", 95: "ribut petir", 96: "ribut petir", 99: "ribut petir kuat",
}


def weather(lat, lon):
    """Cuaca semasa + ramalan hari ini. Cache 10 minit."""
    c = cache_get("weather")
    if c and c.get("at", 0) > time.time() - 600 and c.get("pos") == [lat, lon]:
        return c["data"]
    d = _get_json(
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&hourly=precipitation_probability&forecast_hours=12&timezone=Asia%2FKuala_Lumpur&forecast_days=1", 20)
    cur, day = d["current"], d["daily"]
    hours = d.get("hourly", {})
    rain_hours = [t[-5:] for t, p in zip(hours.get("time", []), hours.get("precipitation_probability", [])) if p and p >= 60]
    data = {
        "temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
        "humidity": cur["relative_humidity_2m"], "desc": WEATHER_CODES.get(cur["weather_code"], "berawan"),
        "max": round(day["temperature_2m_max"][0]), "min": round(day["temperature_2m_min"][0]),
        "rain_chance": day["precipitation_probability_max"][0], "rain_from": rain_hours[0] if rain_hours else None,
    }
    cache_set("weather", {"at": time.time(), "pos": [lat, lon], "data": data})
    return data


def weather_text(w):
    rain = f", peluang hujan {w['rain_chance']}%" + (f" (mungkin mula sekitar {w['rain_from']})" if w["rain_from"] else "")
    return (f"Sekarang {w['temp']}°C (terasa {w['feels']}°C), {w['desc']}, kelembapan {w['humidity']}%. "
            f"Hari ini {w['min']}–{w['max']}°C{rain}.")


# ---------- Waktu solat (JAKIM e-Solat) ----------
PRAYERS = [("fajr", "Subuh"), ("syuruk", "Syuruk"), ("dhuhr", "Zohor"), ("asr", "Asar"), ("maghrib", "Maghrib"), ("isha", "Isyak")]


def _fetch_prayer_month(zone):
    d = _get_json(f"https://www.e-solat.gov.my/index.php?r=esolatApi/TakwimSolat&period=month&zone={zone}", 300)
    days = {}
    for p in d.get("prayerTime", []):
        dt = datetime.strptime(p["date"], "%d-%b-%Y").strftime("%Y-%m-%d")
        days[dt] = {k: p[k][:5] for k, _ in PRAYERS if p.get(k)}
    return days


def prayer_today(zone, refresh_async=True):
    """Waktu solat hari ini dari cache bulanan. Server JAKIM lambat, jadi ambil sebulan sekali di latar."""
    today = datetime.now().strftime("%Y-%m-%d")
    c = cache_get("prayer") or {}
    if c.get("zone") == zone and today in c.get("days", {}):
        return c["days"][today]
    if refresh_async:
        refresh_prayer_cache(zone)
    return None


_prayer_fetching = threading.Event()


def refresh_prayer_cache(zone):
    if _prayer_fetching.is_set():
        return
    _prayer_fetching.set()

    def work():
        try:
            days = _fetch_prayer_month(zone)
            if days:
                cache_set("prayer", {"zone": zone, "days": days, "at": time.time()})
        except Exception:
            pass
        finally:
            _prayer_fetching.clear()
    threading.Thread(target=work, daemon=True).start()


def next_prayer(times):
    """(nama, 'HH:MM', minit_lagi) untuk waktu solat seterusnya hari ini."""
    if not times:
        return None
    now = datetime.now()
    for key, name in PRAYERS:
        if key == "syuruk" or key not in times:
            continue
        t = datetime.combine(now.date(), datetime.strptime(times[key], "%H:%M").time())
        if t > now:
            return name, times[key], int((t - now).total_seconds() // 60)
    return None


def prayer_text(times, zone):
    if not times:
        return "Waktu solat belum dapat (server JAKIM lambat, tengah cuba ambil di latar)."
    parts = ", ".join(f"{name} {times[k]}" for k, name in PRAYERS if k in times)
    nxt = next_prayer(times)
    tail = f" Seterusnya {nxt[0]} pukul {nxt[1]} ({nxt[2]} minit lagi)." if nxt else " Semua waktu hari ini dah lepas."
    return f"Waktu solat hari ini (zon {zone}): {parts}.{tail}"


# ---------- Kawalan laptop melalui kekunci ----------
VK = {"right": 0x27, "left": 0x25, "f5": 0x74, "esc": 0x1B, "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD,
      "play": 0xB3, "next_track": 0xB0, "prev_track": 0xB1, "pgdn": 0x22, "pgup": 0x21, "win": 0x5B,
      "d": 0x44, "alt": 0x12, "tab": 0x09, "shift": 0x10, "s": 0x53, "b": 0x42, "w": 0x57}
_u32 = ctypes.windll.user32


def _tap(*keys, repeat=1):
    for _ in range(repeat):
        for k in keys:
            _u32.keybd_event(VK[k], 0, 0, 0)
        for k in reversed(keys):
            _u32.keybd_event(VK[k], 0, 2, 0)  # KEYEVENTF_KEYUP
        time.sleep(0.03)


# action -> (label, kekunci, ulang, perlu tetingkap lain di depan)
ACTIONS = {
    "next_slide": ("Next slide", ("right",), 1, True),
    "prev_slide": ("Previous slide", ("left",), 1, True),
    "start_show": ("Start slideshow", ("f5",), 1, True),
    "end_show": ("End slideshow", ("esc",), 1, True),
    "black_screen": ("Black screen", ("b",), 1, True),
    "vol_up": ("Volume up", ("vol_up",), 5, False),
    "vol_down": ("Volume down", ("vol_down",), 5, False),
    "mute": ("Mute / unmute", ("mute",), 1, False),
    "play_pause": ("Play / pause", ("play",), 1, False),
    "next_track": ("Next track", ("next_track",), 1, False),
    "prev_track": ("Previous track", ("prev_track",), 1, False),
    "scroll_down": ("Scroll down", ("pgdn",), 1, True),
    "scroll_up": ("Scroll up", ("pgup",), 1, True),
    "show_desktop": ("Show desktop", ("win", "d"), 1, False),
    "switch_window": ("Switch window", ("alt", "tab"), 1, False),
    "snip": ("Screenshot tool", ("win", "shift", "s"), 1, False),
}

# Arahan pantas (tanpa AI). Susunan penting: yang spesifik dulu.
_W = r"(?:^|\b)"
QUICK = [
    (r"\b(tamat|stop|habis|tutup|end|keluar|berhenti)\b.*\b(slide ?show|slides?|present\w*|pembentangan)\b", "end_show"),
    (r"\b(mula|start|mulakan|play|tayang)\b.*\b(slide ?show|slides?|present\w*|pembentangan)\b", "start_show"),
    (r"\b(next|seterusnya|depan|hadapan|lepas)\b.*\bslides?\b|\bslides?\b.*\b(next|seterusnya|depan|hadapan|lepas)\b|^(next|seterusnya)$", "next_slide"),
    (r"\b(previous|prev|sebelum|belakang|balik|back|tadi)\b.*\bslides?\b|\bslides?\b.*\b(previous|prev|sebelum|sebelumnya|belakang|balik|back|tadi)\b|^(back|previous|sebelum)$", "prev_slide"),
    (r"\b(gelapkan|black)\b.*\b(skrin|screen)\b", "black_screen"),
    (r"\b(volume|bunyi|suara)\b.*\b(naik|up|kuat|besar|tinggi)\b|\b(kuatkan|besarkan) (bunyi|suara|volume)\b|\bvolume up\b", "vol_up"),
    (r"\b(volume|bunyi|suara)\b.*\b(turun|down|perlahan|kecil|rendah)\b|\b(perlahankan|kecilkan) (bunyi|suara|volume)\b|\bvolume down\b", "vol_down"),
    (r"^(mute|unmute)$|\b(mute|unmute)\b.*\b(bunyi|sound|audio|laptop)?\b$|\bsenyapkan bunyi\b", "mute"),
    (r"\b(lagu|track|song|muzik|music)\b.*\b(next|seterusnya|lepas)\b|\b(next|seterusnya)\b.*\b(lagu|track|song)\b", "next_track"),
    (r"\b(lagu|track|song|muzik|music)\b.*\b(previous|sebelum|balik)\b|\b(previous|sebelum)\b.*\b(lagu|track|song)\b", "prev_track"),
    (r"^(pause|play|resume)( (lagu|muzik|music|video))?$|\b(pause|sambung|hentikan) (lagu|muzik|music|video)\b", "play_pause"),
    (r"\bscroll\b.*\b(down|bawah|turun)\b|^(turun|ke) bawah$", "scroll_down"),
    (r"\bscroll\b.*\b(up|atas|naik)\b|^(naik|ke) atas$", "scroll_up"),
    (r"\b(tunjuk|show|pergi)\b.*\bdesktop\b|\bminimi[sz]e (semua|all)\b", "show_desktop"),
    (r"\b(tukar|switch)\b.*\b(window|tingkap|app)\b|\balt ?tab\b", "switch_window"),
    (r"\b(snip|tangkap skrin|screenshot tool)\b", "snip"),
]


def clean_command(text):
    t = text.lower().strip()
    # "Hey Jarvis" & salah dengar biasa: hijabis, hey jervis, hai javis, janvis...
    t = re.sub(r"^(okay |ok |eh |weh )?(((hey|hei|hai|hi|ei|a) ?)?(jarvis|jervis|javis|janvis|jarvi|jabis|jarbis)|hijabis|hijarvis|hijervis)[,.!?\s]*", "", t)
    t = re.sub(r"^(tolong|please|boleh tak|cuba)\s+", "", t)
    return re.sub(r"[.!?]+$", "", t).strip()


# Frasa kawalan pendek: dipadankan secara kabur bila pengecaman suara tersilap sikit ("next life" -> "next slide")
CONTROL_PHRASES = {
    "next slide": "next_slide", "slide seterusnya": "next_slide", "slide depan": "next_slide",
    "previous slide": "prev_slide", "slide sebelum": "prev_slide", "slide belakang": "prev_slide",
    "volume naik": "vol_up", "volume turun": "vol_down", "mute": "mute",
    "mula slideshow": "start_show", "tamat slide": "end_show", "pause lagu": "play_pause", "next lagu": "next_track",
}


def fuzzy_control(text):
    """Pulangkan frasa kawalan terdekat jika ayat pendek hampir sama (nisbah >= 0.75)."""
    import difflib
    t = clean_command(text)
    if not t or len(t.split()) > 4:
        return None
    best = max(CONTROL_PHRASES, key=lambda p: difflib.SequenceMatcher(None, t, p).ratio())
    return best if difflib.SequenceMatcher(None, t, best).ratio() >= 0.75 else None


def match_control(text):
    t = clean_command(text)
    for pattern, action in QUICK:
        if re.search(pattern, t):
            return action
    return None


def _jarvis_hwnd():
    return _u32.FindWindowW(None, "Jarvis")


def jarvis_in_front():
    h = _jarvis_hwnd()
    return bool(h) and _u32.GetForegroundWindow() == h


def hide_jarvis_if_front():
    """Kekunci slide/scroll mesti sampai ke app lain, bukan Jarvis."""
    if jarvis_in_front():
        _u32.ShowWindow(_jarvis_hwnd(), 6)  # SW_MINIMIZE
        time.sleep(0.35)
        return True
    return False


def do_control(action):
    if action not in ACTIONS:
        return None
    label, keys, repeat, needs_other_app = ACTIONS[action]
    if needs_other_app:
        hide_jarvis_if_front()
    _tap(*keys, repeat=repeat)
    return label


def beep(kind="ok"):
    try:
        import winsound
        if kind == "wake":
            winsound.Beep(880, 70); winsound.Beep(1320, 90)
        else:
            winsound.Beep(1250, 45)
    except Exception:
        pass


# ---------- Teks untuk suara: sebutan lebih natural ----------
# Perkataan English yang biasa dicampur dalam BM gaya KL. Suara BM sebut ikut loghat Melayu baku,
# jadi untuk Google kita tandakan sebagai en-US (SSML <lang>) supaya bunyi macam orang KL cakap.
EN_WORDS = set("""
okay ok settle check checking file files folder update updated download upload install uninstall website web link online offline
email emel laptop phone app apps system data project server backup ready standby sorry thanks bro chat code coding error bug fix
meeting deadline slide slides screen screenshot mouse keyboard wifi bluetooth battery charge charger storage memory cache browser
chrome google drive excel word powerpoint report dashboard power mode setting settings login password user admin account upgrade
delete copy paste save print scan video audio music play pause next previous live status dot com at slash www jarvis claude deepseek
minimax github node python javascript database frontend backend deploy run test version feature team task tab window windows
desktop downloads documents cloud sync weekend online booking order seller platform sales target trending viral content
""".split())

_ACRONYM = re.compile(r"^[A-Z]{2,5}s?$")


def speech_normalize(text, lang="ms"):
    """Tukar simbol, URL, email dan nombor supaya dibaca dengan natural (BM atau English)."""
    t = text
    t = re.sub(r"https?://", "", t)
    t = re.sub(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)", lambda m: m.group(1).replace(".", " dot ") + " at " + m.group(2).replace(".", " dot "), t)
    # domain & nama fail: akmalsys.com, sipeng.md, laporan.pdf
    t = re.sub(r"\b([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)\.(com|my|net|org|edu|gov|io|ai|app|dev|co|md|pdf|docx?|xlsx?|pptx?|txt|csv|json|js|py|html|png|jpe?g|mp4|zip|exe|bat)\b",
               lambda m: m.group(1).replace(".", " dot ") + " dot " + m.group(2), t, flags=re.I)
    t = re.sub(r"(?<=\w)/(?=\w)", " slash ", t)
    t = re.sub(r"\bRM\s?(\d[\d,]*(?:\.\d+)?)", lambda m: m.group(1) + (" ringgit" if lang == "ms" else " ringgit"), t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)            # 102,431 -> 102431
    t = re.sub(r"(\d)\s?%", r"\1 peratus" if lang == "ms" else r"\1 percent", t)
    t = re.sub(r"(\d)\s?°\s?C\b", r"\1 darjah" if lang == "ms" else r"\1 degrees", t)
    t = t.replace("&", " dan " if lang == "ms" else " and ").replace("→", ", ").replace("—", ", ").replace("–", ", ")
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)  # emoji
    return re.sub(r"\s{2,}", " ", t).strip()


def to_ssml(text):
    """SSML Google: perkataan English & akronim (CPU, PDF, AI) disebut dalam en-US."""
    from xml.sax.saxutils import escape
    out = []
    for tok in re.split(r"(\s+|[,.!?;:()\"'])", text):
        if not tok:
            continue
        core = tok.strip()
        if core and (core.lower() in EN_WORDS or _ACRONYM.match(core)):
            out.append(f'<lang xml:lang="en-US">{escape(tok)}</lang>')
        else:
            out.append(escape(tok))
    ssml = "".join(out).replace('</lang> <lang xml:lang="en-US">', " ")   # gabung perkataan English berturut
    return f"<speak>{ssml}</speak>"


# ---------- Tangkap skrin ----------
def screenshot(path):
    """Tangkap skrin tanpa Jarvis di depan, simpan PNG (maks 1600px lebar)."""
    from PIL import ImageGrab
    hidden = hide_jarvis_if_front()
    if hidden:
        time.sleep(0.4)
    img = ImageGrab.grab(all_screens=True)
    if img.width > 1600:
        img = img.resize((1600, int(img.height * 1600 / img.width)))
    img.save(path)
    if hidden:
        _u32.ShowWindow(_jarvis_hwnd(), 9)  # SW_RESTORE
    return path
