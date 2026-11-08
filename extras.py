"""Kerja harian Jarvis: memori, kalendar, draf e-mel, dokumen rasmi, sijil, rutin,
pemantau laman web, deploy Firebase dan backup.

Semua tindakan yang keluar ke dunia luar ikut peraturan yang sama dengan Telegram:
  · e-mel   -> DRAF dalam Gmail sahaja; Tuan hantar sendiri (tool send tak diberi langsung)
  · deploy  -> perlu "ya" Tuan dahulu
  · rutin   -> menjalankan arahan biasa; mesej yang terhasil masih draf yang perlu "ya"
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

NO_WINDOW = 0x08000000
DAYS = {"isnin": 0, "monday": 0, "selasa": 1, "tuesday": 1, "rabu": 2, "wednesday": 2, "khamis": 3,
        "thursday": 3, "jumaat": 4, "friday": 4, "sabtu": 5, "saturday": 5, "ahad": 6, "sunday": 6}
DAY_NAMES = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"]

CAL_TOOLS = ["mcp__claude_ai_Google_Calendar"]
GMAIL_DRAFT = ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread",
               "mcp__claude_ai_Gmail__get_message", "mcp__claude_ai_Gmail__list_drafts",
               "mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Gmail__update_draft"]   # TIADA send


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(p: Path, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class Extras:
    def __init__(self, api, root: Path, log=print):
        self.api = api
        self.root = Path(root)
        self.log = log
        self.mem_file = self.root / "memory.json"
        self.rt_file = self.root / "routines.json"
        self.site_state = {}
        self.pending_deploy = None
        self._lock = threading.Lock()

    def cfg(self):
        return _load(self.root / "config.json", {})

    def notify(self, title, body, tag="jarvis"):
        try:
            self.api._phone_notify(title, body, tag)
        except Exception:
            pass

    def note(self, text):
        try:
            self.api._emit("note", {"text": text})
        except Exception:
            pass

    # ════════ 1. memori jangka panjang ════════
    def memories(self):
        return _load(self.mem_file, [])

    def remember(self, text):
        text = re.sub(r"\s+", " ", str(text or "")).strip(" .")
        if len(text) < 3:
            return "Tiada apa untuk diingat."
        with self._lock:
            mem = self.memories()
            low = text.lower()
            if any(m["text"].lower() == low for m in mem):
                return "Saya dah ingat itu."
            mem.append({"id": int(time.time() * 1000), "text": text, "at": time.strftime("%Y-%m-%d")})
            _save(self.mem_file, mem[-300:])
        return f"✔ Diingat: {text}"

    def forget(self, what):
        what = str(what or "").strip().lower()
        with self._lock:
            mem = self.memories()
            if what.isdigit() and 1 <= int(what) <= len(mem):
                gone = mem.pop(int(what) - 1)
            else:
                words = [w for w in re.findall(r"\w+", what) if len(w) > 2]
                scored = sorted(((sum(w in m["text"].lower() for w in words), i) for i, m in enumerate(mem)), reverse=True)
                if not scored or scored[0][0] == 0:
                    return "Tak jumpa ingatan yang padan."
                gone = mem.pop(scored[0][1])
            _save(self.mem_file, mem)
        return f"✔ Dilupakan: {gone['text']}"

    def memory_note(self):
        mem = self.memories()
        if not mem:
            return ""
        lines = "\n".join(f"- {m['text']}" for m in mem[-80:])
        return ("\n\nPERKARA YANG TUAN MINTA KAMU INGAT (guna bila berkaitan, jangan sebut senarai ini kecuali ditanya):\n"
                + lines)

    def memory_list(self):
        mem = self.memories()
        if not mem:
            return "Belum ada apa-apa dalam ingatan. Cakap «ingat, …» untuk simpan."
        return "Yang saya ingat:\n" + "\n".join(f"{i}. {m['text']}" for i, m in enumerate(mem, 1))

    # ════════ 2. Google Calendar (melalui penyambung Claude) ════════
    def calendar(self, request):
        now = datetime.now().strftime("%A %d %B %Y, %H:%M")
        return self.api._claude_quick(
            f"Guna Google Calendar Tuan. Sekarang {now}, zon waktu Asia/Kuala_Lumpur. Permintaan Tuan: {request}\n"
            "- Untuk melihat jadual: senaraikan acara (masa, tajuk, tempat) ringkas.\n"
            "- Untuk mencipta acara: cipta terus jika tajuk, tarikh dan masa jelas (tempoh lalai 1 jam), kemudian "
            "sahkan apa yang dicipta. Jika ada yang tak jelas, JANGAN cipta — tanya Tuan.\n"
            "- JANGAN padam atau ubah acara sedia ada kecuali Tuan minta dengan jelas.\n"
            "- Jika Calendar belum disambung/perlu authenticate, jawab tepat: KALENDAR_BELUM_DISAMBUNG",
            CAL_TOOLS, model="sonnet", timeout=150)

    def calendar_today_json(self):
        """Acara baki hari ini sebagai JSON — untuk peringatan dan laporan pagi."""
        out = self.api._claude_quick(
            "Guna Google Calendar. Senaraikan acara HARI INI yang belum tamat. Balas JSON SAHAJA: "
            '[{"title": "...", "start": "HH:MM", "where": "..."}]. Jika tiada, balas []. '
            "Jika Calendar tak boleh diakses, balas: null", CAL_TOOLS, model="haiku", timeout=120)
        m = re.search(r"\[[\s\S]*\]", str(out))
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None

    def calendar_watch(self):
        """Setiap jam (07:00-22:00) ambil acara hari ini; ingatkan di fon & HUD 15 minit sebelum."""
        reminded, events, fetched = set(), [], 0.0
        while True:
            try:
                now = datetime.now()
                if self.cfg().get("calendar_reminders", True) and 7 <= now.hour < 22:
                    if time.time() - fetched > 3600:
                        ev = self.calendar_today_json()
                        fetched = time.time()
                        if ev is not None:
                            events = ev
                    for e in events:
                        try:
                            hh, mm = map(int, str(e.get("start", "")).split(":")[:2])
                        except Exception:
                            continue
                        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                        mins = (t - now).total_seconds() / 60
                        key = (now.date(), e.get("title"), e.get("start"))
                        if 0 < mins <= 15 and key not in reminded:
                            reminded.add(key)
                            where = f" · {e['where']}" if e.get("where") else ""
                            self.notify(f"{e.get('start')} · {e.get('title')}", f"{int(mins)} min lagi{where}", "calendar")
                            self.note(f"📅 {int(mins)} min lagi: {e.get('title')}{where}")
            except Exception as ex:
                self.log(f"calendar watch: {ex}")
            time.sleep(60)

    # ════════ 4. draf e-mel Gmail (tiada tool hantar) ════════
    def email_draft(self, request):
        return self.api._claude_quick(
            f"Guna Gmail Tuan. Permintaan: {request}\n"
            "Cari e-mel berkaitan jika perlu (cth untuk membalas), kemudian CIPTA DRAF dalam Gmail — sebagai "
            "balasan dalam thread yang sama jika ia balasan. Tulis dalam nada dan bahasa e-mel asal (BM rasmi "
            "untuk urusan rasmi). JANGAN HANTAR — kamu memang tiada tool menghantar. Selepas siap, beritahu "
            "kepada siapa draf itu, subjeknya, dan petik isi draf penuh supaya Tuan boleh semak.",
            GMAIL_DRAFT, model="sonnet", timeout=180)

    # ════════ 5. dokumen rasmi (Word + PDF) ════════
    def docs_dir(self):
        d = Path(self.api.known_folder_path("Documents")) / "Jarvis Dokumen"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def to_pdf(path: Path) -> Path | None:
        """Word/PowerPoint -> PDF melalui Office (COM). None jika gagal."""
        try:
            import pythoncom
            import win32com.client
        except Exception:
            return None
        pythoncom.CoInitialize()
        pdf = path.with_suffix(".pdf")
        try:
            if path.suffix.lower() == ".docx":
                app = win32com.client.DispatchEx("Word.Application")
                app.Visible = False
                doc = app.Documents.Open(str(path), ReadOnly=True)
                doc.SaveAs2(str(pdf), FileFormat=17)
                doc.Close(False)
                app.Quit()
            elif path.suffix.lower() == ".pptx":
                app = win32com.client.DispatchEx("PowerPoint.Application")
                pres = app.Presentations.Open(str(path), ReadOnly=True, WithWindow=False)
                pres.SaveAs(str(pdf), 32)
                pres.Close()
                app.Quit()
            return pdf if pdf.exists() else None
        except Exception:
            return None
        finally:
            pythoncom.CoUninitialize()

    def make_document(self, kind, title, details):
        """Model tulis isi (JSON), Python susun dokumen rasmi BM dalam Word, Office tukar ke PDF."""
        s = self.api._secrets()
        mem = self.memory_note()
        prompt = (f"Tulis {kind or 'surat'} rasmi Bahasa Melayu (format sekolah/kerajaan Malaysia). Tajuk: {title}.\n"
                  f"Butiran daripada Tuan: {details}\n{mem}\n"
                  "Balas JSON SAHAJA dengan kunci: "
                  '{"kepada": ["baris alamat penerima", ...], "salam": "Tuan/Puan,", "tajuk": "TAJUK HURUF BESAR", '
                  '"perenggan": ["perenggan 1 ...", "..."], "penutup": "Sekian, terima kasih.", '
                  '"slogan": "\\"BERKHIDMAT UNTUK NEGARA\\"", "penandatangan": ["(NAMA)", "Jawatan", "Organisasi"]}\n'
                  "Perenggan bernombor secara automatik — jangan letak nombor sendiri. Guna maklumat yang ada; "
                  "untuk yang tiada, tulis tempat kosong seperti [Nama Penerima].")
        out = self.api._chat_call(s, [{"role": "system", "content": "Kamu penulis dokumen rasmi. Balas JSON sahaja."},
                                      {"role": "user", "content": prompt}])["content"] or ""
        m = re.search(r"\{[\s\S]*\}", out)
        try:
            d = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except Exception:
            return {"ok": False, "msg": "Model tak pulangkan isi dokumen yang sah."}

        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, Cm
        doc = Document()
        for sec in doc.sections:
            sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2.2)
            sec.left_margin, sec.right_margin = Cm(2.5), Cm(2.5)
        st = doc.styles["Normal"]
        st.font.name, st.font.size = "Arial", Pt(11)
        sender = self.cfg().get("doc_sender") or {}
        if sender.get("org"):
            h = doc.add_paragraph()
            h.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = h.add_run(sender["org"].upper())
            r.bold, r.font.size = True, Pt(13)
            for ln in sender.get("address", []):
                p = doc.add_paragraph(ln)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.add_paragraph("_" * 78)
        doc.add_paragraph(f"Tarikh: {datetime.now().strftime('%d %B %Y')}").alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for ln in d.get("kepada") or []:
            doc.add_paragraph(str(ln)).paragraph_format.space_after = Pt(0)
        doc.add_paragraph()
        doc.add_paragraph(str(d.get("salam") or "Tuan/Puan,"))
        t = doc.add_paragraph()
        tr = t.add_run(str(d.get("tajuk") or title).upper())
        tr.bold = True
        for i, para in enumerate(d.get("perenggan") or [], 1):
            p = doc.add_paragraph(f"{i}.\t{para}")
            p.paragraph_format.first_line_indent = Cm(-1)
            p.paragraph_format.left_indent = Cm(1)
            # perenggan dengan baris pecah (Tarikh:/Masa:/Tempat:) jadi jarang bila diratakan; ratakan kiri sahaja
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if "\n" in str(para) else WD_ALIGN_PARAGRAPH.JUSTIFY
        doc.add_paragraph(str(d.get("penutup") or "Sekian, terima kasih."))
        sl = doc.add_paragraph()
        sl.add_run(str(d.get("slogan") or '"BERKHIDMAT UNTUK NEGARA"')).bold = True
        doc.add_paragraph("Saya yang menjalankan amanah,")
        doc.add_paragraph("\n\n")
        for ln in (sender.get("signature") or d.get("penandatangan") or []):
            doc.add_paragraph(str(ln)).paragraph_format.space_after = Pt(0)

        slug = re.sub(r"[^\w\- ]+", "", title).strip()[:60] or "Dokumen"
        path = self.docs_dir() / f"{slug} {datetime.now():%Y-%m-%d %H%M}.docx"
        doc.save(path)
        pdf = self.to_pdf(path)
        return {"ok": True, "docx": str(path), "pdf": str(pdf) if pdf else ""}

    # ════════ 6. sijil berkelompok (Excel + templat PowerPoint/Word) ════════
    @staticmethod
    def _fill_paragraphs(paragraphs, row):
        for p in paragraphs:
            full = "".join(r.text for r in p.runs)
            if "{{" not in full:
                continue
            new = re.sub(r"\{\{\s*([^}]+?)\s*\}\}", lambda m: str(row.get(m.group(1).strip().lower(), m.group(0))), full)
            if new != full and p.runs:
                p.runs[0].text = new
                for r in p.runs[1:]:
                    r.text = ""

    def sample_template(self):
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Pt, Cm
        d = self.docs_dir().parent / "Jarvis Sijil"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "Templat Sijil Contoh.pptx"
        prs = Presentation()
        prs.slide_width, prs.slide_height = Cm(29.7), Cm(21)
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        lines = [("SIJIL PENGHARGAAN", 36, True), ("Dengan ini diakui bahawa", 16, False), ("{{Nama}}", 30, True),
                 ("{{Sekolah}}", 18, False), ("telah menyertai {{Program}}", 16, False), ("Kategori: {{Kategori}}", 16, False)]
        y = Cm(3)
        for text, size, bold in lines:
            tb = sl.shapes.add_textbox(Cm(1.5), y, Cm(26.7), Cm(2.2))
            p = tb.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text, r.font.size, r.font.bold = text, Pt(size), bold
            r.font.color.rgb = RGBColor(0x80, 0x10, 0x10) if bold else RGBColor(0x20, 0x20, 0x20)
            y += Cm(2.6)
        prs.save(path)
        return path

    def make_certificates(self, excel, template, progress=None):
        import openpyxl
        xl, tp = Path(excel), Path(template)
        wb = openpyxl.load_workbook(xl, read_only=True, data_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        if len(rows) < 2:
            return {"ok": False, "msg": "Excel kosong atau tiada baris data."}
        head = [str(h or "").strip().lower() for h in rows[0]]
        data = [{head[i]: ("" if v is None else str(v)) for i, v in enumerate(r) if i < len(head)}
                for r in rows[1:] if any(v not in (None, "") for v in r)]
        out = self.docs_dir().parent / "Jarvis Sijil" / f"{tp.stem} {datetime.now():%Y-%m-%d %H%M}"
        out.mkdir(parents=True, exist_ok=True)
        namecol = next((h for h in head if h in ("nama", "name", "nama penuh", "nama peserta")), head[0])
        made = []
        for i, row in enumerate(data, 1):
            fn = re.sub(r"[^\w\- ]+", "", row.get(namecol, f"peserta {i}")).strip()[:60] or f"peserta {i}"
            dst = out / f"{i:03d} {fn}{tp.suffix}"
            if tp.suffix.lower() == ".pptx":
                from pptx import Presentation
                prs = Presentation(tp)
                for slide in prs.slides:
                    for shp in slide.shapes:
                        if shp.has_text_frame:
                            self._fill_paragraphs(shp.text_frame.paragraphs, row)
                prs.save(dst)
            else:
                from docx import Document
                doc = Document(tp)
                self._fill_paragraphs(doc.paragraphs, row)
                for t in doc.tables:
                    for c in t._cells:
                        self._fill_paragraphs(c.paragraphs, row)
                doc.save(dst)
            pdf = self.to_pdf(dst)
            made.append(pdf or dst)
            if progress and (i % 10 == 0 or i == len(data)):
                progress(i, len(data))
        merged = ""
        pdfs = [p for p in made if Path(p).suffix == ".pdf"]
        if pdfs:
            try:
                import pymupdf as fitz
                m = fitz.open()
                for p in pdfs:
                    with fitz.open(p) as d:
                        m.insert_pdf(d)
                merged = str(out / "SEMUA SIJIL.pdf")
                m.save(merged)
            except Exception:
                pass
        return {"ok": True, "count": len(made), "folder": str(out), "merged": merged, "pdf": len(pdfs) == len(made)}

    # ════════ 7. rutin berjadual ════════
    def routines(self):
        return _load(self.rt_file, [])

    def add_routine(self, days, at, task):
        try:
            hh, mm = map(int, str(at).replace(".", ":").split(":")[:2])
        except Exception:
            return "Masa tak jelas — contoh 16:00."
        ds = []
        for dname in (days if isinstance(days, list) else re.split(r"[,\s]+", str(days))):
            dn = str(dname).strip().lower()
            if dn in ("setiap hari", "harian", "daily", "hari", "everyday"):
                ds = list(range(7))
                break
            if dn in ("hari kerja", "weekday", "weekdays"):
                ds = [0, 1, 2, 3, 4]
                break
            if dn in DAYS:
                ds.append(DAYS[dn])
        ds = sorted(set(ds)) or list(range(7))
        with self._lock:
            rt = self.routines()
            rt.append({"id": int(time.time()), "days": ds, "at": f"{hh:02d}:{mm:02d}", "task": str(task).strip(), "last": ""})
            _save(self.rt_file, rt)
        when = "setiap hari" if len(ds) == 7 else ", ".join(DAY_NAMES[d] for d in ds)
        return f"✔ Rutin disimpan: {when} {hh:02d}:{mm:02d} — {task}"

    def routine_list(self):
        rt = self.routines()
        if not rt:
            return "Tiada rutin. Contoh: «setiap Jumaat 4 petang, ringkaskan kehadiran minggu ni»."
        return "Rutin:\n" + "\n".join(
            f"{i}. {'Setiap hari' if len(r['days']) == 7 else ', '.join(DAY_NAMES[d] for d in r['days'])} "
            f"{r['at']} — {r['task']}" for i, r in enumerate(rt, 1))

    def routine_delete(self, n):
        with self._lock:
            rt = self.routines()
            if not (1 <= n <= len(rt)):
                return "Nombor rutin tak wujud."
            gone = rt.pop(n - 1)
            _save(self.rt_file, rt)
        return f"✔ Rutin dipadam: {gone['task']}"

    def routine_watch(self):
        while True:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                for r in self.routines():
                    hh, mm = map(int, r["at"].split(":"))
                    due = now.weekday() in r["days"] and (now.hour, now.minute) >= (hh, mm) \
                        and (now.hour * 60 + now.minute) - (hh * 60 + mm) <= 90 and r.get("last") != today
                    if due and not (getattr(self.api, "_chat_busy", False) or getattr(self.api, "_proc", None)):
                        with self._lock:
                            rt = self.routines()
                            for x in rt:
                                if x["id"] == r["id"]:
                                    x["last"] = today
                            _save(self.rt_file, rt)
                        self.notify("Rutin Jarvis", r["task"], "routine")
                        self.note(f"⏰ Rutin: {r['task']}")
                        self.api.run_text(r["task"])
            except Exception as ex:
                self.log(f"routine watch: {ex}")
            time.sleep(30)

    # ════════ 8. pemantau laman web ════════
    def sites(self):
        return self.cfg().get("monitor_urls") or [
            "https://akmalsys.com", "https://booking.akmalsys.com", "https://elawatan.akmalsys.com",
            "https://hatrik.akmalsys.com", "https://lencana.akmalsys.com", "https://rphsmart.akmalsys.com",
            "https://sipeng.akmalsys.com"]

    @staticmethod
    def _check(url):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Monitor/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status < 400, r.status, round((time.time() - t0) * 1000)
        except urllib.error.HTTPError as e:
            return e.code < 400 or e.code in (401, 403), e.code, round((time.time() - t0) * 1000)
        except Exception as e:
            return False, type(e).__name__, None

    def site_watch(self):
        time.sleep(40)
        while True:
            for url in self.sites():
                ok, code, ms = self._check(url)
                st = self.site_state.setdefault(url, {"up": True, "fails": 0})
                st.update(code=code, ms=ms, at=time.strftime("%H:%M"))
                if ok:
                    if not st["up"]:
                        self.notify("✅ Laman pulih", url.replace("https://", ""), "site")
                        self.note(f"✅ {url} kembali hidup")
                    st.update(up=True, fails=0)
                else:
                    st["fails"] += 1
                    if st["up"] and st["fails"] >= 2:          # 2 kali gagal berturut = betul-betul down
                        st["up"] = False
                        self.notify("⚠ Laman down", f"{url.replace('https://', '')} · {code}", "site")
                        self.note(f"⚠ {url} DOWN ({code})")
            time.sleep(int(self.cfg().get("monitor_minutes", 5)) * 60)

    @staticmethod
    def _norm_url(u):
        u = str(u or "").strip().rstrip("/")
        if not u:
            return ""
        return u if u.startswith(("http://", "https://")) else "https://" + u

    def monitor_add(self, url):
        u = self._norm_url(url)
        if not re.match(r"https?://[\w.-]+\.\w{2,}", u):
            return f"✖ «{url}» bukan alamat laman yang sah."
        c = self.cfg()
        urls = c.get("monitor_urls") or self.sites()
        if u in urls:
            return f"{u} memang sudah dipantau."
        c["monitor_urls"] = urls + [u]
        _save(self.root / "config.json", c)
        ok, code, ms = self._check(u)
        self.site_state[u] = {"up": ok, "fails": 0 if ok else 1, "code": code, "ms": ms, "at": time.strftime("%H:%M")}
        return f"✔ Dipantau setiap {c.get('monitor_minutes', 5)} minit: {u} — sekarang {'✅ hidup' if ok else '❌ ' + str(code)}"

    def monitor_remove(self, url):
        q = self._norm_url(url).replace("https://", "").replace("http://", "")
        c = self.cfg()
        urls = c.get("monitor_urls") or self.sites()
        keep = [u for u in urls if q not in u]
        if len(keep) == len(urls):
            return f"✖ {url} tiada dalam senarai pantau."
        c["monitor_urls"] = keep
        _save(self.root / "config.json", c)
        for u in list(self.site_state):
            if u not in keep:
                self.site_state.pop(u, None)
        return f"✔ Berhenti pantau: {', '.join(u for u in urls if u not in keep)}"

    def check_now(self, urls):
        out = []
        for u in [self._norm_url(x) for x in urls if str(x).strip()][:10]:
            ok, code, ms = self._check(u)
            out.append(f"{'✅' if ok else '❌'} {u.replace('https://', '')} · {code}" + (f" · {ms} ms" if ms else ""))
        return "\n".join(out)

    def site_report(self):
        if not self.site_state:
            out = []
            for url in self.sites():
                ok, code, ms = self._check(url)
                out.append(f"{'✅' if ok else '❌'} {url.replace('https://', '')} · {code}" + (f" · {ms} ms" if ms else ""))
            return "\n".join(out)
        return "\n".join(f"{'✅' if s['up'] else '❌'} {u.replace('https://', '')} · {s.get('code')}"
                         + (f" · {s['ms']} ms" if s.get("ms") else "") + f" · {s.get('at', '')}"
                         for u, s in self.site_state.items())

    # ════════ 9. deploy Firebase (perlu "ya") ════════
    def firebase_projects(self):
        found, seen = [], set()
        for _, root in self.api.web_roots():
            r = Path(root)
            if not r.is_dir():
                continue
            for fj in list(r.glob("firebase.json")) + list(r.glob("*/firebase.json")) + list(r.glob("*/*/firebase.json")):
                if "node_modules" in fj.parts:
                    continue
                k = str(fj.parent).lower()
                if k not in seen:
                    seen.add(k)
                    found.append(fj.parent)
        return found

    def deploy_request(self, name):
        q = re.sub(r"\W+", "", str(name).lower())
        cands = [p for p in self.firebase_projects() if q and (q in re.sub(r"\W+", "", p.name.lower())
                 or q in re.sub(r"\W+", "", p.parent.name.lower()))]
        if not cands:
            return f"✖ Tiada projek Firebase bernama «{name}»."
        if len(cands) > 1:
            short = [c for c in cands if re.sub(r"\W+", "", c.name.lower()) == q]
            cands = short or cands
        if len(cands) > 1 and len({c.name.lower() for c in cands}) == 1:
            cands = [min(cands, key=lambda c: len(c.parts))]      # HATRIK & HATRIK\HATRIK: yang paling atas
        if len(cands) > 1:
            return "Ada beberapa: " + "; ".join(str(c).split("Desktop\\")[-1] for c in cands[:6]) + \
                   ". Sebut nama yang lebih tepat."
        self.pending_deploy = {"path": cands[0], "until": time.time() + 120}
        return f"🚀 Deploy {cands[0].name} ({str(cands[0]).split('Desktop' + chr(92))[-1]}) ke Firebase? Jawab «ya» untuk teruskan."

    def deploy_confirmed(self):
        pend, self.pending_deploy = self.pending_deploy, None
        if not pend or time.time() > pend["until"]:
            return "✖ Permintaan deploy dah luput — minta semula."
        threading.Thread(target=self._deploy, args=(pend["path"],), daemon=True).start()
        return f"🚀 Deploy {pend['path'].name} bermula… (keputusan akan dihantar ke HUD & fon)"

    def _deploy(self, path):
        exe = shutil.which("firebase.cmd") or shutil.which("firebase") or "firebase.cmd"
        t0 = time.time()
        try:
            p = subprocess.run([exe, "deploy", "--non-interactive"], cwd=str(path), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=900, creationflags=NO_WINDOW, shell=False)
            out = (p.stdout + "\n" + p.stderr).strip()
            url = re.findall(r"Hosting URL:\s*(\S+)", out)
            ok = p.returncode == 0
            msg = (f"✔ Deploy {path.name} siap ({round(time.time() - t0)} s)" + (f" · {url[-1]}" if url else "")) if ok \
                else f"✖ Deploy {path.name} gagal: " + out.splitlines()[-1][:200] if out else "unknown"
        except Exception as e:
            ok, msg = False, f"✖ Deploy {path.name} gagal: {e}"
        self.note(msg)
        self.notify("Deploy " + ("siap" if ok else "gagal"), msg, "deploy")

    # ════════ 11. Malwarebytes: semak pautan / nombor / e-mel ════════
    MB_TOOLS = ["mcp__claude_ai_Malwarebytes__reputation-check_link", "mcp__claude_ai_Malwarebytes__reputation-check_email",
                "mcp__claude_ai_Malwarebytes__reputation-check_phone", "mcp__claude_ai_Malwarebytes__reputation-scan_all",
                "mcp__claude_ai_Malwarebytes__reputation-whois"]          # TIADA reputation-report (melapor keluar)
    SAFE_DOMAINS = ("google.com", "youtube.com", "youtu.be", "gov.my", "edu.my", "moe.gov.my", "akmalsys.com",
                    "facebook.com", "instagram.com", "whatsapp.com", "t.me", "telegram.org", "microsoft.com",
                    "office.com", "live.com", "apple.com", "wikipedia.org", "github.com", "canva.com", "zoom.us",
                    "forms.gle", "docs.google.com", "drive.google.com", "maps.app.goo.gl", "shopee.com.my", "lazada.com.my")
    _mb_cache = {}
    _mb_hour = []

    def scam_check(self, items):
        """items: senarai pautan/e-mel/nombor (E.164). Pulangkan [{item, verdict, note}]."""
        items = [str(i).strip() for i in items if str(i).strip()][:10]
        if not items:
            return []
        out = self.api._claude_quick(
            "Semak reputasi setiap item ini dengan Malwarebytes (pautan: check_link; e-mel: check_email; "
            "nombor telefon format E.164: check_phone; 3 item atau lebih: scan_all):\n" + "\n".join(items) +
            '\nBalas JSON SAHAJA: [{"item": "...", "verdict": "malicious|suspicious|safe|unknown", '
            '"note": "satu ayat BM: apa yang dijumpai"}]. JANGAN laporkan (report) apa-apa.',
            self.MB_TOOLS, model="haiku", timeout=120)
        m = re.search(r"\[[\s\S]*\]", str(out))
        try:
            return json.loads(m.group(0)) if m else []
        except Exception:
            return []

    @staticmethod
    def _domain(url):
        from urllib.parse import urlparse
        h = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h

    def scan_message(self, chat_name, text):
        """Mesej Telegram masuk: semak pautan yang bukan dari domain dipercayai. Amaran jika berbahaya."""
        urls = re.findall(r"(?:https?://|www\.)[^\s<>\"')\]]+", text or "", re.I)
        todo = []
        for u in dict.fromkeys(urls):
            d = self._domain(u)
            if not d or any(d == s or d.endswith("." + s) for s in self.SAFE_DOMAINS):
                continue
            c = self._mb_cache.get(d)
            if c and time.time() - c["at"] < 86400:
                if c["verdict"] in ("malicious", "suspicious"):
                    self._warn(chat_name, u, c)
                continue
            todo.append(u)
        if not todo or not self.cfg().get("tg_link_scan", True):
            return
        now = time.time()
        self._mb_hour[:] = [t for t in self._mb_hour if now - t < 3600]
        if len(self._mb_hour) >= int(self.cfg().get("tg_link_scan_per_hour", 20)):
            return                                     # siling: kumpulan yang bising tak menghabiskan kuota
        self._mb_hour.append(now)
        for r in self.scam_check(todo):
            d = self._domain(str(r.get("item", "")))
            v = str(r.get("verdict", "unknown")).lower()
            self._mb_cache[d] = {"verdict": v, "note": r.get("note", ""), "at": time.time()}
            if v in ("malicious", "suspicious"):
                self._warn(chat_name, r.get("item", ""), self._mb_cache[d])

    def _warn(self, chat_name, url, c):
        icon = "⛔" if c["verdict"] == "malicious" else "⚠"
        word = "BERBAHAYA" if c["verdict"] == "malicious" else "mencurigakan"
        msg = f"{icon} Pautan {word} dalam {chat_name}: {url} — {c.get('note', '')} Jangan klik."
        self.note(msg)
        self.notify(f"{icon} Pautan {word} · {chat_name}", f"{url} — jangan klik", "scam")

    # ════════ 12. Canva: poster, slaid, kad, sijil ════════
    CANVA_TOOLS = ["mcp__claude_ai_Canva"]

    def canva(self, request):
        d = Path(self.api.known_folder_path("Documents")) / "Jarvis Canva"
        d.mkdir(parents=True, exist_ok=True)
        out = self.api._claude_quick(
            f"Guna Canva Tuan. Permintaan: {request}\n{self.memory_note()}\n"
            "1. Reka bentuk yang sesuai (poster/slaid/kad/sijil/infografik) dalam Bahasa Melayu, gaya kemas dan "
            "profesional. Jika ada templat jenama (brand template) yang sesuai, guna itu; jika tidak, jana reka bentuk "
            "baru dan pilih calon terbaik.\n"
            "2. Eksport sebagai PDF (atau PNG untuk poster media sosial).\n"
            "3. Balas dengan: tajuk reka bentuk, PAUTAN EDIT Canva, dan PAUTAN MUAT TURUN eksport (URL penuh).",
            self.CANVA_TOOLS, model="sonnet", timeout=420)
        saved = []
        for url in re.findall(r"https://[^\s)\]\"'>]+", str(out)):
            if re.search(r"\.(pdf|png|jpe?g|zip)(\?|$)", url, re.I) or "export" in url.lower():
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Jarvis"}),
                                                timeout=120) as r:
                        ext = re.search(r"\.(pdf|png|jpe?g|zip)", url, re.I)
                        name = re.sub(r"[^\w\- ]+", "", str(request))[:50].strip() or "Canva"
                        f = d / f"{name} {datetime.now():%Y-%m-%d %H%M}.{ext.group(1).lower() if ext else 'pdf'}"
                        f.write_bytes(r.read())
                        saved.append(str(f))
                except Exception:
                    pass
        return out, saved

    # ════════ 10. backup ke OneDrive (salinan berperingkat) ════════
    def backup(self, quiet=False):
        import os
        od = os.environ.get("OneDrive")
        if not od:
            return "✖ OneDrive tiada pada laptop ini."
        srcs = self.cfg().get("backup_sources") or [str(Path.home() / "Desktop")]
        dest_root = Path(od) / "Jarvis Backup"
        t0, copied, failed = time.time(), 0, 0
        for src in srcs:
            s = Path(src)
            if not s.is_dir():
                continue
            p = subprocess.run(
                ["robocopy", str(s), str(dest_root / s.name), "/E", "/XO", "/R:1", "/W:1", "/MT:8", "/NP", "/NFL", "/NDL",
                 "/XD", "node_modules", ".git", "vendor", "dist", "build", ".next", "media", "__pycache__", ".venv",
                 "venv", "runtime", ".cloudflared", "/XF", "*.tmp", "~$*", "secrets.json", ".env", "*.pem", "*.key"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            m = re.search(r"Files\s*:\s*\d+\s+(\d+)\s+\d+\s+\d+\s+(\d+)", p.stdout)
            if m:
                copied += int(m.group(1))
                failed += int(m.group(2))
        data = _load(self.root / "cache.json", {})
        data["backup_at"] = time.time()
        _save(self.root / "cache.json", data)
        msg = f"✔ Backup siap ({round(time.time() - t0)} s): {copied} fail disalin ke OneDrive\\Jarvis Backup" + \
              (f", {failed} gagal" if failed else "")
        if not quiet:
            self.note(msg)
        self.notify("Backup", msg, "backup")
        return msg

    def backup_watch(self):
        """Seminggu sekali (lalai), bila laptop hidup dan Jarvis tidak sibuk."""
        time.sleep(300)
        while True:
            try:
                days = float(self.cfg().get("backup_every_days", 7))
                last = float(_load(self.root / "cache.json", {}).get("backup_at") or 0)
                if days > 0 and time.time() - last > days * 86400 and not getattr(self.api, "_chat_busy", False):
                    self.backup(quiet=True)
            except Exception as ex:
                self.log(f"backup watch: {ex}")
            time.sleep(3600)
