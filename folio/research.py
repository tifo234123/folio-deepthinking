import json
import hashlib
import re
from pathlib import Path
from .db import uid, now
from .providers import Provider, parse_json
from .schemas import Extraction, StructureSpec, SectionSpec
from .deep import DeepResearch

PROMPTS = Path(__file__).parent / "prompts"


def prompt(name):
    return (PROMPTS / "core.md").read_text() + "\n\n" + (PROMPTS / (name + ".md")).read_text()


def normalized(text):
    return " ".join(text.split())


class Research(DeepResearch):
    def __init__(self, db, config, library, provider_factory=Provider):
        self.db, self.config, self.library = db, config, library
        self.provider_factory = provider_factory

    def extraction_payload(self, book_id, section_ids=None, focus=""):
        sources = {}
        if section_ids:
            for section_id in section_ids:
                sources.update({p["id"]: p for p in self.library.passages(book_id, section_id)})
        else:
            sources = {p["id"]: p for p in self.library.passages(book_id)}
        if not sources:
            raise ValueError("No readable passages. Prepare the book or review pages requiring OCR.")
        settings = self.config.get()
        if not settings.model:
            raise ValueError("Choose and test an AI model first")
        return {"source_ids": list(sources), "focus": focus, "provider": settings.provider,
                "model": settings.model, "endpoint": settings.endpoint, "section_ids": section_ids or []}

    def run_extraction(self, job, cancelled=lambda: False):
        payload = json.loads(job["payload"])
        if payload.get("mode") == "deep": return self.run_deep(job, cancelled)
        settings = self.config.get(payload["provider"])
        if settings.model != payload["model"] or settings.endpoint != payload["endpoint"]:
            raise ValueError("Provider settings changed since this job was created. Restore them to resume, or start a new extraction.")
        provider = self.provider_factory(settings)
        instruction = prompt("extract")
        version = hashlib.sha256(instruction.encode()).hexdigest()[:12]
        # One source per durable unit: successful units survive cancellation/restart.
        pending = self.db.rows("SELECT passage_id FROM job_units WHERE job_id=? AND status!='done'", (job["id"],))
        errors = []
        for item in pending:
            if cancelled():
                raise InterruptedError("Extraction cancelled; completed findings are saved")
            pid = item["passage_id"]
            source = self.library.source(job["book_id"], pid)
            try:
                user = json.dumps({"focus": payload["focus"], "sources": [source]}, ensure_ascii=False)
                raw = provider.complete(instruction, [{"role": "user", "content": user}])
                output = Extraction.model_validate(parse_json(raw))
                for finding in output.findings:
                    for evidence in finding.evidence:
                        if evidence.source_id != pid or normalized(evidence.quote) not in normalized(source["text"]):
                            raise ValueError("Model supplied an invalid source or quotation; this passage needs retry")
                if cancelled():
                    raise InterruptedError("Extraction cancelled; completed findings are saved")
                with self.db.connect() as db:
                    for f in output.findings:
                        db.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                            uid(), job["id"], job["book_id"], f.category, f.title, f.content,
                            json.dumps(f.details, ensure_ascii=False), json.dumps([e.model_dump() for e in f.evidence], ensure_ascii=False),
                            settings.provider, settings.model, version, now()))
                    db.execute("UPDATE job_units SET status='done',error=NULL WHERE job_id=? AND passage_id=?", (job["id"], pid))
                    count = db.execute("SELECT count(*) FROM job_units WHERE job_id=? AND status='done'", (job["id"],)).fetchone()[0]
                    db.execute("UPDATE jobs SET completed=?,updated=? WHERE id=?", (count, now(), job["id"]))
            except InterruptedError:
                raise
            except Exception as exc:
                # Pydantic errors can contain model data; use a concise redacted failure.
                error = "Invalid structured model response" if type(exc).__module__.startswith("pydantic") else str(exc)
                self.db.execute("UPDATE job_units SET status='failed',error=? WHERE job_id=? AND passage_id=?", (error, job["id"], pid))
                errors.append(error)
                # Stop on the first failed call; avoid a stream of failed paid requests.
                break
        if errors:
            raise ValueError(errors[0] + ". Completed units remain saved; resume to retry the remaining passages.")

    def findings(self, book_id, section_id=None, job_id=None):
        allowed = {p["id"] for p in self.library.passages(book_id, section_id)}
        args = [book_id]
        sql = "SELECT * FROM findings WHERE book_id=?"
        if job_id:
            sql += " AND job_id=?"
            args.append(job_id)
        result = []
        for row in self.db.rows(sql + " ORDER BY created DESC", args):
            row["sources"] = json.loads(row["sources"])
            row["details"] = json.loads(row["details"])
            if any(e["source_id"] in allowed for e in row["sources"]):
                result.append(row)
        return result

    def coverage(self, book_id):
        book = self.library.book(book_id)
        sources = self.library.passages(book_id)
        done = self.db.rows("SELECT DISTINCT u.passage_id FROM job_units u JOIN jobs j ON j.id=u.job_id WHERE j.book_id=? AND u.status='done'", (book_id,))
        return {"readable_passages": len(sources), "extracted_passages_any_run": len(done),
                "pdf_pages": book["page_count"], "warnings": json.loads(book["warnings"]),
                "jobs": self.db.rows("SELECT id,status,completed,total,error FROM jobs WHERE book_id=? AND kind='extract' ORDER BY created DESC", (book_id,)),
                "note": "Coverage is tracked per extraction job. Prior runs with different focus do not prove exhaustive coverage for a new question."}

    def save_structure(self, book_id, spec, origin="Assistant proposal"):
        spec = StructureSpec.model_validate(spec)
        sources = {p["id"] for p in self.library.passages(book_id)}
        used = set()
        for i, section in enumerate(spec.sections):
            if section.parent_index is not None and not 0 <= section.parent_index < i:
                raise ValueError("A parent must refer to an earlier section")
            if any(pid not in sources for pid in section.source_ids):
                raise ValueError("A proposed section refers to a source outside this book")
            used.update(section.source_ids)
        # No accidental data loss: keep all unmapped passages discoverable.
        missing = sources - used
        if missing:
            spec.sections.append(SectionSpec(title="Other original material", source_ids=sorted(missing)))
        sid = uid()
        ids = [uid() for _ in spec.sections]
        with self.db.connect() as db:
            db.execute("INSERT INTO structures VALUES(?,?,?,?,?,?)", (sid, book_id, spec.name, 0, 0, now()))
            for i, section in enumerate(spec.sections):
                db.execute("INSERT INTO sections VALUES(?,?,?,?,?,?)", (ids[i], sid, section.title,
                    ids[section.parent_index] if section.parent_index is not None else None, i, origin))
                db.executemany("INSERT OR IGNORE INTO section_passages VALUES(?,?)", [(ids[i], pid) for pid in section.source_ids])
        return {"structure_id": sid, "name": spec.name, "status": "proposal", "sections": self.library.sections(book_id, sid)}

    def propose_structure(self, book_id, request):
        sources = self.library.passages(book_id)
        if not sources:
            raise ValueError("Prepare the book before reorganizing it")
        settings = self.config.get()
        # A proposal receives bounded descriptors, never silently claims full reading.
        descriptors = [{"id": p["id"], "page": p["page"], "excerpt": p["text"][:160]} for p in sources]
        body = json.dumps({"request": request, "source_descriptors": descriptors}, ensure_ascii=False)
        if len(body) + len(prompt("structure")) > settings.input_chars:
            from .group_structure import propose_grouped
            return propose_grouped(self, book_id, request, settings)
        raw = self.provider_factory(settings).complete(prompt("structure"), [{"role": "user", "content": body}])
        return self.save_structure(book_id, parse_json(raw))

    def apply_structure(self, book_id, structure_id):
        book = self.library.book(book_id)
        if not self.db.one("SELECT id FROM structures WHERE id=? AND book_id=?", (structure_id, book_id)):
            raise ValueError("Structure not found in this book")
        with self.db.connect() as db:
            db.execute("INSERT INTO structure_history(book_id,from_id,to_id,created) VALUES(?,?,?,?)", (book_id, book["active_structure"], structure_id, now()))
            db.execute("UPDATE structures SET applied=1 WHERE id=?", (structure_id,))
            db.execute("UPDATE books SET active_structure=? WHERE id=?", (structure_id, book_id))

    def undo_structure(self, book_id):
        self.library.book(book_id)
        history = self.db.one("SELECT * FROM structure_history WHERE book_id=? ORDER BY id DESC LIMIT 1", (book_id,))
        if not history:
            raise ValueError("No structure change to undo")
        with self.db.connect() as db:
            db.execute("UPDATE books SET active_structure=? WHERE id=?", (history["from_id"], book_id))
            db.execute("DELETE FROM structure_history WHERE id=?", (history["id"],))
        return history["from_id"]
