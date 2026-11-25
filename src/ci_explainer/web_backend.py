"""Backend entry point used by the local web application."""
from __future__ import annotations

import os

from .explainer import Explanation, explain
from .llm import AnthropicClient


def explain_log(
    raw_log: str,
    use_model: bool,
    model: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 700,
) -> Explanation:
    if not raw_log.strip():
        raise ValueError("Paste a CI log or upload a log file before analyzing.")

    client = None
    if use_model:
        selected_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not selected_key:
            raise RuntimeError(
                "Anthropic mode needs ANTHROPIC_API_KEY. Add it to your local .env file "
                "or enter it in the sidebar, or select Rules only."
            )
        selected_model = model or os.environ.get(
            "CI_EXPLAINER_MODEL", "claude-haiku-5-5"
        )
        if not 1 <= max_tokens <= 8192:
            raise ValueError("Maximum response tokens must be between 1 and 8192.")
        client = AnthropicClient(selected_model, api_key=selected_key, max_tokens=max_tokens)

    return explain(raw_log, client)
