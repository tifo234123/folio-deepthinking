import json
from .db import now
from .providers import parse_json, Provider
from .research import prompt
from .schemas import AssistantResponse
from .deep import initial_evidence


class Assistant:
    def __init__(self, app, provider_factory=Provider):
        self.app, self.provider_factory = app, provider_factory

    def history(self, book_id=None):
        return self.app.db.rows("SELECT * FROM messages WHERE scope=? ORDER BY id", (book_id or "library",))

    def _save(self, scope, role, content):
        self.app.db.execute("INSERT INTO messages(scope,role,content,created) VALUES(?,?,?,?)", (scope, role, content, now()))

    def ask(self, text, book_id=None, section_id=None, source_id=None, on_status=lambda s: None):
        if not text.strip():
            raise ValueError("Write a question first")
        app = self.app
        settings = app.config.get()
        provider = self.provider_factory(settings)
        system = prompt("chat")
        context = {"scope": "library", "retrieval": "Partial search; not an exhaustive book review"}
        seen = {}
        if book_id:
            book = app.library.book(book_id)
            context.update({"scope": "section" if section_id else "book", "book_id": book_id,
                            "title": book["title"], "section_id": section_id,
                            "pages_with_review_flags": len(json.loads(book["warnings"])),
                            "structure_id": book["active_structure"]})
            initial = initial_evidence(app.library, book_id, text, section_id, source_id,
                                       max(2500, settings.input_chars-len(system)-6000))
            if source_id: context["scope"] = "selected passage with same-page context"
            context["evidence_passages"] = len(initial)
            context["scope_passages"] = len(app.library.passages(book_id, section_id))
            for p in initial:
                seen[p["id"]] = p
            context["sources"] = initial
        history = []
        # Book-scoped history, bounded by configured context; never mix books.
        remaining = max(0, settings.input_chars - len(system) - len(json.dumps(context)) - len(text) - 4000)
        for item in reversed(self.history(book_id)[-12:]):
            content = item["content"]
            if len(content) > remaining:
                break
            history.insert(0, {"role": item["role"], "content": content})
            remaining -= len(content)
        messages = history + [{"role": "user", "content": json.dumps({"context": context, "request": text}, ensure_ascii=False)}]
        scope = book_id or "library"
        self._save(scope, "user", text)
        events = []
        for step in range(7):
            on_status("Reading evidence…" if step == 0 else "Using the research tools…")
            raw = provider.complete(system, messages)
            try:
                response = AssistantResponse.model_validate(parse_json(raw))
            except Exception:
                raise ValueError("The assistant returned an invalid structured response. No unvalidated action was applied.") from None
            if response.action is None:
                if not response.parts:
                    raise ValueError("The assistant returned an empty answer")
                for part in response.parts:
                    if part.kind == "source" and not part.source_ids:
                        raise ValueError("A book-grounded claim had no source; answer rejected")
                    if any(pid not in seen for pid in part.source_ids):
                        raise ValueError("The assistant cited an unseen passage; answer rejected")
                result = {"parts": [p.model_dump() for p in response.parts], "events": events,
                          "sources": list(seen.values()), "coverage": f"Read {len(seen)} retrieved passages for this answer. Partial coverage; use Deep read for a tracked review." if book_id else "Library inventory only."}
                self._save(scope, "assistant", json.dumps(result, ensure_ascii=False))
                return result
            if step == 6:
                raise ValueError("Assistant tool-step limit reached. Narrow your request; successful actions remain saved.")
            action = response.action
            on_status("Tool: " + action.tool.replace("_", " "))
            try:
                result = self._tool(action.tool, action.arguments, book_id, section_id)
                if action.tool == "search":
                    for p in result["sources"]:
                        seen[p["id"]] = p
                if action.tool == "read_source":
                    seen[result["source"]["id"]] = result["source"]
                if action.tool in ("navigate", "extract", "propose_structure", "save_note"):
                    events.append({"tool": action.tool, "result": result})
                tool_result = {"success": True, "tool": action.tool, "result": result}
            except Exception as exc:
                tool_result = {"success": False, "tool": action.tool, "error": str(exc)}
            messages.extend([{"role": "assistant", "content": raw}, {"role": "user", "content": json.dumps(tool_result, ensure_ascii=False)}])
            # No silent truncation: fail with preserved actions if the tool context is too large.
        raise ValueError("Assistant could not complete the request")

    def _tool(self, tool, args, book_id, section_id):
        app = self.app
        allowed = {"list_books": {"query"}, "sections": set(), "search": {"query", "scope"},
                   "read_source": {"source_id"}, "coverage": set(), "navigate": {"section_id", "source_id"},
                   "extract": {"scope", "focus"}, "propose_structure": {"request"}, "save_note": {"text", "source_ids"}}
        if set(args) - allowed[tool]:
            raise ValueError("Unexpected tool arguments")
        if tool == "list_books":
            books = app.library.books(args.get("query", ""))
            return {"books": [{k: b[k] for k in ("id", "title", "author", "status", "subjects")} for b in books[:50]], "total": len(books)}
        if not book_id:
            raise ValueError("Open a book first")
        if tool == "sections":
            return [{k: s[k] for k in ("id", "title", "parent_id", "pages")} for s in app.library.sections(book_id)]
        if tool == "search":
            if args.get("scope", "section") not in ("section", "book"):
                raise ValueError("Invalid search scope")
            return {"sources": app.library.search(book_id, str(args.get("query", "")), section_id if args.get("scope") != "book" else None, limit=6), "coverage": "Partial retrieval"}
        if tool == "read_source":
            return {"source": app.library.source(book_id, args["source_id"])}
        if tool == "coverage":
            return app.research.coverage(book_id)
        if tool == "navigate":
            if args.get("source_id"):
                p = app.library.source(book_id, args["source_id"])
                return {"source_id": p["id"], "page": p["page"]}
            app.library.passages(book_id, args["section_id"])
            return {"section_id": args["section_id"]}
        if tool == "extract":
            scope = args.get("scope", "section")
            if scope not in ("section", "book"):
                raise ValueError("Invalid extraction scope")
            # Paid work is never queued by the model: the professor confirms the estimate in the interface.
            sections = [section_id] if scope == "section" and section_id else None
            focus = str(args.get("focus", ""))
            payload = app.research.deep_payload(book_id, sections, focus)
            calls = sum(1 for _ in app.research.deep_batches(book_id, payload["source_ids"], focus, app.config.get(payload["provider"])))
            return {"status": "awaiting confirmation in the Deep read dialog; nothing has started", "section_id": sections[0] if sections else None,
                    "focus": focus, "total_passages": len(payload["source_ids"]), "model_calls": calls}
        if tool == "propose_structure":
            result = app.research.propose_structure(book_id, str(args["request"]))
            return {"structure_id": result["structure_id"], "name": result["name"], "status": "proposal awaiting acceptance"}
        if tool == "save_note":
            return {"note_id": app.library.save_note(book_id, str(args["text"]), args.get("source_ids", [])), "status": "saved"}

