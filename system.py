"""Kawalan laptop: satu pintu masuk, tiga tingkat kuasa.

Kenapa fail ini wujud berasingan daripada services.py:
services.py cuma menekan kekunci media (VK_VOLUME_UP dan seumpamanya). Itu
cukup untuk "next slide" tetapi tidak boleh menjawab "volume 30", "brightness
kurangkan separuh", "tutup Chrome", "apa tetingkap yang terbuka". Semua itu
perlukan bacaan keadaan sebenar, bukan buta tekan.

Tiga tingkat, dan tingkat menentukan sama ada kita tanya dulu:

    baca      tiada kesan. Terus jawab. Contoh: volume berapa, senarai tetingkap.
    ubah      kesan serta-merta tetapi Akmal boleh pusing balik dalam satu saat.
              Terus buat. Contoh: volume 40, brightness 70, fokus tetingkap.
    pukal     susah diundur — proses mati, fail masuk recycle bin, laptop tutup.
              Ditahan di sebalik token pengesahan yang luput dalam 90 saat.
              Pemanggil kena hantar token tu balik sebelum ia jalan.

Setiap kaedah pulangkan dict yang sama bentuknya:
    {"ok": bool, "msg": str, ...}
Kalau tindakan perlu pengesahan:
    {"ok": False, "need_confirm": True, "token": "...", "ask": "..."}
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import secrets
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_ole32 = ctypes.windll.ole32
_shell32 = ctypes.windll.shell32

NO_WINDOW = 0x08000000

# Tingkat kesan. Dipakai oleh main.py untuk memutuskan paparan di HUD dan
# oleh _needs_confirm() di bawah.
READ, SOFT, HARD = "baca", "ubah", "pukal"

CONFIRM_TTL = 90.0  # saat


# ─────────────────────────── audio (COM, tanpa dependency) ───────────────────────────
# pycaw tiada dalam senarai pakej, jadi IAudioEndpointVolume dipanggil terus.
# Vtable yang dipakai, disahkan dengan probe pada mesin ini:
#   7  SetMasterVolumeLevelScalar(float, ctx)
#   9  GetMasterVolumeLevelScalar(float*)
#   14 SetMute(BOOL, ctx)      15 GetMute(BOOL*)
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    g = _GUID()
    _ole32.CLSIDFromString(ctypes.c_wchar_p("{%s}" % text), ctypes.byref(g))
    return g


_CLSID_MMDEVICE_ENUM = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_IMMDEVICE_ENUM = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
_IID_IAUDIO_ENDPOINT = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")

_audio_ready = None  # None = belum cuba, False = tiada peranti, objek = hidup


def _vtbl(ptr, index, restype, *argtypes):
    table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def _audio():
    """Pulangkan IAudioEndpointVolume atau None. Disimpan, bukan dicipta semula setiap panggilan."""
    global _audio_ready
    if _audio_ready is not None:
        return _audio_ready or None
    try:
        _ole32.CoInitializeEx(None, 2)  # STA
        enum = ctypes.c_void_p()
        hr = _ole32.CoCreateInstance(ctypes.byref(_CLSID_MMDEVICE_ENUM), None, 1,
                                     ctypes.byref(_IID_IMMDEVICE_ENUM), ctypes.byref(enum))
        if hr != 0 or not enum.value:
            _audio_ready = False
            return None
        dev = ctypes.c_void_p()
        hr = _vtbl(enum, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int,
                   ctypes.POINTER(ctypes.c_void_p))(enum, 0, 1, ctypes.byref(dev))
        if hr != 0 or not dev.value:
            _audio_ready = False
            return None
        endp = ctypes.c_void_p()
        hr = _vtbl(dev, 3, ctypes.c_long, ctypes.POINTER(_GUID), ctypes.c_ulong,
                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            dev, ctypes.byref(_IID_IAUDIO_ENDPOINT), 0, None, ctypes.byref(endp))
        if hr != 0 or not endp.value:
            _audio_ready = False
            return None
        _audio_ready = endp
        return endp
    except Exception:
        _audio_ready = False
        return None


def volume_get():
    ep = _audio()
    if ep is None:
        return None
    f = ctypes.c_float()
    if _vtbl(ep, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float))(ep, ctypes.byref(f)) != 0:
        return None
    return round(f.value * 100)


def volume_set(pct):
    ep = _audio()
    if ep is None:
        return False
    pct = max(0, min(100, int(pct)))
    return _vtbl(ep, 7, ctypes.c_long, ctypes.c_float, ctypes.c_void_p)(
        ep, ctypes.c_float(pct / 100.0), None) == 0


def mute_get():
    ep = _audio()
    if ep is None:
        return None
    b = wt.BOOL()
    if _vtbl(ep, 15, ctypes.c_long, ctypes.POINTER(wt.BOOL))(ep, ctypes.byref(b)) != 0:
        return None
    return bool(b.value)


def mute_set(on):
    ep = _audio()
    if ep is None:
        return False
    return _vtbl(ep, 14, ctypes.c_long, wt.BOOL, ctypes.c_void_p)(
        ep, wt.BOOL(1 if on else 0), None) == 0


# ─────────────────────────── kecerahan (WMI melalui pythonnet) ───────────────────────────
# Hanya panel dalaman yang menyokong WmiMonitorBrightness. Monitor luar melalui
# HDMI/DisplayPort tidak — DDC/CI perlukan jalan lain, jadi kita pulangkan None
# dan pemanggil cakap terus "monitor ni tak sokong" daripada menipu.
def _wmi():
    import clr  # pythonnet; sudah ada dalam env
    clr.AddReference("System.Management")
    from System.Management import (ManagementClass, ManagementObjectSearcher,
                                   ManagementPath, ManagementScope, ObjectGetOptions)
    return ManagementClass, ManagementObjectSearcher, ManagementPath, ManagementScope, ObjectGetOptions


def brightness_get():
    try:
        _, Searcher, *_ = _wmi()
        q = Searcher(r"root\WMI", "SELECT CurrentBrightness FROM WmiMonitorBrightness")
        vals = [int(o["CurrentBrightness"]) for o in q.Get()]
        return vals[0] if vals else None
    except Exception:
        return None


def brightness_set(pct):
    try:
        cls, _, MPath, MSc, Opts = _wmi()
        scope = MSc(r"root\WMI")
        mc = cls(scope, MPath("WmiMonitorBrightnessMethods"), Opts())
        insts = list(mc.GetInstances())
        if not insts:
            return False
        insts[0].InvokeMethod("WmiSetBrightness", [1, max(0, min(100, int(pct)))])
        return True
    except Exception:
        return False


# ─────────────────────────── tetingkap ───────────────────────────
_SKIP_TITLES = {"", "Program Manager", "Windows Input Experience", "Jarvis"}

_EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def list_windows(limit=40):
    """Tetingkap kelihatan yang ada tajuk, paling depan dahulu."""
    out = []
    fg = _u32.GetForegroundWindow()

    def _cb(hwnd, _):
        if not _u32.IsWindowVisible(hwnd):
            return True
        n = _u32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        _u32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if title in _SKIP_TITLES or title.startswith("Default IME"):
            return True
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append({"hwnd": int(hwnd), "title": title, "pid": int(pid.value),
                    "front": int(hwnd) == fg, "min": bool(_u32.IsIconic(hwnd))})
        return len(out) < 400

    _u32.EnumWindows(_EnumProc(_cb), 0)
    # yang depan dulu, selebihnya ikut susunan z (EnumWindows sudah z-order)
    out.sort(key=lambda w: (not w["front"], w["min"]))
    return out[:limit]


def find_window(needle):
    """Padanan kabur: tepat dahulu, kemudian mengandung. Pulangkan hwnd atau None."""
    needle = (needle or "").strip().lower()
    if not needle:
        return None
    wins = list_windows(400)
    for w in wins:
        if w["title"].lower() == needle:
            return w["hwnd"]
    for w in wins:
        if needle in w["title"].lower():
            return w["hwnd"]
    return None


def focus_window(hwnd):
    if not hwnd or not _u32.IsWindow(hwnd):
        return False
    if _u32.IsIconic(hwnd):
        _u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # SetForegroundWindow gagal senyap bila proses pemanggil bukan foreground.
    # AttachThreadInput menutup jurang itu.
    fg = _u32.GetForegroundWindow()
    tid_fg = _u32.GetWindowThreadProcessId(fg, None)
    tid_me = _k32.GetCurrentThreadId()
    attached = False
    if tid_fg and tid_fg != tid_me:
        attached = bool(_u32.AttachThreadInput(tid_me, tid_fg, True))
    try:
        _u32.BringWindowToTop(hwnd)
        return bool(_u32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            _u32.AttachThreadInput(tid_me, tid_fg, False)


def minimize_window(hwnd):
    return bool(_u32.ShowWindow(hwnd, 6)) if hwnd else False  # SW_MINIMIZE


def maximize_window(hwnd):
    return bool(_u32.ShowWindow(hwnd, 3)) if hwnd else False  # SW_MAXIMIZE


def close_window(hwnd):
    """WM_CLOSE, bukan TerminateProcess — app masih boleh tanya 'simpan?'."""
    return bool(_u32.PostMessageW(hwnd, 0x0010, 0, 0)) if hwnd else False


def window_of_pid(pid):
    for w in list_windows(400):
        if w["pid"] == int(pid):
            return w["hwnd"]
    return None


# ─────────────────────────── embed tetingkap lain ke dalam stage ───────────────────────────
# SetParent + SetWindowPos, bukan tangkapan skrin. Tetingkap asal terus hidup —
# app yang di-embed masih boleh main video, masih boleh skrol — cuma ibunya
# ditukar kepada tetingkap HUD dan saiznya diikat pada rect stage.
#
# Tiga perkara yang mesti betul atau ia rosak dengan cara yang menyakitkan:
#   1. Gaya asal disimpan dan dipulihkan. WS_CHILD yang tertinggal pada tetingkap
#      Akmal bermakna app itu hilang dari taskbar selama-lamanya.
#   2. Ibu asal disimpan. Tanpa itu app tidak kembali ke desktop.
#   3. SW_HIDE bila tukar panel. Tetingkap anak duduk ATAS WebView2, jadi kalau
#      tidak disembunyikan ia terapung di atas panel lain.
_GWL_STYLE = -16
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_SWP_FRAMECHANGED = 0x0020

_u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
_u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
_u32.SetParent.argtypes = [wt.HWND, wt.HWND]
_u32.SetParent.restype = wt.HWND
_u32.GetParent.argtypes = [wt.HWND]
_u32.GetParent.restype = wt.HWND
_u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wt.UINT]
_u32.SetWindowPos.restype = wt.BOOL
_u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
_u32.GetWindowRect.restype = wt.BOOL
_u32.GetDpiForWindow.argtypes = [wt.HWND]
_u32.GetDpiForWindow.restype = wt.UINT
_u32.MoveWindow.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.BOOL]


class Embed:
    """Satu tetingkap pada satu masa. Dua serentak akan bertindih dan tak boleh dipulihkan."""

    def __init__(self):
        self.hwnd = None
        self.origin = None   # (parent, style, rect) sebelum diambil alih
        self.title = ""
        self.visible = True

    def attach(self, parent_hwnd, title):
        if self.hwnd and self.hwnd != find_window(title):
            self.detach()
        hwnd = find_window(title)
        if not hwnd:
            return False, "Tak jumpa tetingkap '%s'." % title
        if int(hwnd) == int(parent_hwnd):
            return False, "Itu tetingkap Jarvis sendiri."
        if self.hwnd == hwnd and self.origin:
            return True, "Dah terlepas."   # sudah di-embed, cuma reposisi
        rect = wt.RECT()
        _u32.GetWindowRect(hwnd, ctypes.byref(rect))
        style = _u32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
        self.origin = (_u32.GetParent(hwnd), style, (rect.left, rect.top,
                                                     rect.right - rect.left, rect.bottom - rect.top))
        self.hwnd, self.title, self.visible = hwnd, title, True
        _u32.SetWindowLongPtrW(hwnd, _GWL_STYLE, (style & ~_WS_POPUP) | _WS_CHILD)
        _u32.SetParent(hwnd, parent_hwnd)
        return True, "Dah masuk stage."

    def place(self, x, y, w, h, scale=1.0):
        """x,y,w,h dalam CSS px relatif kepada kawasan klien HUD.

        SetWindowPos pada tetingkap anak mengambil koordinat relatif kepada
        kawasan klien ibu, dan getBoundingClientRect() dalam JS juga relatif
        kepada viewport — jadi kedua-duanya sepadan tanpa pembetulan. Yang
        perlu ditukar hanya unit: SetWindowPos mahu piksel fizikal, JS memberi
        piksel CSS. Pada skrin 150% perbezaannya 1.5×, dan tanpanya app
        tersangkut di suku atas stage.
        """
        if not self.hwnd:
            return False
        s = float(scale or 1.0)
        _u32.SetWindowPos(self.hwnd, None, int(x * s), int(y * s), int(w * s), int(h * s),
                          _SWP_NOACTIVATE | _SWP_SHOWWINDOW | _SWP_FRAMECHANGED)
        self.visible = True
        return True

    def show(self, on):
        if not self.hwnd:
            return False
        _u32.ShowWindow(self.hwnd, 5 if on else 0)  # SW_SHOWNOACTIVATE : SW_HIDE
        self.visible = bool(on)
        return True

    def detach(self):
        if not self.hwnd or not self.origin:
            return False
        parent, style, rect = self.origin
        _u32.SetParent(self.hwnd, parent)
        _u32.SetWindowLongPtrW(self.hwnd, _GWL_STYLE, style)
        _u32.SetWindowPos(self.hwnd, None, rect[0], rect[1], rect[2], rect[3],
                          _SWP_NOACTIVATE | _SWP_SHOWWINDOW | _SWP_FRAMECHANGED)
        self.hwnd, self.origin, self.title = None, None, ""
        return True


def dpi_scale(hwnd):
    """CSS px -> fizikal px. HUD fullscreen pada 125% akan lapor 120 dpi = 1.25."""
    try:
        return (_u32.GetDpiForWindow(hwnd) or 96) / 96.0
    except Exception:
        return 1.0


def is_window(hwnd):
    """Benar kalau pemegang masih menunjuk tetingkap yang hidup."""
    try:
        return bool(hwnd) and bool(_u32.IsWindow(int(hwnd)))
    except Exception:
        return False


def hud_hwnd(title="Jarvis"):
    return _u32.FindWindowW(None, title)


def app_hwnd(title):
    """HWND mengikut tajuk — untuk tetingkap APP biasa, bukan tetingkap pywebview.

    Amaran yang diukur, bukan diandaikan: satu tetingkap pywebview (HUD atau
    tetingkap web anak) menghasilkan puluhan HWND peringkat atas dengan tajuk
    yang sama, semuanya kelas WindowsForms10.Window, semuanya tanpa ibu,
    semuanya IsWindowVisible = True, dan semuanya pada rect yang sama. Tiada
    satu pun daripada ujian itu membezakan bingkai daripada anak — jadi fungsi
    ini akan memulangkan yang pertama ditemui, bukan yang betul.

    Untuk tetingkap pywebview, jangan guna fungsi ini. Guna pemegang Python:
    `win.native.Handle` (Api._web_hwnd() membalutnya). Ia tepat kerana ia
    menunjuk objek Form itu sendiri, bukan gelintar tajuk.

    Fungsi ini masih berguna untuk app yang di-embed ke panel NATIVE — Notepad,
    Calculator, VS Code — kerana app biasa tidak mempunyai anak bernama sama.
    """
    want = (title or "").strip().lower()
    if not want:
        return None
    for w in list_windows(400):
        t = w["title"].strip().lower()
        if t == want or (want in t and len(t) - len(want) < 6):
            return w["hwnd"]
    return None


# ─────────────────────────── clipboard ───────────────────────────
# GlobalAlloc/GlobalLock pulangkan HANDLE dan LPVOID. Tanpa restype yang
# betul, ctypes andaikan int 32-bit dan pointer dipotong — itu yang buat
# tulis clipboard meletup dengan access violation pada alamat 0x0.
_CF_UNICODETEXT = 13

_u32.OpenClipboard.argtypes = [wt.HWND]
_u32.OpenClipboard.restype = wt.BOOL
_u32.CloseClipboard.restype = wt.BOOL
_u32.GetClipboardData.argtypes = [wt.UINT]
_u32.GetClipboardData.restype = wt.HANDLE
_u32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
_u32.SetClipboardData.restype = wt.HANDLE
_u32.EmptyClipboard.restype = wt.BOOL
_k32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
_k32.GlobalAlloc.restype = wt.HGLOBAL
_k32.GlobalLock.argtypes = [wt.HGLOBAL]
_k32.GlobalLock.restype = ctypes.c_void_p
_k32.GlobalUnlock.argtypes = [wt.HGLOBAL]
_k32.GlobalUnlock.restype = wt.BOOL


def clipboard_get():
    if not _u32.OpenClipboard(None):
        return ""
    try:
        h = _u32.GetClipboardData(_CF_UNICODETEXT)
        if not h:
            return ""
        ptr = _k32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            _k32.GlobalUnlock(h)
    finally:
        _u32.CloseClipboard()


def clipboard_set(text):
    text = str(text)
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _u32.OpenClipboard(None):
        return False
    try:
        _u32.EmptyClipboard()
        h = _k32.GlobalAlloc(0x0042, size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
        if not h:
            return False
        ptr = _k32.GlobalLock(h)
        if not ptr:
            return False
        ctypes.memmove(ptr, data, size)
        _k32.GlobalUnlock(h)
        return bool(_u32.SetClipboardData(_CF_UNICODETEXT, h))
    finally:
        _u32.CloseClipboard()


# ─────────────────────────── proses & app ───────────────────────────
def list_processes(limit=60):
    import psutil
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = p.info
            name = info.get("name") or ""
            if not name:
                continue
            rss = info.get("memory_info").rss if info.get("memory_info") else 0
            procs.append({"pid": info["pid"], "name": name, "mb": round(rss / 1048576)})
        except Exception:
            continue
    procs.sort(key=lambda x: -x["mb"])
    return procs[:limit]


def kill_process(needle):
    """Bunuh ikut nama. Pulangkan (bilangan, nama-nama)."""
    import psutil
    needle = (needle or "").strip().lower().replace(".exe", "")
    if not needle:
        return 0, []
    hits, names = 0, []
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info.get("name") or "").lower()
            if not name or name.replace(".exe", "") != needle:
                continue
            if p.info["pid"] in (me, 0):
                continue
            p.terminate()
            hits += 1
            names.append(p.info["name"])
        except Exception:
            continue
    return hits, names


# ─────────────────────────── shell ───────────────────────────
# Senarai putih, bukan senarai hitam. Arahan yang tidak tersenarai tidak jalan
# langsung, walaupun model yakin ia selamat — senarai hitam sentiasa ketinggalan
# satu langkah daripada seseorang yang kreatif.
SHELL_ALLOW = [
    r"^ipconfig( /all)?$", r"^ipconfig /flushdns$", r"^systeminfo$", r"^hostname$", r"^whoami$",
    r"^dir( [\w\\.:/ *-]+)?$", r"^tasklist$", r"^tasklist /v$", r"^ping [\w.\-]+$",
    r"^ping -n \d+ [\w.\-]+$", r"^tracert [\w.\-]+$", r"^nslookup [\w.\-]+$",
    r"^netsh wlan show (interfaces|profiles|profile name=[\w \-]+ key=clear)$",
    r"^netsh interface show interface$", r"^netsh int ip show config$",
    r"^powercfg /?batteryreport( /output [\w\\.:/ -]+)?$", r"^ver$", r"^vol$",
    r"^wmic (cpu get name,numberofcores,numberoflogicalprocessors|memorychip get capacity,speed)$",
    r"^get-[a-z]+( -[a-z]+)*$",  # PowerShell cmdlet baca sahaja
]


def shell_allowed(cmd):
    import re
    cmd = (cmd or "").strip()
    if not cmd or len(cmd) > 300:
        return False
    # tolak chaining dan redirection sebelum padan — kalau tidak `ipconfig && del x` lulus
    if any(t in cmd for t in ("&&", "||", ";", "|", ">", "<", "`", "$(", "&")):
        return False
    return any(re.match(p, cmd, re.I) for p in SHELL_ALLOW)


def shell_run(cmd, timeout=25):
    if not shell_allowed(cmd):
        return False, "Arahan itu tiada dalam senarai putih."
    exe = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd] if cmd.lower().startswith("get-") \
        else ["cmd", "/c", cmd]
    try:
        r = subprocess.run(exe, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        out = (r.stdout or b"").decode("utf-8", "replace") or (r.stderr or b"").decode("utf-8", "replace")
        return True, out.strip()[:4000]
    except subprocess.TimeoutExpired:
        return False, "Arahan ambil masa terlalu lama."
    except Exception as e:
        return False, str(e)


# ─────────────────────────── kad kuasa ───────────────────────────
def lock_workstation():
    return bool(_u32.LockWorkStation())


def sleep_pc():
    # SetSuspendState(hibernate=False, force=False, disableWakeEvent=False)
    return bool(ctypes.windll.powrprof.SetSuspendState(0, 0, 0))


def power_action(action):
    cmd = {"shutdown": ["shutdown", "/s", "/t", "20"],
           "restart": ["shutdown", "/r", "/t", "20"],
           "cancel": ["shutdown", "/a"],
           "logoff": ["shutdown", "/l"]}.get(action)
    if not cmd:
        return False, "Aksi kuasa tak dikenali."
    if action in ("shutdown", "restart"):
        cmd = cmd[:4]  # 20 saat, cukup untuk Akmal batalkan kalau tersilap
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15, creationflags=NO_WINDOW)
        ok = r.returncode == 0
        msg = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip()
        if ok and action in ("shutdown", "restart"):
            msg = "Laptop akan %s dalam 20 saat. Cakap 'batal' untuk stop." % (
                "tutup" if action == "shutdown" else "restart")
        return ok, msg
    except Exception as e:
        return False, str(e)


def recycle_paths(paths):
    """Buang ke Recycle Bin, bukan padam kekal. Pulangkan (bilangan, mesej)."""
    from ctypes import wintypes as w
    # SHFileOperationW dengan FOF_ALLOWUNDO: fail masih boleh dipulihkan Akmal
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", w.HWND), ("wFunc", w.UINT), ("pFrom", w.LPCWSTR),
                    ("pTo", w.LPCWSTR), ("fFlags", w.USHORT), ("fAnyOperationsAborted", w.BOOL),
                    ("hNameMappings", w.LPVOID), ("lpszProgressTitle", w.LPCWSTR)]

    good = [str(p) for p in paths if Path(p).exists()]
    if not good:
        return 0, "Tiada fail yang wujud."
    src = "\0".join(good) + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3            # FO_DELETE
    op.pFrom = src
    op.fFlags = 0x0040 | 0x0010 | 0x0004  # ALLOWUNDO | NOCONFIRMATION | SILENT
    rc = _shell32.SHFileOperationW(ctypes.byref(op))
    return (len(good), "Dah masuk Recycle Bin.") if rc == 0 else (0, "Gagal (kod %d)." % rc)


# ─────────────────────────── pemetaan arahan ───────────────────────────
# Satu jadual, supaya main.py dan model LLM melihat set yang sama. 'kind'
# menentukan sama ada pengesahan diperlukan, bukan nama tindakan.
def parse_pct(text, default=None):
    """Tarik nombor pertama dari ayat. 'volume 40' -> 40, 'naikkan 15' -> 15."""
    import re
    m = re.search(r"(\d{1,3})", str(text or ""))
    if not m:
        return default
    return max(0, min(100, int(m.group(1))))


def _resolve_app(name):
    """Cari app dalam shortcuts.json dahulu, kemudian PATH, kemudian Start Menu."""
    import json
    import shutil as sh
    name = (name or "").strip()
    if not name:
        return None
    low = name.lower()

    # 1. shortcuts.json — laluan yang Akmal sendiri dah tetapkan
    try:
        data = json.loads((ROOT / "shortcuts.json").read_text(encoding="utf-8"))
        for group in ("apps", "folders"):
            for item in data.get(group, []):
                if low in item.get("name", "").lower():
                    from main import resolve  # satu sumber kebenaran, bukan salinan
                    p = resolve(item)
                    if p is not None:
                        return p
    except Exception:
        pass

    # 2. PATH
    hit = sh.which(name) or sh.which(name + ".exe")
    if hit:
        return hit

    # 3. Start Menu — .lnk boleh dilancarkan terus oleh os.startfile
    roots = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.lnk"):
            if low in p.stem.lower():
                return p
    return None


def launch_app(name):
    target = _resolve_app(name)
    if target is None:
        return False, "Tak jumpa app \"%s\"." % name
    try:
        os.startfile(str(target))
        return True, Path(str(target)).stem
    except OSError:
        try:
            subprocess.Popen([str(target)], creationflags=NO_WINDOW, shell=False)
            return True, Path(str(target)).stem
        except Exception as e:
            return False, str(e)


def run_url(url):
    import webbrowser
    if not str(url).startswith(("http://", "https://")):
        url = "https://" + str(url)
    webbrowser.open(url)
    return True, url


def type_text(text):
    """Taip teks ke tetingkap depan. Untuk isi borang, bukan untuk main-main."""
    import ctypes as c
    text = str(text)
    if not text:
        return False
    # KEYEVENTF_UNICODE: hantar aksara terus, jadi layout papan kekunci tak kacau
    for ch in text:
        code = ord(ch)
        c.windll.user32.keybd_event(0, code, 0x0004, 0)
        c.windll.user32.keybd_event(0, code, 0x0004 | 0x0002, 0)
        time.sleep(0.004)
    return True


class System:
    """Satu instance per proses. Token pengesahan disimpan di sini."""

    def __init__(self):
        self._pending = {}  # token -> {"action": str, "args": dict, "until": float}
        self.embed = Embed()

    # ---------- token ----------
    def _mint(self, action, args, ask):
        tok = secrets.token_hex(4)
        self._pending[tok] = {"action": action, "args": args, "until": time.time() + CONFIRM_TTL}
        return {"ok": False, "need_confirm": True, "token": tok, "ask": ask,
                "msg": ask + " (confirm within %d s)" % int(CONFIRM_TTL)}

    def confirm(self, token):
        rec = self._pending.pop(token, None)
        if not rec:
            return {"ok": False, "msg": "Token is invalid or expired."}
        if time.time() > rec["until"]:
            return {"ok": False, "msg": "Token expired — ask again."}
        return self.do(rec["action"], _confirmed=True, **rec["args"])

    def cancel(self, token=None):
        if token:
            self._pending.pop(token, None)
        else:
            self._pending.clear()
        return {"ok": True, "msg": "Cancelled."}

    # ---------- kemasukan tunggal ----------
    def do(self, action, _confirmed=False, **kw):
        h = getattr(self, "_a_" + str(action or ""), None)
        if h is None:
            return {"ok": False, "msg": "Action \"%s\" not recognised." % action}
        kind = getattr(h, "kind", SOFT)
        if kind == HARD and not _confirmed:
            ask = getattr(h, "ask", "Tindakan ini susah diundur. Teruskan?")
            if callable(ask):
                ask = ask(**kw)
            return self._mint(action, kw, ask)
        try:
            return h(**kw)
        except TypeError as e:
            return {"ok": False, "msg": "Arguments do not match: %s" % e}
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def status(self):
        """Snapshot untuk HUD dan untuk model: satu panggilan, semua angka."""
        b = brightness_get()
        return {"ok": True, "volume": volume_get(), "mute": mute_get(),
                "brightness": b, "windows": len(list_windows(400)),
                "front": next((w["title"] for w in list_windows(5) if w["front"]), "")}

    # ═════════════ baca ═════════════
    def _a_status(self):
        s = self.status()
        b = "tak disokong monitor" if s["brightness"] is None else "%d%%" % s["brightness"]
        return {"ok": True, "msg": "Volume %s%%%s, brightness %s, %d windows, front: %s" % (
            s["volume"], " (mute)" if s["mute"] else "", b, s["windows"], s["front"] or "-"), **s}

    def _a_windows(self, limit=15):
        wins = list_windows(int(limit))
        return {"ok": True, "msg": "; ".join(w["title"][:60] for w in wins) or "No windows.",
                "windows": wins}

    def _a_processes(self, limit=15):
        ps = list_processes(int(limit))
        return {"ok": True, "msg": "; ".join("%s %dMB" % (p["name"], p["mb"]) for p in ps[:10]),
                "processes": ps}

    def _a_clip_read(self):
        t = clipboard_get()
        return {"ok": True, "text": t, "msg": (t[:300] + ("…" if len(t) > 300 else "")) or "Clipboard is empty."}

    def _a_shell(self, cmd=""):
        ok, out = shell_run(cmd)
        return {"ok": ok, "msg": out[:1500] if out else "(no output)", "full": out}

    # ═════════════ ubah ═════════════
    def _a_volume(self, level=None, delta=None):
        if delta is not None:
            cur = volume_get()
            if cur is None:
                return {"ok": False, "msg": "No audio device found."}
            level = cur + int(delta)
        if level is None:
            return {"ok": False, "msg": "Give a level 0-100 or a delta."}
        if not volume_set(level):
            return {"ok": False, "msg": "Could not set the volume."}
        if mute_get():
            mute_set(False)  # naikkan volume maksudnya Akmal nak dengar
        return {"ok": True, "msg": "Volume %d%%." % volume_get(), "volume": volume_get()}

    def _a_mute(self, on=None):
        if on is None:
            on = not (mute_get() or False)
        mute_set(bool(on))
        return {"ok": True, "msg": "Mute." if on else "Bunyi hidup balik.", "mute": bool(on)}

    def _a_brightness(self, level=None, delta=None):
        cur = brightness_get()
        if cur is None:
            return {"ok": False, "msg": "This monitor does not support brightness control (WMI)."}
        if delta is not None:
            level = cur + int(delta)
        if level is None:
            return {"ok": False, "msg": "Give a level 0-100 or a delta."}
        if not brightness_set(level):
            return {"ok": False, "msg": "Could not set the brightness."}
        time.sleep(0.25)  # WMI lambat sikit kemas kini nilainya
        return {"ok": True, "msg": "Kecerahan %d%%." % (brightness_get() or level),
                "brightness": brightness_get()}

    def _a_focus(self, title=""):
        hwnd = find_window(title)
        if not hwnd:
            return {"ok": False, "msg": "Window \"%s\" not found." % title}
        ok = focus_window(hwnd)
        return {"ok": ok, "msg": "Focused %s." % title if ok else "Windows refused focus."}

    def _a_minimize(self, title=""):
        hwnd = find_window(title) if title else _u32.GetForegroundWindow()
        if not hwnd:
            return {"ok": False, "msg": "Window not found."}
        minimize_window(hwnd)
        return {"ok": True, "msg": "Minimised."}

    def _a_maximize(self, title=""):
        hwnd = find_window(title) if title else _u32.GetForegroundWindow()
        if not hwnd:
            return {"ok": False, "msg": "Window not found."}
        maximize_window(hwnd)
        return {"ok": True, "msg": "Maximised."}

    def _a_launch(self, name=""):
        ok, info = launch_app(name)
        return {"ok": ok, "msg": ("Opened %s." % info) if ok else info}

    def _a_url(self, url=""):
        ok, u = run_url(url)
        return {"ok": ok, "msg": "Opened %s" % u}

    def _a_clip_write(self, text=""):
        ok = clipboard_set(text)
        return {"ok": ok, "msg": "Copied %d characters to the clipboard." % len(str(text)) if ok else "Copy failed."}

    def _a_type(self, text=""):
        ok = type_text(text)
        return {"ok": ok, "msg": "Typed %d characters." % len(str(text)) if ok else "Typing failed."}

    def _a_show_doc(self, path=""):
        """Dibuat oleh Api (ia perlu _window untuk tukar panel), bukan di sini.

        System tidak tahu tentang HUD; ia hanya tahu tentang Windows. Kalau
        panel DOK mesti dibuka, itu kerja pemanggil. Jadi tindakan ini
        ditandakan sebagai 'delegated' dan Api yang menyelesaikannya.
        """
        return {"ok": False, "msg": "show_doc must be handled by Api."}
    _a_show_doc.delegated = True

    def _a_lock(self):
        lock_workstation()
        return {"ok": True, "msg": "Laptop dikunci."}

    def _a_show_desktop(self):
        _u32.keybd_event(0x5B, 0, 0, 0); _u32.keybd_event(0x44, 0, 0, 0)
        _u32.keybd_event(0x44, 0, 2, 0); _u32.keybd_event(0x5B, 0, 2, 0)
        return {"ok": True, "msg": "Desktop ditunjuk."}

    def _a_power_cancel(self):
        ok, msg = power_action("cancel")
        return {"ok": ok, "msg": "Cancelled." if ok else (msg or "Nothing to cancel.")}

    # ═════════════ pukal — perlukan token ═════════════
    def _a_kill(self, name=""):
        hits, names = kill_process(name)
        if not hits:
            return {"ok": False, "msg": "No process named \"%s\"." % name}
        return {"ok": True, "msg": "Closed %d processes: %s." % (hits, ", ".join(sorted(set(names))))}
    _a_kill.kind = HARD
    _a_kill.ask = lambda name="", **_: "Force close %s? Unsaved work will be lost." % name

    def _a_close_window(self, title=""):
        hwnd = find_window(title)
        if not hwnd:
            return {"ok": False, "msg": "Window \"%s\" not found." % title}
        close_window(hwnd)
        return {"ok": True, "msg": "Sent a close command to %s." % title}
    _a_close_window.kind = HARD
    _a_close_window.ask = lambda title="", **_: "Close the window \"%s\"?" % title

    def _a_recycle(self, paths=None):
        if isinstance(paths, str):
            paths = [paths]
        n, msg = recycle_paths(paths or [])
        return {"ok": n > 0, "msg": msg, "count": n}
    _a_recycle.kind = HARD
    _a_recycle.ask = lambda paths=None, **_: "Send %s to the Recycle Bin?" % (
        ", ".join(Path(str(p)).name for p in (paths or []))[:80])

    def _a_shutdown(self):
        ok, msg = power_action("shutdown")
        return {"ok": ok, "msg": msg}
    _a_shutdown.kind = HARD
    _a_shutdown.ask = "Shut down the laptop now?"

    def _a_restart(self):
        ok, msg = power_action("restart")
        return {"ok": ok, "msg": msg}
    _a_restart.kind = HARD
    _a_restart.ask = "Restart the laptop now?"

    def _a_sleep(self):
        if sleep_pc():
            return {"ok": True, "msg": "Laptop is going to sleep."}
        return {"ok": False, "msg": "Could not put the laptop to sleep."}
    _a_sleep.kind = HARD
    _a_sleep.ask = "Put the laptop to sleep now?"


# Senarai nama tindakan untuk prompt model dan untuk pengesahan awal.
ACTIONS = [m[3:] for m in dir(System) if m.startswith("_a_")]
