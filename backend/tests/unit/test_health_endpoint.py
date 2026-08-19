"""Phase M7 — /api/v1/health enrichment: DB, storage, last ingest, version."""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint_structure():
    """M7: health returns status, database, storage, last_ingest, version."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"healthy", "degraded"}
    assert body["database"] in {"connected", "disconnected"}
    assert "storage" in body and "pending" in body["storage"] and "processed" in body["storage"]
    assert "last_ingest" in body
    assert "version" in body and isinstance(body["version"], str) and body["version"]
    assert "timestamp" in body


def test_health_storage_writable_flag_shape():
    """M7: storage entries carry a writable boolean (and optional error)."""
    res = client.get("/api/v1/health")
    body = res.json()
    for key in ("pending", "processed"):
        entry = body["storage"][key]
        assert isinstance(entry["writable"], bool)
        if "error" in entry:
            assert isinstance(entry["error"], str)


def test_health_last_ingest_null_when_no_documents(monkeypatch):
    """M7: last_ingest is null when no documents exist (never ingested)."""
    from app.db.postgres import session as session_mod

    def fake_ping() -> bool:
        return True

    class FakeAcquire:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            class FakeCur:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def execute(self, sql):
                    assert "MAX(created_at)" in sql

                def fetchone(self):
                    return {"t": None}

            return FakeCur()

    monkeypatch.setattr(session_mod, "ping", fake_ping)
    monkeypatch.setattr(session_mod, "acquire", lambda: FakeAcquire())

    res = client.get("/api/v1/health")
    body = res.json()
    assert body["status"] == "healthy"
    assert body["last_ingest"] is None


def test_health_last_ingest_reports_max_timestamp(monkeypatch):
    """M7: last_ingest echoes the MAX(documents.created_at)."""
    from app.db.postgres import session as session_mod

    def fake_ping() -> bool:
        return True

    class FakeAcquire:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            class FakeCur:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def execute(self, sql):
                    assert "MAX(created_at)" in sql

                def fetchone(self):
                    return {"t": "2026-08-18T06:30:00"}

            return FakeCur()

    monkeypatch.setattr(session_mod, "ping", fake_ping)
    monkeypatch.setattr(session_mod, "acquire", lambda: FakeAcquire())

    res = client.get("/api/v1/health")
    body = res.json()
    assert body["last_ingest"] == "2026-08-18T06:30:00"


def test_health_degraded_when_db_down(monkeypatch):
    """M7: DB failure degrades status without raising (storage still reported)."""
    from app.db.postgres import session as session_mod

    def fake_ping() -> bool:
        return False

    monkeypatch.setattr(session_mod, "ping", fake_ping)

    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"
    assert body["database"] == "disconnected"
    assert body["last_ingest"] is None


def test_health_storage_error_captured(monkeypatch):
    """M7: unwritable storage reports error text instead of raising."""
    from app.db.postgres import session as session_mod

    def fake_ping() -> bool:
        return True

    class BoomPath:
        def __init__(self, *args, **kwargs):
            pass

        def mkdir(self, *args, **kwargs):
            raise OSError("disk full")

    monkeypatch.setattr(session_mod, "ping", fake_ping)
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "Path", BoomPath)

    res = client.get("/api/v1/health")
    body = res.json()
    assert body["status"] == "healthy"
    assert body["storage"]["pending"]["writable"] is False
    assert "disk full" in body["storage"]["pending"]["error"]


def test_health_json_serializable():
    """M7: full payload is plain JSON (used by the admin system-status card)."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    json.dumps(res.json())