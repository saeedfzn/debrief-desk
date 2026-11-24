"""FastAPI app. Run: py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8770"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import ask as ask_mod
from app import calllist, config, crm, debrief, llm

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Debrief Desk")


def _err(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, **extra})


@app.exception_handler(llm.LLMUnavailable)
def _no_key(request: Request, exc: llm.LLMUnavailable):
    return _err(503, "No API key is set on the server, so live runs are off. Set ANTHROPIC_API_KEY and restart.")


@app.exception_handler(llm.LLMError)
def _llm_failed(request: Request, exc: llm.LLMError):
    return _err(502, str(exc))


@app.exception_handler(crm.CRMMissing)
def _no_db(request: Request, exc: crm.CRMMissing):
    return _err(503, crm.MISSING_MESSAGE)


def _db_missing() -> JSONResponse | None:
    """Checked before any model call, so a missing database never costs one."""
    return None if crm.db_ready() else _err(503, crm.MISSING_MESSAGE)


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "live", "model": llm.model_label(), "today": config.DEMO_TODAY, "has_key": llm.has_key(),
            "has_db": crm.db_ready()}


@app.get("/api/transcripts")
def transcripts():
    if (missing := _db_missing()):
        return missing
    return [{k: t.get(k) for k in ("id", "title", "date", "in_db")} for t in crm.list_sample_transcripts()]


@app.get("/api/transcripts/{tid}")
def transcript(tid: str):
    if (missing := _db_missing()):
        return missing
    for t in crm.list_sample_transcripts():
        if t.get("id") == tid:
            return {k: t.get(k) for k in ("id", "title", "date", "in_db", "text")}
    return _err(404, f"No sample transcript called {tid}.")


@app.post("/api/debrief")
def run_debrief(body: dict):
    text = (body or {}).get("transcript") or ""
    if not text.strip():
        return _err(400, "Paste a debrief transcript first.")
    if (missing := _db_missing()):
        return missing
    if not llm.has_key():
        raise llm.LLMUnavailable("no key")
    return debrief.run_debrief(text)


@app.get("/api/consultants")
def consultants():
    if (missing := _db_missing()):
        return missing
    return [{k: c.get(k) for k in ("id", "name", "desk")} for c in crm.list_consultants()]


@app.get("/api/calllist")
def get_calllist(consultant_id: int = 1):
    if (missing := _db_missing()):
        return missing
    try:
        return calllist.build_call_list(consultant_id)
    except LookupError as e:
        return _err(404, str(e))


@app.post("/api/ask")
def ask(body: dict):
    question = (body or {}).get("question") or ""
    if (missing := _db_missing()):
        return missing
    if not llm.has_key():
        raise llm.LLMUnavailable("no key")
    try:
        return ask_mod.ask(question)
    except ask_mod.AskError as e:
        return _err(400, e.message, sql=e.sql)


@app.get("/")
def index():
    page = ROOT / "index.html"
    if not page.exists():
        return _err(404, "index.html is missing.")
    return FileResponse(page, media_type="text/html")


app.mount("/saved", StaticFiles(directory=ROOT / "saved", check_dir=False), name="saved")
