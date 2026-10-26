"""Every test gets its own throw-away shared database path: no test may ever touch the owner's real
KunalQuant database (market_data/kq_store.py reads the KQ_DATABASE environment variable)."""

import pytest


@pytest.fixture(autouse=True)
def _private_shared_database(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_DATABASE", str(tmp_path / "shared_kunal_quant.db"))
