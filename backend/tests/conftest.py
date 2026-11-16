import pytest


@pytest.fixture(autouse=True)
def isolated_call_log(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite call log, opened only if used."""
    monkeypatch.setenv("CIVOPS_DB_PATH", str(tmp_path / "civops.db"))
    monkeypatch.delenv("CIVOPS_STORE_LIVE_TRANSCRIPTS", raising=False)
