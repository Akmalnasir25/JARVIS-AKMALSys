"""Standalone proof that inspect_path measures a real folder correctly.

Builds a fixture with known counts and known duplicates, then asserts the
numbers — a report that looks plausible and is wrong is the failure mode
worth guarding against.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\akmal\jarvis-desktop")
import inspect_path as ip

CHECKS = []
def ok(cond, name, extra=""):
    CHECKS.append((bool(cond), name, extra))
    print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + str(extra)) if extra and not cond else ""))


def fixture(tmp: Path):
    # 3 py, 2 png, 1 pdf, 1 zip, 1 empty txt, 2 identical binaries (dupes),
    # nested 3 levels deep, one in a node_modules that must be ignored.
    (tmp / "src" / "deep" / "deeper").mkdir(parents=True)
    (tmp / "assets").mkdir()
    (tmp / "node_modules" / "junk").mkdir(parents=True)
    (tmp / "main.py").write_text("import os\nprint(1)\n", encoding="utf-8")
    (tmp / "src" / "util.py").write_text("x = 1\n" * 40, encoding="utf-8")
    (tmp / "src" / "deep" / "deeper" / "last.py").write_text("y = 2\n", encoding="utf-8")
    (tmp / "assets" / "a.png").write_bytes(b"\x89PNG" + b"0" * 5000)
    (tmp / "assets" / "b.png").write_bytes(b"\x89PNG" + b"1" * 7000)
    (tmp / "doc.pdf").write_bytes(b"%PDF-1.4" + b"z" * 120000)
    (tmp / "pack.zip").write_bytes(b"PK" + b"q" * 30000)
    (tmp / "empty.txt").write_bytes(b"")
    (tmp / "node_modules" / "junk" / "should-not-count.js").write_text("nope", encoding="utf-8")
    # two byte-identical small-but-over-64k files -> one duplicate group
    blob = os.urandom(70000)
    (tmp / "copy-a.bin").write_bytes(blob)
    (tmp / "copy-b.bin").write_bytes(blob)
    return tmp


tmp = Path(tempfile.mkdtemp(prefix="ipfix_"))
try:
    fixture(tmp)
    d = ip.inspect(str(tmp))

    ok(d["ok"], "folder inspection succeeds")
    # 11 real files: main, util, last, a.png, b.png, doc.pdf, pack.zip, empty.txt, copy-a, copy-b = 10
    ok(d["files"] == 10, "file count excludes node_modules", d.get("files"))
    ok(any("node_modules" in p for _s, p in [(x["size"], x["path"]) for x in d["biggest"]]) is False,
       "node_modules content never appears in the largest list")
    ok(d["empty"] == 1, "one empty file detected", d.get("empty"))
    ok(d["dups"] == 1, "one duplicate detected", d.get("dups"))
    ok(d["dup_groups"] == 1, "one duplicate group", d.get("dup_groups"))
    ok(d["dup_bytes"] == 70000, "duplicate bytes exact", d.get("dup_bytes"))
    ok(dict(d["ext"])["py"] == 3, "three python files", d.get("ext"))
    ok(d["dirs"] >= 3, "folder count includes nested dirs", d.get("dirs"))
    ok(max(x for x, _ in d["depth"]) == 3, "deepest file is 3 levels down", d.get("depth"))
    ok(d["biggest"] and d["biggest"][0]["path"].endswith("doc.pdf"),
       "largest file is doc.pdf", d.get("biggest", [])[:1])
    ok(any(t == "code" for t, _ in d["types"]), "python classified as code", d.get("types"))

    dash = ip.dashboard(d)
    ok(dash is not None, "dashboard builds")
    ok(len(dash["cards"]) == 4, "four cards", len(dash.get("cards", [])))
    ok(1 <= len(dash["charts"]) <= 4, "charts within range", len(dash.get("charts", [])))
    ok(3 <= len(dash["points"]) <= 7, "points within range", len(dash.get("points", [])))
    kinds = [c["kind"] for c in dash["charts"]]
    ok("donut" in kinds and "bar" in kinds, "both donut and bar present", kinds)
    for c in dash["charts"]:
        ok(all(isinstance(i["value"], int) for i in c["items"]),
           f'chart "{c["title"]}" has numeric values only')
    donut = [c for c in dash["charts"] if c["kind"] == "donut"][0]
    ok(sum(i["value"] for i in donut["items"]) <= d["files"],
       "donut slices never exceed the file count", (sum(i["value"] for i in donut["items"]), d["files"]))

    # single file
    one = ip.inspect(str(tmp / "main.py"))
    ok(one["ok"] and one["kind"] == "file", "single file inspection succeeds")
    ok(one["lines"] == 2, "line count exact on main.py", one.get("lines"))
    ok(one["encoding"] == "utf-8", "encoding detected", one.get("encoding"))
    ok(one["words"] >= 3, "word count sane", one.get("words"))
    fdash = ip.dashboard(one)
    ok(fdash and fdash["cards"][1]["value"] == "py", "single-file report names the type",
       fdash["cards"][1] if fdash else None)

    big = ip.inspect(str(tmp / "doc.pdf"))
    ok(big["lines"] == 0 and big["preview"] == "", "binary file is not read as text")

    # failures must return a reason, never raise
    miss = ip.inspect(str(tmp / "nope.txt"))
    ok(not miss["ok"] and "not on this machine" in miss["msg"], "missing path returns a reason",
       miss.get("msg"))

    lst = ip.listing(d)
    ok(len(lst) == 10, "listing returns every file", len(lst))
    ok(all({"path", "size", "size_h", "date", "type"} <= set(r) for r in lst),
       "listing rows carry the full shape")
    ok(not any("node_modules" in r["path"] for r in lst), "listing excludes noise dirs")

    # speed on a real tree
    import time
    t0 = time.time()
    real = ip.inspect(r"C:\Users\akmal\jarvis-desktop")
    dt = time.time() - t0
    ok(real["ok"], "real project folder inspects")
    ok(dt < 8, f"real folder finished in {dt:.2f}s", f"{dt:.2f}s")
    print(f"\n  jarvis-desktop: {real['files']} files, {real['size_h']}, "
          f"{len(real['types'])} types, {real['dups']} dups, {dt:.2f}s")

    bad = [c for c in CHECKS if not c[0]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} passed")
    sys.exit(1 if bad else 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
