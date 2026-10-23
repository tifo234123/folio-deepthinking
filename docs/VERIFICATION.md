# Verification record

Date: 2026-10-01. Environment: local Linux desktop, Python 3.12, Qt/PySide6 6.11.2.

## Automated checks

The test suite includes:

- Managed imports, exact duplicate identity, original-file preservation, and multiple subject assignments.
- Real synthetic PDF parsing, hierarchical bookmarks, page labels versus PDF indices, and section-scoped versus whole-book retrieval.
- A 101-page fixture with more than 60,000 characters, confirming no global text truncation and identifying its unreadable final page.
- Corrupt and encrypted PDFs failing with visible errors rather than false ready states.
- Atomic configuration writes, preservation of unrelated settings, difficult key quoting, masked public settings, and write-failure recovery.
- Request/response contracts for Ollama, OpenAI, Anthropic, Gemini, NVIDIA, OpenRouter, LM Studio, and a custom compatible endpoint using an HTTP mock transport.
- Successful model discovery followed by failed model inference; truncated provider answers rejected; provider response bodies and keys excluded from errors.
- Validated findings, rejected invented quotes/source IDs, checkpointed retry, cancellation, and preserved completed findings.
- Notes and source IDs surviving regeneration and application restart.
- Process locking, recovery from interrupted jobs, and refusal to resume a job with changed model/endpoint selection.
- Noncontiguous custom sections, retained unmapped passages, hierarchy validation, proposal acceptance, and undo.
- Scoped assistant history, application-tool execution, and rejection of unexpected arguments or invalid navigation/source targets.
- A simulated assistant request producing a structure proposal that remains unapplied until explicitly accepted.
- Refusal to remove a book while a cancelled model request is still finishing.
- OpenRouter model metadata, non-text model exclusion, decimal price formatting, free-label detection, and restricted key-status fields.
- Provider presets, model search/free filtering, offline catalogue preservation, failed activation rollback (including the already-active provider), and dismissal during a pending model test.
- Native Qt workflow: book/section selection, findings, notes, original PDF rendering, provider settings, and restored last-book/section state.

The final command and count are recorded in `test-results.txt` in this directory.

## Visual checks

The actual Qt application was rendered and inspected, including the light workspace, source viewer, and dark settings dialog. Layout issues found during inspection were corrected. Screenshots in this directory use explicitly synthetic test documents and simulated model results; they are design/interaction evidence, not evidence of a live AI response.

The native launch script, CLI help, Python compilation, shell syntax, and desktop-entry format were checked. The delivered application starts with an empty library and asks for the user's own AI configuration.

## Not verified live

No online API credentials were read from Lashy or reused. No local Ollama service was available. Authenticated inference, model discovery against a real account, real-world academic books, and research-quality evaluation are therefore not claimed as verified.

The next practical validation is to configure one provider in the application and run the workflow on representative user PDFs, especially those with equations, tables, and multiple columns. OCR and cross-book research remain outside this initial version.

Follow-up UI validation: all six desktop tests passed, including manual subject assignment/filtering and generating, accepting, and switching a saved outline back to the original. Subject and structure dropdowns were rendered and visually checked with white backgrounds and readable text.
