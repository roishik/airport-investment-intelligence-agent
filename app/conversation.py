"""The in-memory conversation history, and the one operation voice adds
to it: truncating a reply the user talked over.

This lives in its own module because two request paths now share it —
`app/main.py` (text chat) and `app/voice_api.py` (spoken chat) — and
having the voice endpoints reach into the web module for a private list
would have made the import graph circular for no benefit.

SCOPE, stated plainly: this is a single process-wide history, which is
right for a single-user demo and wrong for anything multi-user. Two
browser tabs share one conversation. Making it per-session is a dict
keyed by a session cookie and about fifteen lines, deliberately not
spent here — see README "Scope and limitations".
"""
from __future__ import annotations

from typing import Any

# Message list in the OpenAI chat format, WITHOUT the system message —
# `agent_loop.run_agent` prepends that itself on every call, so storing it
# here would double it.
_history: list[dict[str, Any]] = []


def snapshot() -> list[dict[str, Any]]:
    """A copy, not the live list. A streaming request must not observe
    another request mutating history halfway through its own turn."""
    return list(_history)


def replace(messages: list[dict[str, Any]]) -> None:
    _history[:] = messages


def clear() -> None:
    _history.clear()


def truncate_last_reply(spoken_prefix: str) -> bool:
    """Rewrite the most recent assistant reply to only what the user
    actually heard, and report whether anything was rewritten.

    This is the third step of barge-in, and the one that is easy to skip
    and expensive to get wrong. Steps one and two — stop speaking, drop
    the audio already queued — are what the user perceives. This step is
    what keeps the conversation coherent afterwards: if the agent was cut
    off four sentences into a nine-sentence answer, the model must not
    believe it said the other five. Otherwise the next turn is built on a
    transcript that never happened, and follow-ups like "what was the
    third one?" answer from text the user never heard.

    Granularity is whole sentences, because sentences are the unit the
    client synthesizes and plays. Word-level truncation would need
    per-word timing from the TTS provider, which neither provider here
    returns from its plain synthesis endpoint. Named limitation, not an
    oversight — see DECISIONS.md.

    An empty `spoken_prefix` means the user interrupted before any audio
    played at all, so the reply is removed outright rather than stored as
    an empty assistant turn.
    """
    for i in range(len(_history) - 1, -1, -1):
        message = _history[i]
        if message.get("role") != "assistant" or not message.get("content"):
            continue
        prefix = spoken_prefix.strip()
        if prefix:
            _history[i] = {**message, "content": prefix}
        else:
            del _history[i]
        return True
    return False
