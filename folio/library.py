from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import tempfile
from filelock import FileLock
from .db import uid, now
from .pdf_worker import read_pdf_isolated


class Library:
    def __init__(self, db, config):
        self.db, self.config = db, config

    def book(self, book_id):
        result = self.db.one("SELECT * FROM books WHERE id=?", (book_id,))
        if not result:
            raise ValueError("Book not found")
        return result

    def books(self, query="", subject=None):
        sql = "SELECT b.*, group_concat(s.name, ', ') subjects FROM books b LEFT JOIN book_subjects bs ON b.id=bs.book_id LEFT JOIN subjects s ON s.id=bs.subject_id WHERE (b.title LIKE ? OR b.author LIKE ?)"
        args = [f"%{query}%", f"%{query}%"]
        if subject:
            sql += " AND b.id IN (SELECT book_id FROM book_subjects WHERE subject_id=?)"
            args.append(subject)
        return self.db.rows(sql + " GROUP BY b.id ORDER BY b.created DESC", args)

    def import_pdf(self, path):
        path = Path(path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise ValueError("Choose a PDF file")
        storage = self.config.library
        storage.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.config.home / "import.lock")):
            fd, tmp = tempfile.mkstemp(dir=storage, suffix=".partial")
            temp = Path(tmp)
            try:
                digest = hashlib.sha256()
                with path.open("rb") as src, os.fdopen(fd, "wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        digest.update(chunk)
                        dst.write(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                value = digest.hexdigest()
                existing = self.db.one("SELECT * FROM books WHERE digest=?", (value,))
                if existing:
                    return existing, False
                with temp.open("rb") as check:
                    if b"%PDF-" not in check.read(1024):
                        raise ValueError("File does not have a PDF header")
                target = storage / (value + ".pdf")
                os.replace(temp, target)
                book_id = uid()
                self.db.execute("INSERT INTO books(id,digest,title,author,filename,path,status,created) VALUES(?,?,?,?,?,?,?,?)",
                    (book_id, value, path.stem, "", path.name, str(target), "imported", now()))
                return self.book(book_id), True
            finally:
                temp.unlink(missing_ok=True)

    def scan(self, folder):
        results = []
        # Snapshot file list before importing, so managed copies cannot feed back.
        for path in sorted(Path(folder).expanduser().glob("*.pdf")):
            try:
                book, created = self.import_pdf(path)
                results.append({"file": path.name, "book_id": book["id"], "created": created})
            except (ValueError, OSError) as exc:
                results.append({"file": path.name, "error": str(exc)})
        return results

    def prepare(self, book_id, progress=lambda d, t: None, cancelled=lambda: False):
        book = self.book(book_id)
        if self.db.one("SELECT id FROM passages WHERE book_id=? LIMIT 1", (book_id,)):
            return book  # Never invalidate existing notes/source identifiers on retry.
        self.db.execute("UPDATE books SET status='processing', error=NULL WHERE id=?", (book_id,))
        try:
            result = read_pdf_isolated(book["path"], progress, cancelled)
            if cancelled():
                raise InterruptedError("Preparation cancelled")
            structure_id = uid()
            warnings = [{"page": p["page"], "warnings": p["warnings"]} for p in result["pages"] if p["warnings"]]
            has_text = any(p["text"].strip() for p in result["pages"])
            status = "needs_attention" if warnings or not has_text else "ready"
            with self.db.connect() as db:
                db.execute("DELETE FROM pages WHERE book_id=?", (book_id,))
                db.execute("DELETE FROM structures WHERE book_id=?", (book_id,))
                page_ids = {}
                for p in result["pages"]:
                    db.execute("INSERT INTO pages VALUES(?,?,?,?,?)", (book_id, p["page"], p["label"], p["text"], json.dumps(p["warnings"])))
                    page_ids[p["page"]] = []
                    for position, passage in enumerate(p["passages"]):
                        pid = uid()
                        page_ids[p["page"]].append(pid)
                        db.execute("INSERT INTO passages VALUES(?,?,?,?,?,?,?)", (pid, book_id, p["page"], p["label"], position, passage["text"], json.dumps(passage["bbox"])))
                        db.execute("INSERT INTO passage_search VALUES(?,?,?)", (pid, book_id, passage["text"]))
                db.execute("INSERT INTO structures VALUES(?,?,?,?,?,?)", (structure_id, book_id, "Original chapters", 1, 1, now()))
                section_ids = [uid() for _ in result["sections"]]
                for i, section in enumerate(result["sections"]):
                    sid = section_ids[i]
                    parent = section_ids[section["parent"]] if section["parent"] is not None else None
                    db.execute("INSERT INTO sections VALUES(?,?,?,?,?,?)", (sid, structure_id, section["title"], parent, i, section["origin"]))
                    for page in range(section["start"], section["end"] + 1):
                        db.executemany("INSERT OR IGNORE INTO section_passages VALUES(?,?)", [(sid, p) for p in page_ids[page]])
                db.execute("UPDATE books SET title=?,author=?,status=?,page_count=?,warnings=?,active_structure=?,error=NULL WHERE id=?",
                           (result["title"] or book["title"], result["author"], status, len(result["pages"]), json.dumps(warnings), structure_id, book_id))
            return self.book(book_id)
        except Exception as exc:
            self.db.execute("UPDATE books SET status=?,error=? WHERE id=?", ("imported" if isinstance(exc, InterruptedError) else "failed", str(exc), book_id))
            raise

    def sections(self, book_id, structure_id=None):
        book = self.book(book_id)
        structure_id = structure_id or book["active_structure"]
        if not structure_id:
            return []
        if not self.db.one("SELECT id FROM structures WHERE id=? AND book_id=?", (structure_id, book_id)):
            raise ValueError("Structure does not belong to this book")
        result = self.db.rows("SELECT * FROM sections WHERE structure_id=? ORDER BY position", (structure_id,))
        for s in result:
            passages = self.passages(book_id, s["id"])
            s["pages"] = sorted({p["page"] for p in passages})
            s["source_ids"] = [p["id"] for p in passages]
        return result

    def passages(self, book_id, section_id=None):
        self.book(book_id)
        if section_id:
            if not self.db.one("SELECT s.id FROM sections s JOIN structures t ON t.id=s.structure_id WHERE s.id=? AND t.book_id=?", (section_id, book_id)):
                raise ValueError("Section does not belong to this book")
            return self.db.rows("SELECT p.* FROM passages p JOIN section_passages s ON s.passage_id=p.id WHERE p.book_id=? AND s.section_id=? ORDER BY p.page,p.position", (book_id, section_id))
        return self.db.rows("SELECT * FROM passages WHERE book_id=? ORDER BY page,position", (book_id,))

    def source(self, book_id, source_id):
        source = self.db.one("SELECT * FROM passages WHERE id=? AND book_id=?", (source_id, book_id))
        if not source:
            raise ValueError("Source is not in the current book")
        return source

    def search(self, book_id, query, section_id=None, limit=12):
        self.book(book_id)
        terms = re.findall(r"\w+", query, re.UNICODE)[:24]
        if not terms:
            return []
        expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        sql = "SELECT p.*, bm25(passage_search) score FROM passage_search JOIN passages p ON p.id=passage_search.id WHERE passage_search MATCH ? AND p.book_id=?"
        args = [expression, book_id]
        if section_id:
            self.passages(book_id, section_id)  # Validate scope before retrieval.
            sql += " AND p.id IN (SELECT passage_id FROM section_passages WHERE section_id=?)"
            args.append(section_id)
        return self.db.rows(sql + " ORDER BY score LIMIT ?", args + [min(50, max(1, limit))])

    def set_subjects(self, book_id, names):
        self.book(book_id)
        with self.db.connect() as db:
            db.execute("DELETE FROM book_subjects WHERE book_id=?", (book_id,))
            for name in dict.fromkeys(n.strip() for n in names if n.strip()):
                db.execute("INSERT OR IGNORE INTO subjects VALUES(?,?)", (uid(), name))
                sid = db.execute("SELECT id FROM subjects WHERE name=?", (name,)).fetchone()[0]
                db.execute("INSERT INTO book_subjects VALUES(?,?)", (book_id, sid))

    def save_note(self, book_id, text, source_ids=(), note_id=None):
        self.book(book_id)
        if not text.strip():
            raise ValueError("Note cannot be empty")
        for source in source_ids:
            self.source(book_id, source)
        if note_id:
            if not self.db.one("SELECT id FROM notes WHERE id=? AND book_id=?", (note_id, book_id)):
                raise ValueError("Note not found")
            self.db.execute("UPDATE notes SET text=?,source_ids=?,updated=? WHERE id=?", (text, json.dumps(list(source_ids)), now(), note_id))
        else:
            note_id = uid()
            self.db.execute("INSERT INTO notes VALUES(?,?,?,?,?,?)", (note_id, book_id, text, json.dumps(list(source_ids)), now(), now()))
        return note_id

    def remove(self, book_id, delete_managed=False):
        book = self.book(book_id)
        if self.db.one("SELECT id FROM jobs WHERE book_id=? AND status IN ('running','queued','cancelling')", (book_id,)):
            raise ValueError("Cancel active jobs before removing this book")
        if delete_managed:
            path = Path(book["path"])
            if path.name != book["digest"] + ".pdf":
                raise ValueError("Refusing to delete a file outside managed naming rules")
            path.unlink(missing_ok=True)
        with self.db.connect() as db:
            db.execute("DELETE FROM messages WHERE scope=?", (book_id,))
            db.execute("DELETE FROM books WHERE id=?", (book_id,))
