# Deepthinking verification — 2026-10-01

- Original source hash manifest checked; no source changes made to the original project.
- Desktop Folio Saved and Folio Deepthinking have real, separate folders and Python environments. The Saved edition changes only packaging discovery and local storage/launcher paths, not application behavior.
- Databases copied with SQLite's online backup API; each edition's managed PDFs and configuration path are independent.
- 46 automated tests passed. All desktop scenarios use simulated providers; deep reading validates every passage review and exact quotations before atomic batch checkpointing.
- A live Gemini sample on the selected abstract completed one batch of seven passages, saving one detailed finding with four detail fields and one valid quoted source. Six passages were classified as headings/reference material. The whole book was not analyzed.
- Reading overview, section reader, and detailed findings were visually checked using the copied book.
- Desktop launchers validated, marked executable/trusted, and point to their corresponding folders.

The inherited ARCHITECTURE and VERIFICATION documents describe the original baseline. New modules are deep.py (batched reading and coverage), reading_ui.py (scope preview and job setup), section_reader.py (page-by-page section text), and group_structure.py (bounded large-book preview). Current edition differences and limits are documented in README.md.
