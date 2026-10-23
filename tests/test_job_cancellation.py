from threading import Event
import pytest
from conftest import FixtureProvider


def test_cancelling_blocks_book_removal_until_worker_stops(app, book):
    entered, release = Event(), Event()
    class WaitingProvider(FixtureProvider):
        def complete(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().complete(*args, **kwargs)
    app.research.provider_factory = WaitingProvider
    job = app.jobs.create(book["id"], "extract", app.research.extraction_payload(book["id"]))
    try:
        assert entered.wait(5)
        app.jobs.cancel(job["id"])
        assert app.jobs.get(job["id"])["status"] == "cancelling"
        with pytest.raises(ValueError, match="Cancel active"):
            app.library.remove(book["id"], delete_managed=True)
    finally:
        release.set()
        app.jobs.futures[job["id"]].result(timeout=5)
    assert app.jobs.get(job["id"])["status"] == "cancelled"
    assert not app.research.findings(book["id"])

