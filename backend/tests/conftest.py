import pytest

import app.services.store as store_module
from app.services.store import Store


@pytest.fixture(autouse=True)
def isolated_call_log(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite call log, opened only if used,
    and every database a test opens is closed when the test ends."""
    opened: list[Store] = []
    original_init = Store.__init__

    def tracking_init(self, path):
        original_init(self, path)
        opened.append(self)

    monkeypatch.setattr(Store, "__init__", tracking_init)
    monkeypatch.setenv("DESPATCH_DB_PATH", str(tmp_path / "despatch.db"))
    monkeypatch.delenv("DESPATCH_STORE_LIVE_TRANSCRIPTS", raising=False)

    yield

    for store in opened:
        store.close()
    store_module._store = None
