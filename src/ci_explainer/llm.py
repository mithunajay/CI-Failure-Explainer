"""LLM client interface with an Anthropic implementation and a test fake."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> LLMResponse: ...


class AnthropicClient:
    """Calls the Anthropic Messages API. Needs `pip install anthropic` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str, api_key: str | None = None, max_tokens: int = 700):
        try:
            import anthropic  # lazy import so the core tool has no dependencies
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Install the client first: pip install anthropic") from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("Set ANTHROPIC_API_KEY (see .env.example)")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> LLMResponse:  # pragma: no cover
        start = time.perf_counter()
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return LLMResponse(
            text=text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            latency_s=time.perf_counter() - start,
        )


class FakeClient:
    """Returns scripted replies. Used in tests and for offline demos."""

    def __init__(self, replies: list[str], model: str = "fake"):
        self.replies = list(replies)
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        text = self.replies.pop(0) if self.replies else "{}"
        return LLMResponse(text=text, input_tokens=len(user) // 4,
                           output_tokens=len(text) // 4, latency_s=0.01)


def price_from_env() -> tuple[float | None, float | None]:
    """USD per 1M tokens (input, output) from env. Copy from your provider's pricing page."""
    def _f(name: str) -> float | None:
        v = os.environ.get(name, "").strip()
        return float(v) if v else None
    return _f("CI_EXPLAINER_PRICE_IN"), _f("CI_EXPLAINER_PRICE_OUT")
