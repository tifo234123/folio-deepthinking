import argparse
import getpass
import json
from pathlib import Path
from .app import App
from .config import PROVIDERS
from .providers import Provider


def output(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def main():
    parser = argparse.ArgumentParser(description="Folio local PDF research")
    parser.add_argument("--home", type=Path, help="Data/configuration folder")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("desktop")
    sub.add_parser("settings")
    setup = sub.add_parser("configure")
    setup.add_argument("provider", choices=PROVIDERS)
    setup.add_argument("model")
    setup.add_argument("--endpoint")
    setup.add_argument("--set-key", action="store_true", help="Securely prompt for API key")
    setup.add_argument("--input-chars", type=int, default=24000)
    setup.add_argument("--output-tokens", type=int, default=4096)
    sub.add_parser("models")
    sub.add_parser("test-provider")
    lib = sub.add_parser("library-folder")
    lib.add_argument("path", type=Path)
    imp = sub.add_parser("import")
    imp.add_argument("paths", nargs="+", type=Path)
    scan = sub.add_parser("scan")
    scan.add_argument("folder", type=Path)
    books = sub.add_parser("books")
    books.add_argument("--query", default="")
    for name in ("prepare", "sections", "coverage", "structures", "undo", "notes", "export"):
        p = sub.add_parser(name)
        p.add_argument("book")
        if name == "export":
            p.add_argument("output", type=Path)
    for name in ("search", "chat"):
        p = sub.add_parser(name)
        p.add_argument("book")
        p.add_argument("query")
        p.add_argument("--section")
    extract = sub.add_parser("extract")
    extract.add_argument("book")
    extract.add_argument("--section", action="append")
    extract.add_argument("--focus", default="")
    findings = sub.add_parser("findings")
    findings.add_argument("book")
    findings.add_argument("--section")
    findings.add_argument("--job")
    prop = sub.add_parser("propose")
    prop.add_argument("book")
    prop.add_argument("request")
    manual = sub.add_parser("structure-json")
    manual.add_argument("book")
    manual.add_argument("file", type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("book")
    apply.add_argument("structure")
    note = sub.add_parser("note")
    note.add_argument("book")
    note.add_argument("text")
    note.add_argument("--source", action="append", default=[])
    note.add_argument("--id")
    subjects = sub.add_parser("subjects")
    subjects.add_argument("book")
    subjects.add_argument("names", nargs="*")
    sub.add_parser("jobs")
    resume = sub.add_parser("resume")
    resume.add_argument("job")
    remove = sub.add_parser("remove")
    remove.add_argument("book")
    remove.add_argument("--delete-managed-pdf", action="store_true")
    args = parser.parse_args()
    if args.command == "desktop":
        from .desktop import main as desktop
        return desktop(args.home)
    try:
        with App(args.home) as app:
            c, lib, r, jobs = app.config, app.library, app.research, app.jobs
            cmd = args.command
            if cmd == "settings": output(c.get().public())
            elif cmd == "configure":
                output(c.save(args.provider, args.model, args.endpoint,
                              getpass.getpass("API key (input hidden): ") if args.set_key else None,
                              input_chars=args.input_chars, output_tokens=args.output_tokens).public())
            elif cmd == "models": output(Provider(c.get()).models())
            elif cmd == "test-provider": output({"response": Provider(c.get()).test(), "tested": c.get().public()})
            elif cmd == "library-folder": c.set_library(args.path); output({"folder": c.library})
            elif cmd == "import":
                for path in args.paths:
                    b, created = lib.import_pdf(path)
                    job = jobs.create(b["id"], "prepare", background=False) if created else None
                    output({"book": lib.book(b["id"]), "created": created, "job": job})
            elif cmd == "scan":
                result = lib.scan(args.folder)
                for item in result:
                    if item.get("created"):
                        item["job"] = jobs.create(item["book_id"], "prepare", background=False)
                output(result)
            elif cmd == "books": output(lib.books(args.query))
            elif cmd == "prepare": output(jobs.create(args.book, "prepare", background=False))
            elif cmd == "sections": output(lib.sections(args.book))
            elif cmd == "coverage": output(r.coverage(args.book))
            elif cmd == "search": output(lib.search(args.book, args.query, args.section))
            elif cmd == "extract": output(jobs.create(args.book, "extract", r.extraction_payload(args.book, args.section, args.focus), background=False))
            elif cmd == "findings": output(r.findings(args.book, args.section, args.job))
            elif cmd == "chat": output(app.assistant.ask(args.query, args.book, args.section))
            elif cmd == "structures": output(app.db.rows("SELECT * FROM structures WHERE book_id=? ORDER BY created", (args.book,)))
            elif cmd == "propose": output(r.propose_structure(args.book, args.request))
            elif cmd == "structure-json": output(r.save_structure(args.book, json.loads(args.file.read_text()), origin="Manual structure"))
            elif cmd == "apply": r.apply_structure(args.book, args.structure); output({"applied": args.structure})
            elif cmd == "undo": output({"restored": r.undo_structure(args.book)})
            elif cmd == "note": output({"note_id": lib.save_note(args.book, args.text, args.source, args.id)})
            elif cmd == "notes": output(app.db.rows("SELECT * FROM notes WHERE book_id=?", (args.book,)))
            elif cmd == "subjects": lib.set_subjects(args.book, args.names); output({"subjects": args.names})
            elif cmd == "jobs": output(app.db.rows("SELECT * FROM jobs ORDER BY created DESC"))
            elif cmd == "resume": output(jobs.resume(args.job, background=False))
            elif cmd == "remove": lib.remove(args.book, args.delete_managed_pdf); output({"removed": args.book})
            elif cmd == "export":
                data = export_book(app, args.book)
                args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                output({"exported": str(args.output)})
    except Exception as exc:
        parser.exit(1, f"Folio: {exc}\n")


def export_book(app, book_id):
    book = app.library.book(book_id)
    return {"book": {k: book[k] for k in ("id", "title", "author", "filename", "page_count", "warnings")},
            "findings": app.research.findings(book_id), "sources": app.library.passages(book_id),
            "notes": app.db.rows("SELECT * FROM notes WHERE book_id=?", (book_id,)),
            "structures": [{**s, "sections": app.library.sections(book_id, s["id"])} for s in app.db.rows("SELECT * FROM structures WHERE book_id=?", (book_id,))],
            "coverage": app.research.coverage(book_id)}


if __name__ == "__main__":
    main()

