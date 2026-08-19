"""Phase M4 — structured request logging + x-request-id tracing."""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.jwt_handler import create_token
from app.logging.middleware import RequestLoggingMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/echo")
    def echo():
        return {"ok": True}

    return app


def _log_lines(caplog) -> list[dict]:
    return [
        json.loads(rec.message)
        for rec in caplog.records
        if rec.name == "app.request" and rec.levelno == logging.INFO
    ]


class TestRequestId:
    def test_echoes_x_request_id_header(self):
        client = TestClient(_make_app())
        res = client.get("/ping")
        assert res.status_code == 200
        assert res.headers.get("x-request-id")
        assert len(res.headers["x-request-id"]) == 16

    def test_distinct_ids_across_requests(self):
        client = TestClient(_make_app())
        first = client.get("/ping").headers["x-request-id"]
        second = client.get("/ping").headers["x-request-id"]
        assert first != second


class TestStructuredLog:
    def test_logs_one_json_line_per_request(self, caplog):
        client = TestClient(_make_app())
        with caplog.at_level(logging.INFO, logger="app.request"):
            client.get("/ping")
            client.post("/echo")

        lines = _log_lines(caplog)
        assert len(lines) == 2

    def test_line_has_request_metadata(self, caplog):
        client = TestClient(_make_app())
        with caplog.at_level(logging.INFO, logger="app.request"):
            res = client.get("/ping")

        line = _log_lines(caplog)[0]
        assert line["request_id"] == res.headers["x-request-id"]
        assert line["method"] == "GET"
        assert line["path"] == "/ping"
        assert line["status"] == 200
        assert line["latency_ms"] >= 0

    def test_logs_user_scope_for_valid_token(self, caplog):
        client = TestClient(_make_app())
        token = create_token(subject="42", audience="staff", role="admin")
        with caplog.at_level(logging.INFO, logger="app.request"):
            client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        line = _log_lines(caplog)[0]
        assert line["user_id"] == "42"
        assert line["audience"] == "staff"

    def test_no_user_scope_without_token(self, caplog):
        client = TestClient(_make_app())
        with caplog.at_level(logging.INFO, logger="app.request"):
            client.get("/ping")

        line = _log_lines(caplog)[0]
        assert line["user_id"] is None
        assert line["audience"] is None

    def test_invalid_token_yields_null_user(self, caplog):
        client = TestClient(_make_app())
        with caplog.at_level(logging.INFO, logger="app.request"):
            client.get("/ping", headers={"Authorization": "Bearer not.a.real.token"})

        line = _log_lines(caplog)[0]
        assert line["user_id"] is None
