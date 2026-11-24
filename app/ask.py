"""Feature 3: a plain-English question -> one read-only SQL query -> table and a short answer."""
from __future__ import annotations

import json
import time
from datetime import date

from app import config, crm, llm, prompts


class AskError(ValueError):
    """The question could not be turned into a safe, working query. Carries the SQL (may be empty)."""

    def __init__(self, message: str, sql: str = ""):
        super().__init__(message)
        self.message = message
        self.sql = sql or ""


def _today_parts():
    d = date.fromisoformat(config.DEMO_TODAY)
    return config.DEMO_TODAY, d.strftime("%A")


def _plain(v) -> str:
    if v is None:
        return "none"
    if isinstance(v, float):
        return f"{v:,.1f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def ask(question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise AskError("Please type a question.")
    t0 = time.perf_counter()
    today, weekday = _today_parts()
    calls, tin, tout, model = 0, 0, 0, llm.model_name()

    system = prompts.ASK_SQL_SYSTEM.format(today=today, weekday=weekday, schema=crm.schema_text())
    data, m = llm.call_json(system, f"Question: {question}", max_tokens=6000)
    calls += 1
    tin += m.get("input_tokens", 0)
    tout += m.get("output_tokens", 0)
    model = m.get("model") or model
    sql = (data.get("sql") or "").strip() if isinstance(data.get("sql"), str) else ""
    if not sql:
        raise AskError(data.get("note") or "That question cannot be answered from the pipeline data.", "")

    try:
        result = crm.run_readonly_sql(sql)
    except ValueError as e:
        raise AskError(str(e), sql) from e
    except Exception as e:  # sqlite errors and the like
        raise AskError(f"The query did not run: {e}", sql) from e
    columns, rows = list(result.get("columns") or []), [list(r) for r in (result.get("rows") or [])]
    # More rows than the guard returns, or exactly as many as a LIMIT of that size: either way the total is not known.
    truncated = bool(result.get("truncated")) or len(rows) >= 200

    if not rows:
        answer = "Nothing in the pipeline matches that question."
    elif len(rows) == 1 and len(columns) == 1 and not truncated:
        answer = f"{columns[0].replace('_', ' ').capitalize()}: {_plain(rows[0][0])}."
    else:
        shown = rows[:60]
        more = ", first 60 shown" if len(rows) > 60 else ""
        if truncated:
            count_line = (f"Rows (only the first {len(rows)} were returned and there may be more, so the total is"
                          f" not known; do not state a total{more}):\n")
        else:
            count_line = f"Rows ({len(rows)} in total{more}):\n"
        user = f"Question: {question}\nColumns: {json.dumps(columns)}\n" + count_line + json.dumps(shown, default=str)
        try:
            a, m2 = llm.call_json(prompts.ASK_ANSWER_SYSTEM.format(today=today), user, max_tokens=3000)
            calls += 1
            tin += m2.get("input_tokens", 0)
            tout += m2.get("output_tokens", 0)
            answer = str(a.get("answer") or "").strip()
        except llm.LLMUnavailable:
            raise
        except Exception:
            answer = ""
        if not answer:
            answer = (f"At least {len(rows)} rows match that question." if truncated else
                      f"{len(rows)} {'row matches' if len(rows) == 1 else 'rows match'} that question.")
        if truncated:
            answer = answer.rstrip() + f" (This shows the first {len(rows)} rows only; there may be more.)"

    return {"question": question, "sql": sql, "columns": columns, "rows": rows, "answer": answer,
            "meta": {"model": model, "ms": int((time.perf_counter() - t0) * 1000), "calls": calls,
                     "input_tokens": tin, "output_tokens": tout, "row_count": len(rows), "truncated": truncated,
                     "note": data.get("note") or ""}}
