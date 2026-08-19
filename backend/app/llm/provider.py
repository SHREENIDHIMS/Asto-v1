"""Hosted LLM provider client (DEC-1 seam; not called while OFF).

A deliberately thin OpenAI-compatible ``POST {base_url}/chat/completions``
client built on the standard library (``urllib``), so the seam adds no new
runtime dependency. It works against OpenAI, Azure, Anthropic-via-gateway,
or a self-hosted vLLM/llama.cpp endpoint — anything that speaks the OpenAI
chat-completions wire format.

DEC-1 is closed as "No" today: nothing in the request-serving path calls an
LLM and every answer stays verbatim from a source. This client exists only
so that a future decision to flip ``ASTO_LLM_ENABLED`` can activate the
cite-with-LLM mode without new plumbing. Errors raise :class:`LLMError`
which the caller treats as best-effort (never crash a request).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(Exception):
    """Raised for any provider, HTTP, or parse failure."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_s: float = 30
    max_tokens: int = 500
    temperature: float = 0.2


class LLMClient:
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def chat(self, system: str, user: str) -> str:
        """Send one chat turn and return the assistant's text content."""
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM response missing content: {exc}") from exc
        if not isinstance(content, str):
            raise LLMError("LLM response content is not text")
        return content