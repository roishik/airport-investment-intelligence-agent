"""Mock LLM provider — no network calls, no API key required.

This is what makes the whole app runnable end-to-end with zero
setup: `LLM_PROVIDER=mock` (the default — see app/config.py) exercises
the real agent loop, the real tool-calling protocol, the real guardrail
wrapping, and the real chat UI, without ever touching the network. Swap
to LLM_PROVIDER=openai or =anthropic once a rep has a live key; nothing
else changes. See README "Running without an API key".

Scripted, two-phase behavior:
  - Turn 1 (no tool result in the transcript yet): request a
    `compare_items` tool call, with item ids parsed out of the user's
    message if present, else falling back to the full example dataset.
  - Turn 2+ (a tool result is present): read the most recent tool
    result and phrase a real explanation FROM it — never a fabricated
    number. This mirrors the "explain a score you never computed" rule
    the real providers are also bound by via the system prompt.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.guardrails import unwrap_untrusted
from app.providers.llm.base import LLMResponse, ToolCall

_ITEM_ID_RE = re.compile(r"\boption_[a-z0-9]+\b", re.I)


class MockLLMProvider:
    name = "mock"
    model = "mock-v1"

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        has_tool_result = any(m.get("role") == "tool" for m in messages)

        if not has_tool_result:
            return self._request_tool_call(messages)
        return self._explain_tool_result(messages)

    def _request_tool_call(self, messages: list[dict[str, Any]]) -> LLMResponse:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        ids = _ITEM_ID_RE.findall(last_user) if isinstance(last_user, str) else []
        if not ids:
            ids = ["option_a", "option_b", "option_c"]
        # dedupe, preserve order
        seen: set[str] = set()
        ids = [i for i in ids if not (i.lower() in seen or seen.add(i.lower()))]
        return LLMResponse(
            content=None,
            tool_calls=(ToolCall(id="call_1", name="compare_items", arguments={"item_ids": ids}),),
            provider=self.name,
            model=self.model,
        )

    def _explain_tool_result(self, messages: list[dict[str, Any]]) -> LLMResponse:
        tool_msg = next(m for m in reversed(messages) if m.get("role") == "tool")
        try:
            payload = json.loads(unwrap_untrusted(tool_msg["content"]))
            ranking = payload["ranking"]
            top = ranking[0]
            lines = [
                f"Based on the deterministic scoring tool, {top['item_id']} ranks first "
                f"with a total score of {top['total_score']} (out of 1.0)."
            ]
            for comp in top["components"]:
                lines.append(
                    f"- {comp['criterion']}: raw value {comp['raw_value']}, "
                    f"normalized {comp['normalized_score']}, weight {comp['weight']} "
                    f"-> contributes {comp['contribution']} to the total."
                )
            if len(ranking) > 1:
                rest = ", ".join(f"{r['item_id']} ({r['total_score']})" for r in ranking[1:])
                lines.append(f"Runner(s)-up: {rest}.")
            text = "\n".join(lines)
        except Exception:
            text = "I ran the comparison tool but could not parse its result — see the raw tool output above."
        return LLMResponse(content=text, tool_calls=(), provider=self.name, model=self.model)
