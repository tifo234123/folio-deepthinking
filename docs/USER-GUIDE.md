# Folio Deepthinking — user guide

A separate edition of the native Folio desktop app for detailed, source-backed doctoral reading. The original project and the Desktop **Folio Saved** snapshot remain separate. This folder contains its own source code, Python environment, configuration, copied PDFs, and database.

## Open

Double-click **Folio Deepthinking** on your Desktop, or run `./launch.sh` here. Your copied library and provider configuration are ready. New findings, notes, and outlines in this edition do not change the original library.

## Read a book by sections

1. Open a book and select a chapter or subsection in the left-hand outline.
2. **Reading overview** shows the scope's page/passages count, previously reviewed passages, saved findings, and actual source excerpts immediately. These excerpts are not an AI summary.
3. **Section reader** contains all extracted text in the selected scope, page by page. Use Previous/Next or the page dropdown. Open the original PDF to verify columns, tables, notation, or extraction errors.
4. **Explain this page in depth** fills the assistant with a doctoral-reading request and gives it the selected page's source context. Press Send when ready. Questions remain scoped to the selected section unless whole-book scope is enabled.
5. **Deep read** reviews every passage in the selected scope in bounded neighboring batches. Before starting, the dialog shows the passage count, approximate model-call count, and provider. Enter an optional research focus. This uses your API account; a whole-book job may involve hundreds of requests.
6. **Findings** contains detailed ideas, definitions, methods, equations, and data, with visible supporting quotations, PDF links, and model provenance. Filter by finding type or reading run. Completed batches appear as work progresses.
7. Use **Background work** to cancel, inspect an error, or resume. Completed batches survive interruption; failed batches do not receive a successful checkpoint.

## What makes this edition different

- Detailed prompts preserve arguments, theoretical framing, mechanisms, evidence, conditions, examples, assumptions, trade-offs, and stated research gaps when supported by the book. Extra length is not forced when the source contains little information.
- Each deep-reading response must account for every passage. Substantive passages require a cited finding; reference/navigation/unclear/out-of-focus passages receive explicit reasons. Unsupported or missing quotations are rejected.
- Assistant context includes more bounded evidence, same-page context for selected passages, and representative excerpts across the selected scope. Retrieval prefers explanatory prose over short headings and bibliography-like text, without removing anything from deep reading.
- Source search respects the selected section. The original source text and chapters remain available.
- Large-book reorganizations can use bounded source groups instead of exceeding the model's input limit. These are broad previews based on sampled excerpts, with explicit caveats; all original passages are retained and acceptance remains manual.
- Provider errors distinguish temporary unavailability from rate limits. Folio never silently switches provider or model.

## Evidence and limits

Deepthinking names the reading workflow; it does not unlock a stronger model or guarantee doctoral-quality interpretation. Depth and accuracy depend on the source and selected model. Quotation validation verifies provenance, not every semantic claim. A completed run covers its chosen focus and readable passages, not unreadable pages or all possible questions. There is no OCR in this edition.

The copied book has layout flags on many pages. A layout flag is not proof that the page is unreadable. Inspect the original PDF, especially for formulas and tables. Original section mappings use page boundaries, so adjacent sections on the same page can overlap.

The new Reading overview is immediately usable offline. AI analysis starts only when requested. Existing findings from the original copy retain their original provenance and are not relabeled as deep reading.

## Validation

The automated suite passed **46 tests**, covering the inherited workflows plus deep-reading batch resume, invalid/missing evidence, complete passage accounting, explicit empty reviews, scoped context, large-book source retention, and the section reader.

One authenticated live sample used the copied Gemini configuration on the selected abstract: **7 passages reviewed, 1 detailed finding, 4 detail fields, and 1 verified quotation**. This validates that small workflow, not the full book or all providers. See `docs/live-sample.json` and `docs/test-results.txt`.

## Storage and installation

Runtime data is in `data/`, including the private `.env`, SQLite database, and managed PDF copies. Back up this folder and keep credentials private. The SQLite database was copied with the SQLite backup API and PDF paths were rebased into this edition's own library. No PDF path points to the original library.

For a fresh environment, run `./install.sh`. Development tests: `uv pip install --python .venv/bin/python pytest reportlab`, then `.venv/bin/python -m pytest tests -q`. Schema version 2 adds per-passage deep-review records while retaining old findings and jobs.

## Windows build

The Windows app is a single file, `FolioDeepthinking.exe`. Its `data` folder (database, PDFs, API keys) is created next to the `.exe` on first run and is never part of the build.

- **GitHub:** pushing a tag such as `v0.1.0` (or running the *Build Windows app* workflow manually) builds and tests on Windows and attaches `FolioDeepthinking.exe` to the release.
- **Locally on Windows:** `pip install -r packaging/requirements-windows.txt`, `pip install --no-deps .`, then `pyinstaller packaging/folio.spec --noconfirm`. The app is written to `dist/FolioDeepthinking.exe`.

Windows builds pin Qt 6.8 (LTS). Qt 6.9+ links the Windows ICU library, which Wine lacks, and 6.8 lets the same build be tested under Wine.
