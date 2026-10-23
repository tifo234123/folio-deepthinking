from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import json
from .db import uid, now


class Jobs:
    def __init__(self, db, library, research):
        self.db, self.library, self.research = db, library, research
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="folio-job")
        self.lock = Lock()
        self.futures = {}
        # The application takes a process lock before this recovery runs.
        db.execute("UPDATE jobs SET status='interrupted',error='Application stopped; resume this job',updated=? WHERE status IN ('running','queued','cancelling')", (now(),))
        db.execute("UPDATE books SET status='imported',error='Preparation interrupted; resume the job' WHERE status IN ('processing','queued')")

    def get(self, job_id):
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job:
            raise ValueError("Job not found")
        return job

    def create(self, book_id, kind, payload=None, background=True):
        self.library.book(book_id)
        with self.lock:
            if self.db.one("SELECT id FROM jobs WHERE book_id=? AND status IN ('queued','running','cancelling')", (book_id,)):
                raise ValueError("This book already has an active job")
            job_id = uid()
            payload = payload or {}
            ids = payload.get("source_ids", [])
            with self.db.connect() as db:
                db.execute("INSERT INTO jobs(id,book_id,kind,status,payload,total,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                           (job_id, book_id, kind, "queued", json.dumps(payload), len(ids), now(), now()))
                db.executemany("INSERT INTO job_units VALUES(?,?,?,NULL)", [(job_id, p, "pending") for p in ids])
                if kind == "prepare":
                    db.execute("UPDATE books SET status='queued' WHERE id=?", (book_id,))
        if background:
            self.futures[job_id] = self.pool.submit(self.run, job_id)
        else:
            self.run(job_id)
        return self.get(job_id)

    def run(self, job_id):
        job = self.get(job_id)
        with self.db.connect() as db:
            claimed = db.execute("UPDATE jobs SET status='running',error=NULL,updated=? WHERE id=? AND status='queued'", (now(), job_id)).rowcount
        if not claimed: return
        cancelled = lambda: self.get(job_id)["status"] in ("cancelled", "cancelling")
        try:
            if job["kind"] == "prepare":
                def progress(done, total):
                    self.db.execute("UPDATE jobs SET completed=?,total=?,updated=? WHERE id=?", (done, total, now(), job_id))
                self.library.prepare(job["book_id"], progress, cancelled)
            elif job["kind"] == "extract":
                self.research.run_extraction(job, cancelled)
            else:
                raise ValueError("Unknown job type")
            self.db.execute("UPDATE jobs SET status=?,updated=? WHERE id=?", ("cancelled" if cancelled() else "done", now(), job_id))
        except Exception as exc:
            state = "cancelled" if isinstance(exc, InterruptedError) or cancelled() else "failed"
            self.db.execute("UPDATE jobs SET status=?,error=?,updated=? WHERE id=?", (state, str(exc), now(), job_id))

    def cancel(self, job_id):
        with self.db.connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job: raise ValueError("Job not found")
            if job["status"] == "running":
                db.execute("UPDATE jobs SET status='cancelling',updated=? WHERE id=?", (now(), job_id))
            elif job["status"] == "queued":
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?", (now(), job_id))
                if job["kind"] == "prepare":
                    db.execute("UPDATE books SET status='imported' WHERE id=?", (job["book_id"],))

    def resume(self, job_id, background=True):
        with self.lock:
            job = self.get(job_id)
            future = self.futures.get(job_id)
            if job["status"] in ("queued", "running", "cancelling", "done") or (future and not future.done()):
                raise ValueError("Job is already running or complete; wait for cancellation to finish")
            if self.db.one("SELECT id FROM jobs WHERE book_id=? AND status IN ('queued','running','cancelling')", (job["book_id"],)):
                raise ValueError("This book already has an active job")
            self.db.execute("UPDATE jobs SET status='queued',updated=? WHERE id=?", (now(), job_id))
        if background:
            self.futures[job_id] = self.pool.submit(self.run, job_id)
        else:
            self.run(job_id)
        return self.get(job_id)

    def close(self):
        for job in self.db.rows("SELECT id FROM jobs WHERE status IN ('queued','running')"):
            self.cancel(job["id"])
        self.pool.shutdown(wait=True, cancel_futures=True)
