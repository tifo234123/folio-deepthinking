"""Isolate MuPDF ingestion from the GUI's rendering process.

PyMuPDF does not support multithreaded use. A small JSON-line protocol keeps
preparation cancellable without sharing a document or native library state.
"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

from .documents import read_pdf

PREFIX = "FOLIO_EVENT\t"
WORKER_FLAG = "--pdf-worker"


def worker_command(path):
    # A packaged executable cannot run "-m"; it dispatches this flag in its launcher.
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG, path]
    return [sys.executable, "-m", "folio.pdf_worker", path]


def read_pdf_isolated(path, progress=lambda done, total: None, cancelled=lambda: False):
    process = subprocess.Popen(worker_command(str(Path(path).resolve())),
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                               text=True, encoding="utf-8", errors="replace", bufsize=1,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    events = queue.Queue()
    def collect():
        try:
            for line in process.stdout:
                if line.startswith(PREFIX):
                    try: events.put(json.loads(line[len(PREFIX):]))
                    except ValueError: events.put({"error": "PDF worker returned malformed data"})
        finally: events.put({"eof": True})
    reader = threading.Thread(target=collect, daemon=True, name="folio-pdf-events")
    reader.start()
    try:
        while True:
            if cancelled():
                raise InterruptedError("Preparation cancelled")
            try: event = events.get(timeout=.2)
            except queue.Empty: continue
            if "progress" in event: progress(*event["progress"])
            elif "result" in event: return event["result"]
            elif "error" in event: raise ValueError(event["error"])
            elif event.get("eof"): raise ValueError("PDF worker stopped before completing the document")
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        reader.join(timeout=3)
        process.stdout.close()


def emit(value):
    print(PREFIX + json.dumps(value, ensure_ascii=False), flush=True)


def main(path=None):
    # The parent decodes UTF-8; Windows pipes otherwise default to the ANSI code page.
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = read_pdf(path or sys.argv[1], progress=lambda done, total: emit({"progress": [done, total]}))
        emit({"result": result})
    except Exception as exc:
        emit({"error": str(exc)})


if __name__ == "__main__": main()
