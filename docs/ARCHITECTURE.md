# Architecture and decisions

## Scope

This implementation follows the supplied research brief and functional diagram, with the later corrections: a **native local desktop**, NVIDIA API and OpenRouter as named providers, and the macOS-style visual references. The full source brief and images are retained in this directory. Lashy was inspected read-only for its provider interface and configuration patterns; its saved credentials were not accessed or copied.

## Module map

| Module | Responsibility |
|---|---|
| `config.py` | Provider selection, per-provider settings, atomic `.env` persistence, library path |
| `providers.py` | Explicit REST adapters, discovery, model inference tests, redacted errors |
| `db.py` | SQLite schema, connection/transaction boundaries, identifiers |
| `documents.py` | PDF reading, complete page text, blocks, warnings, outlines |
| `pdf_worker.py` | Isolated PDF preparation process with progress and cancellation |
| `library.py` | Managed imports, preparation storage, subjects, search, source access, notes |
| `schemas.py` | Strict extraction, evidence, outline, answer, and action models |
| `research.py` | Checkpointed extraction, evidence checks, coverage, proposals, apply/undo |
| `jobs.py` | Single-worker scheduling, cancellation, restart recovery, resume |
| `assistant.py` | Book-scoped history, context assembly, bounded validated tool loop |
| `app.py` | Shared service composition and single-process data-folder lock |
| `cli.py` | CLI workflows and credential-free research export |
| `desktop.py`, `theme.py` | Native Qt interface and visual design system |
| `settings_ui.py` | Provider presets, searchable catalogue, price display, test-before-activation setup |
| `prompts/` | Core role plus extraction, chat/tool, and restructuring instructions |

## Why this stack

Python keeps PDF processing, validation, and the application services together. SQLite provides durable local research state and text search without a server. Qt renders a native desktop application with the rounded light workspace and dark settings treatment requested in the references. Neither the CLI nor the interface owns business logic or a separate data store.

SQLite FTS5 starts with exact technical-term retrieval and model-directed query reformulation. This is transparent and locally available; it avoids coupling saved documents to a particular embedding model. Embeddings can be added behind the library search service later. The interface labels retrieval as partial, rather than equating the top search results with an exhaustive review.

PDF ingestion runs in a separate process from desktop rendering, following [PyMuPDF's multiprocessing guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html). The parent receives JSON progress events and the complete extraction result; cancellation terminates the isolated worker. AI networking and database work use threads without sharing MuPDF document state.

## Data invariants

1. Imported originals are never changed. Managed copies use content hashes; exact duplicates share one record.
2. Original page text and source IDs remain independent of section organization.
3. A book can have multiple subjects and multiple named structures without duplicating its file.
4. Source IDs in notes, findings, navigation, and proposals must belong to the current book.
5. Model findings require actual quoted evidence. Valid citations do not automatically certify interpretation.
6. An extraction run is immutable output history; regenerating creates a new job. Professor-authored notes remain separate.
7. Each passage completes transactionally with its findings and checkpoint. Retry skips completed passages.
8. A structure proposal does not affect the active view until accepted. Applying a structure records a reversible previous state. Unmapped source passages remain available.
9. Provider/model selection is explicit. No fallback sends a local request to a cloud provider.
10. Model tools cannot execute shell commands, arbitrary SQL, credential operations, book removal, or proposal acceptance.

## Provider references checked

The adapters use the official request formats below. Model IDs are selected by the user or discovered from the provider; no 'latest model' is hardcoded.

- [OpenAI text generation and Responses](https://developers.openai.com/api/docs/guides/text)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [Anthropic API authentication](https://platform.claude.com/docs/en/manage-claude/authentication) and [versioning](https://platform.claude.com/docs/en/api/versioning)
- [Gemini generateContent](https://ai.google.dev/api/generate-content)
- [NVIDIA chat-completions request reference](https://docs.api.nvidia.com/nim/reference/meta-llama-3_1-70b-infer)
- [OpenRouter quickstart](https://openrouter.ai/docs/quickstart), [model catalogue](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties), and [current-key status](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key)
- [LM Studio OpenAI-compatible endpoints](https://lmstudio.ai/docs/developer/openai-compat)

Model-specific capabilities vary. All structured model output is validated in application code. A successful model catalogue request does not establish that a selected model is available to the account or suitable for research extraction.

Desktop provider setup validates an in-memory draft and tests its exact model before atomically saving settings. Discovery caches only model metadata, endpoint, and refresh time; it does not save keys or change the active configuration. OpenRouter pricing is converted from USD per token to USD per million tokens using decimal arithmetic. Free labels require explicitly zero input, output, and request prices. Key-status responses are restricted to spending-limit/usage fields and are not persisted. Dismissing setup invalidates outstanding results.
