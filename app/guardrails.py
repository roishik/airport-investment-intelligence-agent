"""
guardrails.py — tool output, and any other retrieved/external text, is
UNTRUSTED DATA, never instructions.

Any agent that feeds fetched data back into its own prompt inherits this
problem: text arriving from an API, a scraped page, or a pasted document
can carry "ignore previous instructions" / "reveal your system prompt"
payloads that read to the model as if they came from the operator.

This module gives agent_loop.py two things:

  1. wrap_untrusted(text, source) — fences arbitrary text so it's
     unambiguous, IN THE PROMPT ITSELF, that it's data to read, not
     directions to follow. Every tool result gets wrapped before it's
     appended to the message history (see agent_loop.py).
  2. scan_for_injection(text) — a cheap, deterministic pre-filter that
     flags common prompt-injection phrasings BEFORE the text reaches the
     model, so a suspicious tool result can be logged / surfaced / blocked
     rather than silently trusted.

This is not a substitute for a real classifier, an allow-listed tool
surface, or output-side data-loss checks in production — it is the
minimum "treat tool output as data" discipline, made visible, logged, and
testable. See README 'Guardrails — what this is and isn't'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

UNTRUSTED_CLOSE = "</untrusted_data>"

# Deliberately simple regexes with an obvious name, so this list is easy to
# read and easy to extend in a real rep. Not exhaustive — see README for
# what a production version would add (semantic classifier, allow-listed
# tool schemas, output scanning for exfiltrated secrets, etc).
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all )?(the )?(previous|prior|above) instructions", re.I),
    re.compile(r"disregard (all )?(the )?(previous|prior|above)", re.I),
    re.compile(r"reveal (your |the )?system prompt", re.I),
    re.compile(r"print (your |the )?system prompt", re.I),
    re.compile(r"show (me )?(your |the )?(system prompt|instructions)", re.I),
    re.compile(r"you are now (in )?(a )?(developer|debug|dan) mode", re.I),
    re.compile(r"act as (if you (are|were)|an?) (an? )?(unfiltered|unrestricted|jailbroken)", re.I),
    re.compile(r"new instructions?\s*:", re.I),
    re.compile(r"</?(system|assistant)[ >]", re.I),  # fake role-tag injection
    re.compile(r"do anything now", re.I),
    re.compile(r"pretend (you are|to be) (an? )?(ai )?(with no|without) (restrictions|rules|guardrails)", re.I),
]


@dataclass(frozen=True)
class ScanResult:
    flagged: bool
    matched_patterns: tuple[str, ...]


def scan_for_injection(text: str) -> ScanResult:
    """Deterministic, regex-based scan for common prompt-injection
    phrasings. Pure function — no I/O, safe to unit test in isolation."""
    if not text:
        return ScanResult(flagged=False, matched_patterns=())
    matches = tuple(p.pattern for p in _INJECTION_PATTERNS if p.search(text))
    return ScanResult(flagged=bool(matches), matched_patterns=matches)


def wrap_untrusted(text: str, source: str) -> str:
    """Fence external/tool text so the model can't mistake it for
    developer/system instructions, and annotate it if the deterministic
    scanner flagged a likely injection attempt. ALWAYS call this on tool
    output before appending it to the conversation — see agent_loop.py,
    which does this for every tool result with no exceptions.

    The flagged text is still INCLUDED (not silently dropped) — visibility
    beats silent filtering for a take-home demo where "show the guardrail
    catching it" is the point. A production system would additionally
    decide whether to block, redact, or route flagged content to a human;
    see README."""
    scan = scan_for_injection(text)
    header = f'<untrusted_data source="{source}">'
    if scan.flagged:
        header += f"\n<!-- guardrail: flagged patterns {list(scan.matched_patterns)} -->"
    return f"{header}\n{text}\n{UNTRUSTED_CLOSE}"


def unwrap_untrusted(wrapped: str) -> str:
    """Inverse of wrap_untrusted: strip the fence and any guardrail
    comment line, returning the original payload. The real LLM providers
    never need this (they just read the fenced text as part of the
    conversation) — it exists for callers that need the raw payload back,
    e.g. app/providers/llm/mock_llm.py parsing a tool's JSON result, or a
    log viewer that wants to show the clean payload separately from the
    guardrail annotation."""
    lines = wrapped.splitlines()
    if lines and lines[0].startswith("<untrusted_data"):
        lines = lines[1:]
    if lines and lines[0].startswith("<!-- guardrail:"):
        lines = lines[1:]
    if lines and lines[-1].strip() == UNTRUSTED_CLOSE:
        lines = lines[:-1]
    return "\n".join(lines)
