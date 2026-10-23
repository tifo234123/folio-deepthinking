from contextlib import contextmanager
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime, timezone


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS books(
 id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, title TEXT NOT NULL, author TEXT,
 filename TEXT, path TEXT NOT NULL, status TEXT NOT NULL, page_count INTEGER DEFAULT 0,
 warnings TEXT DEFAULT '[]', error TEXT, created TEXT NOT NULL, active_structure TEXT);
CREATE TABLE IF NOT EXISTS pages(
 book_id TEXT REFERENCES books(id) ON DELETE CASCADE, page INTEGER, label TEXT, text TEXT,
 warnings TEXT, PRIMARY KEY(book_id,page));
CREATE TABLE IF NOT EXISTS passages(
 id TEXT PRIMARY KEY, book_id TEXT REFERENCES books(id) ON DELETE CASCADE,
 page INTEGER, label TEXT, position INTEGER, text TEXT NOT NULL, bbox TEXT);
CREATE INDEX IF NOT EXISTS passages_book ON passages(book_id,page,position);
CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(id UNINDEXED, book_id UNINDEXED, text, tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS passages_delete AFTER DELETE ON passages BEGIN
 DELETE FROM passage_search WHERE id=old.id;
END;
CREATE TABLE IF NOT EXISTS structures(
 id TEXT PRIMARY KEY, book_id TEXT REFERENCES books(id) ON DELETE CASCADE,
 name TEXT, original INTEGER DEFAULT 0, applied INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS sections(
 id TEXT PRIMARY KEY, structure_id TEXT REFERENCES structures(id) ON DELETE CASCADE,
 title TEXT, parent_id TEXT, position INTEGER, origin TEXT);
CREATE TABLE IF NOT EXISTS section_passages(
 section_id TEXT REFERENCES sections(id) ON DELETE CASCADE,
 passage_id TEXT REFERENCES passages(id) ON DELETE CASCADE, PRIMARY KEY(section_id,passage_id));
CREATE TABLE IF NOT EXISTS structure_history(
 id INTEGER PRIMARY KEY, book_id TEXT REFERENCES books(id) ON DELETE CASCADE,
 from_id TEXT, to_id TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS subjects(id TEXT PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS book_subjects(
 book_id TEXT REFERENCES books(id) ON DELETE CASCADE, subject_id TEXT REFERENCES subjects(id),
 PRIMARY KEY(book_id,subject_id));
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, book_id TEXT REFERENCES books(id) ON DELETE CASCADE,
 kind TEXT, status TEXT, payload TEXT, completed INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
 error TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS job_units(
 job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE, passage_id TEXT REFERENCES passages(id) ON DELETE CASCADE,
 status TEXT, error TEXT, PRIMARY KEY(job_id,passage_id));
CREATE TABLE IF NOT EXISTS findings(
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
 book_id TEXT REFERENCES books(id) ON DELETE CASCADE, category TEXT, title TEXT, content TEXT,
 details TEXT, sources TEXT, provider TEXT, model TEXT, prompt_version TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS notes(
 id TEXT PRIMARY KEY, book_id TEXT REFERENCES books(id) ON DELETE CASCADE,
 text TEXT, source_ids TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS messages(
 id INTEGER PRIMARY KEY, scope TEXT, role TEXT, content TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS ui_state(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS deep_reviews(
 job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
 passage_id TEXT REFERENCES passages(id) ON DELETE CASCADE,
 status TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL,
 PRIMARY KEY(job_id,passage_id));
DELETE FROM schema_version WHERE version=1;
INSERT OR IGNORE INTO schema_version VALUES(2);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

