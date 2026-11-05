"""What is actually in a folder or a file — measured, not guessed.

Why this is not a model call: "how many files, what kinds, how big, what is
old, what is duplicated" are facts on disk. A language model reading a listing
will approximate them. os.scandir will not.

The output is shaped for the HUD's analysis pane (cards / charts / points), so
a report drawn here looks like every other report Jarvis gives.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# Noise that would swamp any honest reading of "what is in here". Not a
# safety line — a measuring one: 40k files of node_modules say nothing about
# the project that owns them.
NOISE = {
    "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "env",
    "site-packages", "dist", "build", ".next", ".nuxt", "target", ".cache",
    ".pytest_cache", ".mypy_cache", ".idea", ".vs", "bin", "obj",
}
# Extension -> what a person would call it.
KIND = {
    "image": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "raw", "cr2", "nef",
              "svg", "ico", "tif", "tiff", "psd", "ai"},
    "video": {"mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "3gp"},
    "audio": {"mp3", "wav", "m4a", "flac", "aac", "ogg", "opus", "wma", "aiff"},
    "document": {"pdf", "doc", "docx", "txt", "rtf", "odt", "md", "tex", "epub"},
    "sheet": {"xls", "xlsx", "csv", "xlsm", "ods", "tsv"},
    "slide": {"ppt", "pptx", "odp", "key"},
    "code": {"py", "js", "ts", "tsx", "jsx", "java", "c", "cpp", "h", "hpp", "cs", "go",
             "rs", "rb", "php", "swift", "kt", "sql", "html", "css", "scss", "sh",
             "ps1", "bat", "vbs", "lua", "dart", "vue", "svelte"},
    "data": {"json", "xml", "yaml", "yml", "toml", "ini", "cfg", "db", "sqlite", "log"},
    "archive": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg"},
    "installer": {"exe", "msi", "apk", "deb", "rpm", "pkg", "appx"},
    "font": {"ttf", "otf", "woff", "woff2"},
}

MAX_ENTRIES = 120_000     # honest ceiling; the report says when it was hit
LARGE_FILE = 500 * 1024 * 1024


def _kind(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    for k, s in KIND.items():
        if ext in s:
            return k
    return "other" if ext else "no extension"


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024.0
    return f"{n:.1f} TB"


def _when(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def _age(days: float) -> str:
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 31:
        return f"{int(days)} days ago"
    if days < 365:
        return f"{int(days / 30)} months ago"
    return f"{days / 365:.1f} years ago"


# ── single file ────────────────────────────────────────────────────────────

TEXTY = {"txt", "md", "csv", "json", "xml", "yaml", "yml", "ini", "cfg", "log",
         "py", "js", "ts", "tsx", "jsx", "html", "css", "sql", "sh", "ps1", "bat"}


def inspect_file(p: Path) -> dict:
    st = p.stat()
    ext = p.suffix.lower().lstrip(".")
    now = time.time()
    out = {
        "kind": "file", "name": p.name, "path": str(p), "ext": ext,
        "type": _kind(ext), "size": st.st_size, "size_h": _human(st.st_size),
        "modified": _when(st.st_mtime), "created": _when(st.st_ctime),
        "age": _age((now - st.st_mtime) / 86400),
        "lines": 0, "words": 0, "encoding": "", "preview": "",
    }
    # Hash the first and last megabyte, not the whole file: enough to identify
    # it, cheap enough that a 3 GB video does not stall the answer.
    h = hashlib.sha1()
    try:
        with open(p, "rb") as f:
            h.update(f.read(1024 * 1024))
            if st.st_size > 2 * 1024 * 1024:
                f.seek(-1024 * 1024, os.SEEK_END)
                h.update(f.read(1024 * 1024))
        out["sha1"] = h.hexdigest()[:16]
    except OSError:
        out["sha1"] = ""
    if ext in TEXTY and st.st_size < 8 * 1024 * 1024:
        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                text = p.read_text(encoding=enc)
                # A file ending in a newline has no line after it — counting
                # "\n" + 1 would report a phantom last line on every well
                # formed source file, which is most of them.
                tail = 0 if text.endswith("\n") else 1
                out.update(encoding=enc, lines=text.count("\n") + tail,
                           words=len(text.split()), preview=text[:600])
                break
            except (UnicodeDecodeError, OSError):
                continue
    return out


# ── folder ─────────────────────────────────────────────────────────────────

def inspect_folder(root: Path, max_entries: int = MAX_ENTRIES) -> dict:
    t0 = time.time()
    root = root.resolve()
    files, dirs = 0, 0
    total = 0
    ext_count, ext_bytes = Counter(), Counter()
    kind_count = Counter()
    depths = Counter()
    ages = {"< 1 week": 0, "1–4 weeks": 0, "1–6 months": 0, "6–12 months": 0, "> 1 year": 0}
    empty_files = 0
    biggest = []                 # (size, relpath) kept small
    newest = oldest = None
    newest_p, oldest_p = "", ""
    by_size: dict[int, list[Path]] = {}
    names = []
    truncated = False
    now = time.time()
    errors = 0

    for cur, subdirs, filenames in os.walk(root, onerror=lambda e: None):
        subdirs[:] = [d for d in subdirs if d.lower() not in NOISE and not d.startswith("$")]
        cur_p = Path(cur)
        try:
            depth = len(cur_p.relative_to(root).parts)
        except ValueError:
            depth = 0
        dirs += len(subdirs)
        for fn in filenames:
            fp = cur_p / fn
            try:
                st = fp.stat()
            except OSError:
                errors += 1
                continue
            if not fp.is_file():
                continue
            files += 1
            size = st.st_size
            total += size
            depths[min(depth, 8)] += 1
            ext = fp.suffix.lower().lstrip(".")
            ext_count[ext or "—"] += 1
            ext_bytes[ext or "—"] += size
            kind_count[_kind(ext)] += 1
            if size == 0:
                empty_files += 1
            if size:
                biggest.append((size, str(fp.relative_to(root))))
                if len(biggest) > 40:
                    biggest.sort(reverse=True)
                    del biggest[12:]
            age_days = (now - st.st_mtime) / 86400
            if age_days < 7:
                ages["< 1 week"] += 1
            elif age_days < 30:
                ages["1–4 weeks"] += 1
            elif age_days < 182:
                ages["1–6 months"] += 1
            elif age_days < 365:
                ages["6–12 months"] += 1
            else:
                ages["> 1 year"] += 1
            if newest is None or st.st_mtime > newest:
                newest, newest_p = st.st_mtime, str(fp.relative_to(root))
            if oldest is None or st.st_mtime < oldest:
                oldest, oldest_p = st.st_mtime, str(fp.relative_to(root))
            if size > 64 * 1024:      # below this, duplicate detection is noise
                by_size.setdefault(size, []).append(fp)
            stem = fp.stem.lower()
            for tok in re.findall(r"[a-z][a-z0-9]{2,}", stem):
                names.append(tok)
            if files >= max_entries:
                truncated = True
                break
        if truncated:
            break

    # The in-loop sort only fires in batches, so the final list is trimmed
    # once more here — otherwise the last few files can arrive unsorted.
    biggest.sort(reverse=True)
    del biggest[12:]

    dups, dup_bytes, dup_groups = 0, 0, 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        seen: dict[str, Path] = {}
        for fp in paths:
            try:
                with open(fp, "rb") as f:
                    digest = hashlib.sha1(f.read(65536)).hexdigest()
            except OSError:
                continue
            if digest in seen:
                if len(seen) == 1:
                    dup_groups += 1
                dups += 1
                dup_bytes += size
            else:
                seen[digest] = fp

    return {
        "kind": "folder", "name": root.name or str(root), "path": str(root),
        "files": files, "dirs": dirs, "size": total, "size_h": _human(total),
        "ext": ext_count.most_common(14),
        "ext_bytes": ext_bytes.most_common(10),
        "types": kind_count.most_common(),
        "ages": ages,
        "depth": sorted(depths.items()),
        "empty": empty_files, "errors": errors, "truncated": truncated,
        "biggest": [{"size": s, "size_h": _human(s), "path": rp} for s, rp in biggest],
        "newest": _when(newest) if newest else "", "newest_path": newest_p,
        "oldest": _when(oldest) if oldest else "", "oldest_path": oldest_p,
        "dups": dups, "dup_bytes": dup_bytes, "dup_groups": dup_groups,
        "clusters": Counter(names).most_common(10),
        "secs": round(time.time() - t0, 2),
    }


def inspect(raw) -> dict:
    """One entry point. Accepts a path, decides file or folder, never raises."""
    try:
        p = Path(os.path.expanduser(str(raw))).resolve()
    except (OSError, ValueError):
        return {"ok": False, "msg": "That path cannot be read."}
    if not p.exists():
        return {"ok": False, "msg": f'"{p.name}" is not on this machine.'}
    try:
        if p.is_file():
            if p.stat().st_size > 2 * 1024 * 1024 * 1024:
                return {"ok": False, "msg": "Files over 2 GB are outside what I can read."}
            return {"ok": True, **inspect_file(p)}
        return {"ok": True, **inspect_folder(p)}
    except PermissionError:
        return {"ok": False, "msg": "Windows denied access to that path."}
    except OSError as e:
        return {"ok": False, "msg": f"Cannot read it: {e}"}


# ── report ─────────────────────────────────────────────────────────────────

def dashboard(d: dict) -> dict | None:
    """Measured facts -> the payload the analysis pane already knows how to draw."""
    if not d.get("ok"):
        return None

    if d["kind"] == "file":
        cards = [
            {"label": "Size", "value": d["size_h"], "note": f'{d["size"]:,} bytes'},
            {"label": "Type", "value": d["ext"] or "—", "note": d["type"]},
            {"label": "Modified", "value": d["age"], "note": d["modified"]},
            {"label": "Lines", "value": f'{d["lines"]:,}' if d["lines"] else "—",
             "note": f'{d["words"]:,} words' if d["words"] else "not text"},
        ]
        pts = [
            {"text": f"{d['name']} is {d['size_h']}, a {d['type']} file, last changed {d['age']}.",
             "target": "card:0"},
        ]
        if d["lines"]:
            pts.append({"text": f"It is text — {d['lines']:,} lines, {d['words']:,} words, "
                                 f"read as {d['encoding']}.", "target": "card:3"})
        pts.append({"text": f"Its identity hash is {d['sha1'] or 'not readable'}.",
                    "target": "card:1"})
        return {"title": d["name"], "summary": f"{d['type']} · {d['size_h']} · changed {d['age']}",
                "cards": cards, "charts": [], "points": pts,
                "followups": ["Show me the first lines.", "Where else is this file?"]}

    files = d["files"]
    if not files and not d["dirs"]:
        return {"title": d["name"], "summary": "This folder is empty.",
                "cards": [{"label": "Files", "value": "0", "note": "nothing to measure"}],
                "charts": [], "points": [{"text": f"{d['name']} has nothing in it.", "target": "card:0"}],
                "followups": []}

    dom_type = d["types"][0][0] if d["types"] else "mixed"
    dominant = d["types"][0][1] if d["types"] else 0
    share = round(dominant / files * 100) if files else 0
    newest_age = _age((time.time() - datetime.strptime(d["newest"], "%Y-%m-%d").timestamp()) / 86400) \
        if d["newest"] else "unknown"

    cards = [
        {"label": "Files", "value": f"{files:,}",
         "note": f'{d["dirs"]:,} folders deep to {max((x for x, _ in d["depth"]), default=0)} levels'},
        {"label": "Total size", "value": d["size_h"],
         "note": f"avg {_human(d['size'] / files) if files else '0'} per file"},
        {"label": "Mostly", "value": dom_type, "note": f"{dominant:,} files · {share}%"},
        {"label": "Newest", "value": newest_age, "note": d["newest"]},
    ]
    charts = [
        {"title": "What is in here", "kind": "donut",
         "items": [{"label": k, "value": v, "display": str(v)} for k, v in d["types"][:6]]},
        {"title": "By extension · count", "kind": "bar",
         "items": [{"label": e, "value": c, "display": f"{c:,}"} for e, c in d["ext"][:8]]},
        {"title": "How old", "kind": "bar",
         "items": [{"label": k, "value": v, "display": f"{v:,}"} for k, v in d["ages"].items()]},
    ]
    if d["ext_bytes"]:
        charts.append({"title": "What eats the space", "kind": "bar",
                       "items": [{"label": e, "value": b, "display": _human(b)}
                                 for e, b in d["ext_bytes"][:8]]})

    pts = [
        {"text": f"{d['name']} holds {files:,} files in {d['dirs']:,} folders, {d['size_h']} in total.",
         "target": "card:0"},
        {"text": f"Most of it is {dom_type} — {dominant:,} files, about {share} percent.",
         "target": "card:2"},
        {"text": f"The newest file changed {newest_age}. The oldest goes back to {d['oldest'] or 'unknown'}.",
         "target": "card:3"},
    ]
    if d["dups"]:
        pts.append({"text": f"There are {d['dups']:,} duplicate files in {d['dup_groups']:,} groups — "
                             f"{_human(d['dup_bytes'])} you could get back.", "target": "chart:0"})
    if d["empty"]:
        pts.append({"text": f"{d['empty']:,} files in here are empty, zero bytes.", "target": "card:0"})
    if d["clusters"]:
        top = ", ".join(f"{w} ({n})" for w, n in d["clusters"][:3])
        pts.append({"text": f"The names repeat these words most: {top}.", "target": "chart:1:0"})
    if d["truncated"]:
        pts.append({"text": f"I stopped after {MAX_ENTRIES:,} files, so these numbers are a floor, "
                             "not the whole folder.", "target": "card:0"})

    summ = f"{files:,} files · {d['size_h']} · mostly {dom_type} · newest {d['newest'] or '—'}"
    return {"title": f"Report — {d['name']}", "summary": summ,
            "cards": cards, "charts": charts, "points": pts[:7],
            "followups": ["Which files are the biggest?", "What is duplicated?",
                          "What changed this week?"]}


def listing(d: dict, limit: int = 200) -> list[dict]:
    """A flat listing for the docs pane: path, size, date, type."""
    if not d.get("ok") or d["kind"] != "folder":
        return []
    out = []
    root = Path(d["path"])
    try:
        for cur, subdirs, filenames in os.walk(root, onerror=lambda e: None):
            subdirs[:] = [x for x in subdirs if x.lower() not in NOISE and not x.startswith("$")]
            for fn in filenames:
                fp = Path(cur) / fn
                try:
                    st = fp.stat()
                except OSError:
                    continue
                out.append({"path": str(fp.relative_to(root)), "size": st.st_size,
                            "size_h": _human(st.st_size), "date": _when(st.st_mtime),
                            "type": _kind(fp.suffix)})
                if len(out) >= limit:
                    return out
    except OSError:
        pass
    return out
