# Folio Deepthinking 📚

> **An AI research assistant for a personal library of PDF books.**
> Ask questions across your books, get answers grounded in verbatim quotes, and keep a traceable research trail — never a confident guess with no source behind it.

Built by **Abderrahman Ezzin** with **Python** and **PySide6** (Qt for Python), running as a native Windows desktop app.

---

## 🖼️ Screenshots

*(coming soon)*

---

## What it does

Folio helps a researcher — the project was designed around a professor's personal PDF library — locate, extract, understand and organize evidence across many books, without losing track of where every claim actually came from.

- **Evidence-first answers.** Every finding is tied to a verbatim quote from the source PDF. The assistant is instructed to never invent a quote, a page number, or an author, and to say plainly when the available evidence can't settle a question.
- **Structured extraction.** Findings are returned as structured JSON (`category`, `title`, `content`, `evidence`) with categories for claims, definitions, formulas, methods and data — each preserving units, conditions and uncertainty instead of flattening them into a soundbite.
- **Scoped search.** Questions can be scoped to the whole library, a single book, a section or a selected passage, and the assistant respects that scope instead of silently mixing books together.
- **Coverage tracking.** A "quick retrieval" is explicitly partial; an "exhaustive" request requires a tracked extraction job and reports exactly how many passages were actually covered (e.g. "12 of 90 passages processed") rather than implying the whole book was read.
- **Notes & reorganization.** The professor's own notes are kept separate from AI-generated findings and from the original source text. Large reorganizations of the library's structure go through a proposal the user has to explicitly accept — nothing restructures silently.
- **Prompt-injection resistant.** PDF content, including anything that reads like an instruction to the AI ("ignore your previous instructions...") is treated strictly as untrusted research material to analyze, never as a command.

## 🧠 Why it's interesting from an engineering standpoint

The core of this project isn't the UI — it's the **prompt architecture** behind it. Each task (chat, quick extraction, deep/exhaustive extraction, structure proposals) has its own dedicated system prompt, each one specifying:
- what evidence is and isn't allowed to be asserted,
- how to handle incomplete/unreadable (scanned, image-only) pages,
- how to keep quantitative claims (numbers, units, conditions) intact instead of stripping context away,
- explicit example behaviors (few-shot) for edge cases like conflicting sources or failed tool calls.

That structure is what keeps the assistant useful for real research instead of producing fluent-sounding but unverifiable summaries.

## ▶️ Run it

This is currently distributed as a **packaged Windows build** (PyInstaller) rather than the raw `.py` source — see note below.

```bash
# Unzip, then run:
FolioDeepthinking.exe
```

No installation required; it's a self-contained desktop app for Windows.

> **Note on source:** this repository ships the compiled application, not the raw Python source tree. The project's prompt files (the actual "brain" of the assistant — see [`prompts/`](_internal/folio/prompts)) are included in full and are readable as plain Markdown, since that's where most of the engineering effort went.

## 🛠️ Stack

- **Python 3.12**
- **PySide6** (Qt) for the desktop UI
- **PyMuPDF** for PDF parsing/extraction
- **Pydantic** for structured LLM output validation
- Packaged with **PyInstaller**

## 📂 What's in this repo

```
FolioDeepthinking.exe       — the app
_internal/folio/prompts/    — the system prompts that drive the assistant
  core.md                   — core research-assistant instructions
  chat.md                   — conversational mode
  extract.md / deep_extract.md — structured evidence extraction
  structure.md / group_structure.md — library reorganization proposals
_internal/folio/static/     — UI icons
```

---

*Built by [Abderrahman Ezzin](https://github.com/tifo234123) — Computer Engineering student, Università degli Studi di Cassino e del Lazio Meridionale.*
