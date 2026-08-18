"""Minimal FastAPI chat UI shell — reusable across every rep.

Deliberately small: one page (static/index.html), one POST /chat
endpoint, one GET /health, a live tool-call log rendered client-side from
what /chat returns. This is the whole web UI. See README "UI scope — what
NOT to build" for why it stops here: UI polish is not what this brief
asks for, and every hour spent on it is an hour not spent on the scoring
logic and the data.

Run with:
    uvicorn app.main:app --reload
or:
    python -m app.main
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent_loop import MaxTurnsExceeded, run_agent
from app.config import HOST, PORT
from app.providers.llm import get_llm_provider
from app.system_prompt import BASE_SYSTEM_PROMPT
from app.tools import TOOL_REGISTRY, TOOL_SCHEMAS

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="airport-investment-intelligence-agent")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory, single-session history — fine for a single-user demo, not
# for multi-user production. Scope note, not an oversight; see README.
_history: list[dict[str, Any]] = []


class ChatRequest(BaseModel):
    message: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health() -> dict:
    provider = get_llm_provider()
    return {"status": "ok", "provider": provider.name, "model": provider.model}


def _tool_log_rows(entries) -> list[dict]:
    return [
        {"tool_name": e.tool_name, "arguments": e.arguments, "result": e.result, "error": e.error}
        for e in entries
    ]


@app.post("/chat")
async def chat(req: ChatRequest) -> dict:
    provider = get_llm_provider()
    try:
        result = run_agent(
            user_message=req.message,
            history=_history,
            provider=provider,
            tool_schemas=TOOL_SCHEMAS,
            tool_registry=TOOL_REGISTRY,
            system_prompt=BASE_SYSTEM_PROMPT,
        )
    except MaxTurnsExceeded as exc:
        # The termination guarantee firing is a designed outcome, not a
        # server fault, so this is a 200 with an honest partial answer —
        # not a 500 and a blank screen. The tool log is returned in full
        # because the work genuinely happened and is worth showing.
        #
        # History is deliberately NOT updated: the turn never reached a
        # final assistant message, and persisting a truncated transcript
        # would corrupt every subsequent turn in the conversation.
        return {
            "reply": (
                "I hit my tool-call limit before finishing this one. Here's what I did "
                "establish — but treat it as incomplete, not as a final answer. Asking a "
                "narrower question usually gets there."
            ),
            "tool_log": _tool_log_rows(exc.tool_log),
            "incomplete": True,
            "turns_used": exc.turns_used,
        }

    _history[:] = result.messages[1:]  # drop system message; run_agent re-adds it each call
    return {
        "reply": result.final_text,
        "tool_log": _tool_log_rows(result.tool_log),
        "incomplete": False,
        "turns_used": result.turns_used,
    }


@app.post("/reset")
async def reset() -> dict:
    _history.clear()
    return {"status": "reset"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
