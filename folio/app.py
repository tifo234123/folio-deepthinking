from pathlib import Path
import os
import sys
from filelock import FileLock, Timeout
from .config import Config
from .db import Database
from .library import Library
from .research import Research
from .providers import Provider
from .jobs import Jobs


def default_home():
    # Data lives beside the delivered application unless explicitly changed.
    if os.environ.get("FOLIO_HOME"): return Path(os.environ["FOLIO_HOME"])
    if getattr(sys, "frozen", False): return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent.parent / "data"


class App:
    def __init__(self, home=None, provider_factory=Provider):
        self.config = Config(home or default_home())
        self.lock = FileLock(str(self.config.home / "app.lock"))
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            raise RuntimeError("Folio is already using this data folder. Close it before opening the CLI or another window.") from None
        try:
            self.db = Database(self.config.home / "folio.sqlite3")
            self.library = Library(self.db, self.config)
            self.research = Research(self.db, self.config, self.library, provider_factory)
            self.jobs = Jobs(self.db, self.library, self.research)
            from .assistant import Assistant
            self.assistant = Assistant(self, provider_factory)
        except BaseException:
            self.lock.release()
            raise

    def close(self):
        self.jobs.close()
        self.lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

