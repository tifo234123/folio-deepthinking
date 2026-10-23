import json
import pytest
import pymupdf
from folio.app import App


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "Water research.pdf"
    doc = pymupdf.open()
    for title, text in [
        ("1. Introduction", "Water treatment removes contaminants. Removal efficiency reached 95% at pH 7 in a laboratory batch test."),
        ("2. Filtration", "Sand filtration passes water through granular media. Q = A v. Q denotes volumetric discharge."),
        ("2.1 Membranes", "Membrane filtration requires pressure. A membrane separates particles from water. Conditions vary by pore size."),
    ]:
        page = doc.new_page()
        page.insert_text((50, 60), title, fontsize=20)
        page.insert_textbox((50, 110, 540, 700), text, fontsize=12)
    doc.set_metadata({"title": "Water research fixture", "author": "Synthetic test fixture"})
    doc.set_toc([[1, "Introduction", 1], [1, "Filtration", 2], [2, "Membranes", 3]])
    doc.save(path)
    doc.close()
    return path


class FixtureProvider:
    def __init__(self, settings): self.settings = settings
    def complete(self, system, messages, max_tokens=None, **kwargs):
        body = json.loads(messages[-1]["content"])
        if "sources" in body:
            p = body["sources"][0]
            return json.dumps({"findings": [{"category": "main", "title": "Fixture finding", "content": p["text"],
                "details": {}, "evidence": [{"source_id": p["id"], "quote": p["text"]}]}]})
        source = body["context"].get("sources", [])[0]
        return json.dumps({"parts": [{"text": source["text"], "kind": "source", "source_ids": [source["id"]]}], "action": None})


@pytest.fixture
def app(tmp_path):
    with App(tmp_path / "data", provider_factory=FixtureProvider) as app:
        app.config.save("ollama", "fixture")
        yield app


@pytest.fixture
def book(app, pdf):
    b, _ = app.library.import_pdf(pdf)
    app.jobs.create(b["id"], "prepare", background=False)
    return app.library.book(b["id"])

