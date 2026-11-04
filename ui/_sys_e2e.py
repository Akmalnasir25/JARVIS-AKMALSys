"""Ujian hujung-ke-hujung untuk kawalan laptop. Jalankan: python ui/_sys_e2e.py

Guna Api sebenar dengan _window=None — _push() dan _emit() sudah tahan bridge
yang tiada, jadi semua logik resolver dan system.py boleh diuji tanpa WebView2.
Setiap tindakan yang mengubah mesin dipulihkan pada penghujungnya.
"""
import sys
import time

sys.path.insert(0, r"C:\Users\akmal\jarvis-desktop")
import main as M
import system as S

api = M.Api()
api._window = None

fails, passes = [], 0


def check(label, got, want):
    global passes
    ok = got == want
    if ok:
        passes += 1
    else:
        fails.append("%s\n     got  %r\n     want %r" % (label, got, want))
    print("%-4s %-46s %r" % ("ok" if ok else "FAIL", label, got))


def run(text):
    return api.resolve_system(text)


# ── 1. laluan pantas: ayat sistem mesti tidak sampai ke model
print("\n-- routing --")
r = run("volume 40")
check("volume 40 handled", r["handled"], True)
check("volume 40 label", r["label"], "✔ Volume 40%.")
check("volume 40 actual", S.volume_get(), 40)

r = run("volume naik")
check("volume naik -> 50", S.volume_get(), 50)

r = run("mute")
check("mute on", S.mute_get(), True)
r = run("unmute")
check("unmute", S.mute_get(), False)
S.volume_set(55)

# ayat biasa mesti jatuh ke model, bukan ditelan resolver
for phrase in ("apa khabar akmal", "buat analisis jualan", "ringkaskan fail ni", "main lagu"):
    check("passthrough: " + phrase, run(phrase)["handled"], False)

# ── 2. pengesahan: token, bukan tindakan terus
print("\n-- confirm gate --")
before = api._sys.status()["volume"]
r = run("tutup laptop")
check("shutdown gated", bool(r.get("confirm")), True)
check("shutdown not performed (token held)", api._pending_token is not None, True)

r = run("tak")
check("tak cancels", (r["handled"], api._pending_token), (True, None))

# token palsu ditolak
check("confirm bad token", api._sys.confirm("00000000")["ok"], False)

# token luput
tok = api._sys._mint("lock", {}, "test")["token"]
api._sys._pending[tok]["until"] = time.time() - 1
check("confirm expired token", api._sys.confirm(tok)["ok"], False)

# ── 3. tindakan sebenar yang selamat
print("\n-- real actions --")
r = run("status laptop")
check("status ok", r["handled"] and "Volume" in r["label"], True)

r = run("salin teks ujian 99")
check("clip write", S.clipboard_get(), "teks ujian 99")
check("clip read", run("baca clipboard")["label"].startswith("✔"), True)

r = run("buka notepad")
check("buka notepad not resolved (goes to open path / model)", r["handled"], False)
# Notepad lain yang sudah terbuka atas desktop Akmal mesti tidak disentuh —
# ujian ini hanya menguruskan tetingkap yang ia sendiri lahirkan.
pre = {w["hwnd"] for w in S.list_windows(400) if "notepad" in w["title"].lower()}
r = api._sys.do("launch", name="notepad")
check("launch notepad", r["ok"], True)
time.sleep(2.0)
new = [w for w in S.list_windows(400)
       if "notepad" in w["title"].lower() and w["hwnd"] not in pre]
check("notepad window exists", bool(new), True)

r = run("fokus notepad")
check("focus notepad", r["label"].startswith("✔"), True)

target = new[0]["title"] if new else "notepad"
r = run("tutup " + target)
check("close notepad gated", bool(r.get("confirm")), True)
if r.get("confirm"):
    check("token held for yes", api._pending_token is not None, True)
    r = run("ya")
    check("close notepad confirmed", r["label"].startswith("✔"), True)
else:
    fails.append("close notepad never asked for confirmation")
time.sleep(1.5)
check("notepad gone", [w for w in S.list_windows(400)
                       if w["hwnd"] in {n["hwnd"] for n in new}], [])

# ── 4. shell allow-list
print("\n-- shell --")
check("ipconfig allowed", run("run ipconfig")["label"].startswith("✔"), True)
check("chained blocked", run("run ipconfig && del x")["handled"], False)
check("shell_allowed(ping 8.8.8.8)", S.shell_allowed("ping 8.8.8.8"), True)
check("shell_allowed(rm)", S.shell_allowed("rm -rf /"), False)
check("shell_allowed(pipe)", S.shell_allowed("dir | findstr x"), False)
check("shell_allowed(del)", S.shell_allowed("del /q *"), False)

# ── 5. suara: quick_control mesti guna resolver, bukan tekan kekunci 40 kali
print("\n-- voice path --")
S.volume_set(10)
r = api.quick_control("volume 30")
check("voice volume 30 label", r["label"].startswith("✔"), True)
check("voice volume 30 actual", S.volume_get(), 30)

r = api.quick_control("next slide")   # kata kunci media kekal di services.ACTIONS
check("voice next slide still services", r["label"], "Next slide")
r = api.quick_control("main lagu")
check("voice 'main lagu' not swallowed by resolver", r["handled"], False)

# ── 6. prompt model melihat system tool dan enumerasinya lengkap
print("\n-- model surface --")
tools = {t["function"]["name"]: t for t in M.CHAT_TOOLS}
check("system tool present", "system" in tools, True)
enum = tools["system"]["function"]["parameters"]["properties"]["action"]["enum"]
check("enum covers every system action",
      sorted(set(enum) - set(S.ACTIONS)), [])
check("enum has no phantom action",
      sorted(set(S.ACTIONS) - set(enum)), [])
check("trigger picks system tool", "system" in [t["function"]["name"] for t in
      M.tools_for("tolong set volume 20 dan cerahkan skrin", [])], True)

# ── 7. show_doc: nama fail dalam ayat -> panel DOK, bukan app luar
print("\n-- show_doc --")
probe = M.ROOT / "_probe_doc_ujian.txt"
probe.write_text("baris satu\nbaris dua\n", encoding="utf-8")
try:
    r = run("buka _probe_doc_ujian.txt")
    check("buka <fail> handled", r.get("handled"), True)
    check("buka <fail> label", r.get("label", "").startswith("✔"), True)
    check("buka <fail> resolves in workdir", r.get("path"), str(probe))
    r = run("buka tiada_fail_ini_999.pdf")
    check("buka fail tiada falls through", r.get("handled"), False)
    # model tool mesti lalu jalan yang sama, bukan _a_show_doc yang delegates
    r = api._chat_tool("system", {"action": "show_doc", "path": str(probe)})
    check("tool show_doc delegated to Api", r.startswith("✔"), True)
    r = api._chat_tool("system", {"action": "show_doc", "path": "C:/Windows/notepad.exe"})
    check("tool show_doc outside workdir refused", r.startswith("✖"), True)
finally:
    probe.unlink(missing_ok=True)

# ── 8. pulihkan mesin
S.volume_set(55)
S.brightness_set(70)

print("\n%d lulus, %d gagal" % (passes, len(fails)))
for f in fails:
    print("  - " + f)
sys.exit(1 if fails else 0)
