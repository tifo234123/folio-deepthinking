import json
import pytest
import pymupdf
from folio.app import App
from folio.providers import ProviderError
from folio.research import normalized
from conftest import FixtureProvider


def test_quote_validation_preserves_case():
    assert normalized("Q = A  v\n") == "Q = A v"
    assert normalized("Q") != normalized("q")


def test_page_labels_are_separate_from_pdf_indices(app, tmp_path):
    path = tmp_path / "labels.pdf"
    d = pymupdf.open()
    for i in range(3):
        p = d.new_page()
        p.insert_text((40, 80), f"Page content number {i}. This is enough text to be readable.")
    d.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                       {"startpage": 2, "prefix": "", "style": "D", "firstpagenum": 1}])
    d.save(path); d.close()
    b, _ = app.library.import_pdf(path)
    app.library.prepare(b["id"])
    pages = app.db.rows("SELECT page,label FROM pages WHERE book_id=? ORDER BY page", (b["id"],))
    assert pages == [{"page": 1, "label": "i"}, {"page": 2, "label": "ii"}, {"page": 3, "label": "1"}]


def test_process_lock_and_interrupted_job_recovery(tmp_path, pdf):
    home = tmp_path / "recovery"
    with App(home, FixtureProvider) as app:
        with pytest.raises(RuntimeError, match="already"): App(home)
        app.config.save("ollama", "fixture")
        b, _ = app.library.import_pdf(pdf)
        app.library.prepare(b["id"])
        job = app.jobs.create(b["id"], "extract", app.research.extraction_payload(b["id"]), background=False)
        jid = job["id"]
    # Simulate a crash marker without rerunning previously completed units.
    import sqlite3
    with sqlite3.connect(home / "folio.sqlite3") as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    with App(home, FixtureProvider) as restored:
        assert restored.jobs.get(jid)["status"] == "interrupted"
        count = len(restored.research.findings(b["id"]))
        assert restored.jobs.resume(jid, background=False)["status"] == "done"
        assert len(restored.research.findings(b["id"])) == count


def test_failed_provider_keeps_saved_work_accessible(app, book):
    class Offline(FixtureProvider):
        def complete(self, *a, **k): raise ProviderError("Cannot connect")
    app.research.provider_factory = Offline
    job = app.jobs.create(book["id"], "extract", app.research.extraction_payload(book["id"]), background=False)
    assert job["status"] == "failed" and job["completed"] == 0
    assert app.library.books() and app.library.search(book["id"], "pressure")
    assert app.library.book(book["id"])["status"] != "failed"


def test_model_change_blocks_resume(app, book):
    class Offline(FixtureProvider):
        def complete(self, *a, **k): raise ProviderError("Cannot connect")
    app.research.provider_factory = Offline
    job = app.jobs.create(book["id"], "extract", app.research.extraction_payload(book["id"]), background=False)
    app.config.save("ollama", "different-model")
    job = app.jobs.resume(job["id"], background=False)
    assert job["status"] == "failed" and "settings changed" in job["error"]


def test_assistant_tool_execution_and_cross_book_rejection(app, book, tmp_path):
    source = app.library.passages(book["id"])[-1]
    class ToolProvider(FixtureProvider):
        def complete(self, system, messages, **kwargs):
            body = json.loads(messages[-1]["content"])
            if "context" in body:
                return json.dumps({"parts": [], "action": {"tool": "search", "arguments": {"query": "pressure", "scope": "book"}}})
            pid = body["result"]["sources"][0]["id"]
            return json.dumps({"parts": [{"text": "Membrane filtration requires pressure.", "kind": "source", "source_ids": [pid]}]})
    app.assistant.provider_factory = ToolProvider
    section = app.library.sections(book["id"])[0]["id"]
    result = app.assistant.ask("Find membrane requirements", book["id"], section)
    assert any(s["page"] == 3 for s in result["sources"])
    with pytest.raises(ValueError): app.assistant._tool("navigate", {"section_id": "not-this-book"}, book["id"], None)
    with pytest.raises(ValueError): app.assistant._tool("read_source", {"source_id": source["id"]}, "different-book", None)
    with pytest.raises(ValueError): app.assistant._tool("search", {"query": "x", "sql": "DELETE"}, book["id"], None)
    with pytest.raises(ValueError): app.assistant._tool("extract", {"scope": "book"}, None, None)


def test_manual_hierarchy_cycles_and_dangling_sources_rejected(app, book):
    pid = app.library.passages(book["id"])[0]["id"]
    with pytest.raises(ValueError, match="earlier"):
        app.research.save_structure(book["id"], {"name": "Cycle", "sections": [{"title": "Cycle", "parent_index": 0, "source_ids": [pid]}]})
    assert len(app.db.rows("SELECT * FROM structures WHERE book_id=?", (book["id"],))) == 1


def test_assistant_reorganization_is_only_a_proposal(app, book):
    class Reorganizer(FixtureProvider):
        def complete(self, system, messages, **kwargs):
            body = json.loads(messages[-1]["content"])
            if "source_descriptors" in body:
                sources = body["source_descriptors"]
                return json.dumps({"name": "By theme", "sections": [{"title": "Selected evidence", "source_ids": [sources[0]["id"], sources[-1]["id"]]}]})
            if "context" in body:
                return json.dumps({"action": {"tool": "propose_structure", "arguments": {"request": "Organize by theme"}}})
            assert body["success"] is True
            return json.dumps({"parts": [{"text": "A proposal is saved for your review. It has not been applied.", "kind": "status", "source_ids": []}]})
    app.assistant.provider_factory = Reorganizer
    app.research.provider_factory = Reorganizer
    result = app.assistant.ask("Organize this book by theme", book["id"])
    proposal = result["events"][0]["result"]["structure_id"]
    assert app.library.book(book["id"])["active_structure"] == book["active_structure"]
    assert app.db.one("SELECT applied FROM structures WHERE id=?", (proposal,))["applied"] == 0
    app.research.apply_structure(book["id"], proposal)
    assert app.library.book(book["id"])["active_structure"] == proposal
    assert app.research.undo_structure(book["id"]) == book["active_structure"]
