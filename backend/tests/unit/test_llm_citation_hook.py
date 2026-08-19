"""Unit tests for the DEC-1 hosted-LLM cite-with-LLM seam.

The seam is OFF by default (``settings.llm_enabled`` false) and must be a
strict pass-through in that state — no LLM call, no behavior change. These
tests prove the off-state is inert and that the on-state (future DEC-1
flip) is fully wired: prompt building, provider request/response, and
citation parsing. No network is ever touched.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.llm.citations import (
    Citation,
    build_citation_prompt,
    maybe_apply_citation_mode,
    parse_citation_answer,
)
from app.llm.provider import LLMClient, LLMConfig, LLMError
from app.response.package_builder import Excerpt, ResponsePackage, Source


def _enter(patches) -> ExitStack:
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


def _package() -> ResponsePackage:
    def source(title: str) -> Source:
        return Source(
            chunk_id=1,
            document_id=1,
            title=title,
            section=None,
            chunk_type="paragraph",
            is_approved=True,
            document_version=1,
        )

    return ResponsePackage(
        response_id="abc123",
        title="Doc A",
        answer="original extractive answer",
        excerpts=[
            Excerpt(text="Alpha content.", source=source("Doc A"), confidence=0.9, bm25_score=1.0, vec_score=0.5),
            Excerpt(text="Beta content.", source=source("Doc B"), confidence=0.8, bm25_score=0.9, vec_score=0.4),
        ],
        confidence=0.9,
    )


def _enable_llm(url: str = "https://api.example.test/v1"):
    return _enter([
        patch.object(settings, "llm_enabled", True),
        patch.object(settings, "llm_provider_url", url),
        patch.object(settings, "llm_api_key", "k"),
        patch.object(settings, "llm_model", "m"),
    ])


def _disable_llm():
    return _enter([
        patch.object(settings, "llm_enabled", False),
        patch.object(settings, "llm_provider_url", ""),
    ])


class TestDefaultIsOff:
    def test_llm_enabled_defaults_to_false(self):
        assert settings.llm_enabled is False


class TestHookOffState:
    def test_pass_through_returns_same_package(self):
        with _disable_llm():
            package = _package()
            with patch("app.llm.citations.LLMClient") as client:
                out = maybe_apply_citation_mode(package, "what is x?")
        assert out is package
        assert package.answer == "original extractive answer"
        assert package.citations == []
        client.assert_not_called()

    def test_pass_through_is_instant_no_provider_import_side_effects(self):
        with _disable_llm():
            package = _package()
            out = maybe_apply_citation_mode(package, "q")
        assert out is package


class TestHookOnState:
    def test_synthesizes_answer_with_citations(self):
        with _enable_llm():
            client = MagicMock()
            client.chat.return_value = (
                "Alpha is correct. [1] Beta is also relevant. [2]"
            )
            with patch("app.llm.citations.LLMClient", return_value=client):
                package = _package()
                out = maybe_apply_citation_mode(package, "what is x?")
        assert out is package
        assert "Alpha is correct." in out.answer
        assert out.citations == [
            {"sentence": "Alpha is correct. [1]", "sources": [{"document": "Doc A"}]},
            {"sentence": "Beta is also relevant. [2]", "sources": [{"document": "Doc B"}]},
        ]

    def test_skips_when_provider_url_empty(self, caplog):
        with _enable_llm(url=""):
            with patch("app.llm.citations.LLMClient") as client:
                package = _package()
                out = maybe_apply_citation_mode(package, "q")
        assert out is package
        assert package.answer == "original extractive answer"
        client.assert_not_called()
        assert "llm_provider_url is empty" in caplog.text

    def test_provider_failure_returns_package_unchanged(self):
        with _enable_llm():
            client = MagicMock()
            client.chat.side_effect = LLMError("down")
            with patch("app.llm.citations.LLMClient", return_value=client):
                package = _package()
                out = maybe_apply_citation_mode(package, "q")
        assert out is package
        assert package.answer == "original extractive answer"
        assert package.citations == []


class TestPromptBuilder:
    def test_lists_excerpts_with_indices_and_titles(self):
        prompt = build_citation_prompt(_package(), "what is x?")
        assert prompt.startswith("QUESTION: what is x?")
        assert "[1] Doc A :: Alpha content." in prompt
        assert "[2] Doc B :: Beta content." in prompt


class TestParser:
    def test_extracts_sentences_and_maps_titles(self):
        titles = ["Doc A", "Doc B"]
        result = parse_citation_answer(
            "Alpha is correct. [1] Both matter. [1][2]",
            titles,
        )
        assert result.answer == "Alpha is correct. [1] Both matter. [1][2]"
        assert result.citations == [
            Citation(sentence="Alpha is correct. [1]", document_ids=[1], titles=["Doc A"]),
            Citation(sentence="Both matter. [1][2]", document_ids=[1, 2], titles=["Doc A", "Doc B"]),
        ]

    def test_ignores_sentences_without_citations(self):
        result = parse_citation_answer("No citation here. Cited. [1]", ["Doc A"])
        assert len(result.citations) == 1
        assert result.citations[0].sentence == "Cited. [1]"

    def test_ignores_out_of_range_indices(self):
        result = parse_citation_answer("Cited. [9]", ["Doc A"])
        assert result.citations == [Citation(sentence="Cited. [9]", document_ids=[], titles=[])]


class TestLLMClient:
    def _client(self) -> LLMClient:
        return LLMClient(LLMConfig(
            base_url="https://api.example.test/v1",
            api_key="secret",
            model="gpt-4o-mini",
            timeout_s=30,
            max_tokens=500,
            temperature=0.2,
        ))

    def _resp(self, content: str):
        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_chat_posts_openai_wire_format(self):
        from urllib.request import Request

        resp = self._resp("Hello.")
        sent = {}
        with patch("app.llm.provider.urllib.request.urlopen", return_value=resp) as urlopen:
            self._client().chat("sys", "user text")
        req: Request = urlopen.call_args.args[0]
        sent = json.loads(req.data)
        assert req.full_url == "https://api.example.test/v1/chat/completions"
        assert req.get_header("Authorization") == "Bearer secret"
        assert sent["model"] == "gpt-4o-mini"
        assert sent["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user text"},
        ]
        assert sent["max_tokens"] == 500
        assert sent["temperature"] == 0.2

    def test_chat_returns_content(self):
        with patch("app.llm.provider.urllib.request.urlopen", return_value=self._resp("Yes.")):
            assert self._client().chat("s", "u") == "Yes."

    def test_chat_raises_on_http_error(self):
        import urllib.error

        with patch(
            "app.llm.provider.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("u", 429, "rate", None, None),
        ):
            with pytest.raises(LLMError):
                self._client().chat("s", "u")

    def test_chat_raises_on_missing_content(self):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"choices": [{"message": {}}]}).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch("app.llm.provider.urllib.request.urlopen", return_value=resp):
            with pytest.raises(LLMError):
                self._client().chat("s", "u")

    def test_chat_raises_on_network_error(self):
        import urllib.error

        with patch(
            "app.llm.provider.urllib.request.urlopen",
            side_effect=urllib.error.URLError("no network"),
        ):
            with pytest.raises(LLMError):
                self._client().chat("s", "u")