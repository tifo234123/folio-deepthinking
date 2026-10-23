import json
from pathlib import Path
import pytest
import pymupdf
from folio.app import App
from folio.config import Config
from folio.providers import Provider, ProviderError
from conftest import FixtureProvider


def test_import_is_durable_and_deduplicated(app, pdf, book):
    before = pdf.read_bytes()
    duplicate, created = app.library.import_pdf(pdf)
    assert not created and duplicate["id"] == book["id"]
    assert pdf.read_bytes() == before
    assert Path(book["path"]).read_bytes() == before
    app.library.set_subjects(book["id"], ["Water", "Engineering / Water"])
    assert len(app.library.books()) == 1
    assert len(list(app.config.library.glob("*.pdf"))) == 1
    assert app.library.search(book["id"], "pressure")[0]["page"] == 3


def test_sections_source_labels_and_scoping(app, book, pdf):
    sections = app.library.sections(book["id"])
    assert sections[2]["parent_id"] == sections[1]["id"]
    assert sections[1]["pages"] == [2, 3]
    assert not app.library.search(book["id"], "pressure", sections[0]["id"])
    assert app.library.search(book["id"], "pressure")
    with pytest.raises(ValueError): app.library.passages(book["id"], "bogus")


def test_long_document_not_truncated_and_image_only_flagged(app, tmp_path):
    path = tmp_path / "long.pdf"
    doc = pymupdf.open()
    for i in range(100):
        page = doc.new_page()
        page.insert_textbox((40, 40, 550, 780), (f"Page {i + 1} technical content and relevant measurements. " * 25), fontsize=10)
    doc.new_page()  # Empty/scanned-equivalent extraction failure.
    doc.save(path)
    doc.close()
    b, _ = app.library.import_pdf(path)
    result = app.library.prepare(b["id"])
    pages = app.db.rows("SELECT * FROM pages WHERE book_id=?", (b["id"],))
    assert len(pages) == 101 and sum(len(p["text"]) for p in pages) > 60000
    assert result["status"] == "needs_attention"
    assert any(w["page"] == 101 for w in json.loads(result["warnings"]))
    assert any(p["page"] == 100 for p in app.library.search(b["id"], '"100"'))


def test_encrypted_and_corrupt_pdf_fail_clearly(app, tmp_path):
    corrupt = tmp_path / "bad.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a valid document")
    b, _ = app.library.import_pdf(corrupt)
    j = app.jobs.create(b["id"], "prepare", background=False)
    assert j["status"] == "failed" and app.library.book(b["id"])["status"] == "failed"
    locked = tmp_path / "locked.pdf"
    d = pymupdf.open(); d.new_page()
    d.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="password"); d.close()
    b, _ = app.library.import_pdf(locked)
    j = app.jobs.create(b["id"], "prepare", background=False)
    assert "encrypted" in j["error"]


def test_atomic_config_keeps_unrelated_and_key_private(tmp_path, monkeypatch):
    c = Config(tmp_path)
    c.path.write_text("# user comment\nUNRELATED='keep me'\n")
    key = "special'key\\with $characters\nnewline"
    c.save("nvidia", "chosen/model", key=key)
    assert c.get().key == key
    assert c.values()["UNRELATED"] == "keep me"
    c.save("openrouter", "another/model", key="router-key", activate=False)
    assert c.get().provider == "nvidia"
    assert key not in json.dumps(c.get().public())
    assert c.path.stat().st_mode & 0o777 == 0o600
    before = c.path.read_bytes()
    import folio.config
    monkeypatch.setattr(folio.config.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("save failed")))
    with pytest.raises(OSError): c.save("ollama", "new")
    assert c.path.read_bytes() == before


def test_extraction_notes_and_restart(tmp_path, pdf):
    home = tmp_path / "durable"
    with App(home, FixtureProvider) as app:
        app.config.save("ollama", "fixture")
        b, _ = app.library.import_pdf(pdf)
        app.library.prepare(b["id"])
        pid = app.library.passages(b["id"])[0]["id"]
        note = app.library.save_note(b["id"], "My interpretation", [pid])
        for _ in range(2):
            job = app.jobs.create(b["id"], "extract", app.research.extraction_payload(b["id"]), background=False)
            assert job["status"] == "done" and job["completed"] == job["total"]
    with App(home, FixtureProvider) as restored:
        assert restored.config.get().model == "fixture"
        assert restored.library.source(b["id"], pid)
        assert restored.db.one("SELECT text FROM notes WHERE id=?", (note,))["text"] == "My interpretation"
        assert restored.research.findings(b["id"])


def test_invalid_evidence_rejected_and_retry_preserves_progress(app, book):
    calls = [0]
    class BadOnce(FixtureProvider):
        def complete(self, *args, **kwargs):
            calls[0] += 1
            good = json.loads(super().complete(*args, **kwargs))
            if calls[0] == 2:
                good["findings"][0]["evidence"][0]["quote"] = "hallucinated evidence"
            return json.dumps(good)
    app.research.provider_factory = BadOnce
    job = app.jobs.create(book["id"], "extract", app.research.extraction_payload(book["id"]), background=False)
    assert job["status"] == "failed" and job["completed"] == 1
    completed_ids = {f["id"] for f in app.research.findings(book["id"])}
    app.research.provider_factory = FixtureProvider
    job = app.jobs.resume(job["id"], background=False)
    assert job["status"] == "done"
    assert completed_ids <= {f["id"] for f in app.research.findings(book["id"])}
    assert len(app.research.findings(book["id"])) == job["total"]


def test_structure_proposal_preserves_noncontiguous_sources_and_undo(app, book):
    all_sources = app.library.passages(book["id"])
    ids = [all_sources[0]["id"], all_sources[-1]["id"]]
    original = book["active_structure"]
    result = app.research.save_structure(book["id"], {"name": "My research", "sections": [{"title": "Across chapters", "source_ids": ids}]})
    assert app.library.book(book["id"])["active_structure"] == original
    assert set(result["sections"][0]["source_ids"]) == set(ids)
    assert len(result["sections"]) == 2  # Unmapped material retained.
    app.research.apply_structure(book["id"], result["structure_id"])
    assert app.library.book(book["id"])["active_structure"] == result["structure_id"]
    assert app.research.undo_structure(book["id"]) == original
    with pytest.raises(ValueError):
        app.research.save_structure(book["id"], {"name": "bad", "sections": [{"title": "bad", "source_ids": ["fake"]}]})


def test_chat_citations_and_history(app, book):
    result = app.assistant.ask("pressure", book["id"])
    assert result["parts"][0]["source_ids"]
    assert len(app.assistant.history(book["id"])) == 2
    assert app.assistant.history() == []
    class Fabricator(FixtureProvider):
        def complete(self, *args, **kwargs):
            return json.dumps({"parts": [{"text": "Invented claim", "kind": "source", "source_ids": ["unknown"]}]})
    app.assistant.provider_factory = Fabricator
    with pytest.raises(ValueError, match="unseen"): app.assistant.ask("pressure", book["id"])


def test_removal_preserves_original(app, book, pdf):
    app.library.remove(book["id"], delete_managed=True)
    assert pdf.exists() and not Path(book["path"]).exists()
    assert not app.db.rows("SELECT * FROM passage_search")


def test_cancellation_keeps_completed_and_resume(app, book):
    calls = [0]
    class Cancelling(FixtureProvider):
        def complete(self, *a, **k):
            calls[0] += 1
            result = super().complete(*a, **k)
            if calls[0] == 2:
                j = app.db.one("SELECT id FROM jobs WHERE kind='extract' AND status='running'")
                app.jobs.cancel(j["id"])
            return result
    app.research.provider_factory = Cancelling
    job = app.jobs.create(book["id"], "extract", app.research.extraction_payload(book["id"]), background=False)
    assert job["status"] == "cancelled" and job["completed"] == 1
    app.research.provider_factory = FixtureProvider
    assert app.jobs.resume(job["id"], background=False)["status"] == "done"

