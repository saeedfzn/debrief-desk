"""The CRM layer. SQLite today; this is the one file to swap for a real CRM's API.

Every function returns plain dicts / lists of dicts. Every connection is read-only: nothing here writes to the CRM.
Settings are read from app.config at call time, so tests can point DB_PATH somewhere else.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from app import config

# ---------------------------------------------------------------- connections


def _db_path() -> Path:
    return Path(config.DB_PATH)


class CRMMissing(FileNotFoundError):
    """The sample CRM database has not been built yet."""


MISSING_MESSAGE = "The sample CRM database has not been built yet. Run: py -3 data/seed.py (or python data/seed.py)."


def db_ready() -> bool:
    return _db_path().is_file()


def connect() -> sqlite3.Connection:
    """Open the CRM read-only. There is no writable connection anywhere in the app."""
    path = _db_path()
    if not path.is_file():
        raise CRMMissing(MISSING_MESSAGE)
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _all(sql: str, params: tuple = ()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params: tuple = ()) -> dict | None:
    rows = _all(sql, params)
    return rows[0] if rows else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# Words that say nothing about which firm it is: "Northgate Capital" must not match "Fernhallow Capital".
_GENERIC_FIRM_WORDS = {
    "capital", "trading", "research", "partners", "partner", "llp", "ltd", "limited", "plc", "inc", "llc",
    "group", "management", "asset", "assets", "investments", "investment", "markets", "securities", "fund",
    "funds", "labs", "lab", "ai", "the", "and", "of", "co", "company", "advisors", "advisers", "global",
}


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", _norm(s))


def _best_name_match(query: str, rows: list[dict], person: bool) -> dict | None:
    """Case-insensitive and tolerant, but never a guess.

    1. exact name; 2. the stored name appears whole inside the query ("Fernhallow Capital LLP");
    3. the query's words all appear in exactly one stored name ("marchetti", "fernhallow");
    4. people: surname plus at least one other word in common. Firms: a distinctive word in common,
       with only one firm sharing it. Otherwise None.
    """
    q = _norm(query)
    if not q:
        return None
    q_words = _words(q)
    ignore = set() if person else _GENERIC_FIRM_WORDS
    distinctive_q = [w for w in q_words if w not in ignore and len(w) > 1]
    if not distinctive_q:
        return None
    for r in rows:
        if _norm(r["name"]) == q:
            return r
    padded_q = f" {' '.join(q_words)} "
    inside = [r for r in rows if f" {' '.join(_words(r['name']))} " in padded_q]
    if inside:
        return max(inside, key=lambda r: len(r["name"]))
    covering = [r for r in rows if set(distinctive_q) <= set(_words(r["name"]))]
    if len(covering) == 1:
        return covering[0]
    if len(covering) > 1:
        return None
    if person:
        hits = [r for r in rows
                if _words(r["name"]) and _words(r["name"])[-1] in q_words
                and len(set(q_words) & set(_words(r["name"]))) >= 2]
    else:
        hits = [r for r in rows if set(distinctive_q) & (set(_words(r["name"])) - ignore)]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------- lookups


def list_consultants() -> list[dict]:
    return _all("SELECT id, name, desk FROM consultants ORDER BY id")


def get_consultant(consultant_id: int) -> dict | None:
    return _one("SELECT id, name, desk FROM consultants WHERE id = ?", (consultant_id,))


def list_clients() -> list[dict]:
    return _all("SELECT id, name, kind, city FROM clients ORDER BY id")


def find_client_by_name(name: str) -> dict | None:
    return _best_name_match(name, list_clients(), person=False)


def find_candidate_by_name(name: str) -> dict | None:
    return _best_name_match(name, _all("SELECT * FROM candidates ORDER BY id"), person=True)


def get_application(candidate_id: int, client_id: int) -> dict | None:
    return _one(
        """
        SELECT a.*, r.id AS role_id, r.title AS role_title, r.team AS role_team, r.comp_band,
               c.name AS client_name
        FROM applications a
        JOIN roles r ON r.id = a.role_id
        JOIN clients c ON c.id = r.client_id
        WHERE a.candidate_id = ? AND r.client_id = ?
        ORDER BY (a.status = 'active') DESC, a.stage_updated DESC, a.id DESC
        LIMIT 1
        """,
        (candidate_id, client_id),
    )


def debriefs_for_client(client_id: int) -> list[dict]:
    return _all(
        """
        SELECT d.id, d.application_id, d.candidate_id, d.client_id, d.round, d.held_on, d.title,
               d.transcript, ca.name AS candidate_name, r.title AS role_title, a.role_id
        FROM debriefs d
        JOIN candidates ca ON ca.id = d.candidate_id
        LEFT JOIN applications a ON a.id = d.application_id
        LEFT JOIN roles r ON r.id = a.role_id
        WHERE d.client_id = ?
        ORDER BY d.held_on, d.id
        """,
        (client_id,),
    )


def next_candidates_for_client(client_id: int, exclude_candidate_id: int | None = None,
                               role_id: int | None = None) -> list[dict]:
    """Candidates with an interview booked at this client from today on.

    With role_id, candidates on that same role come first (soonest interview first), then the rest.
    Each row carries role_id, so callers can tell a same-role candidate from a different-role one.
    """
    return _all(
        """
        SELECT ca.id AS candidate_id, ca.name AS candidate_name, ca.known_as, ca.pronouns, r.id AS role_id,
               r.title AS role_title, a.stage, a.next_interview_at, ca.skills, ca.current_title,
               ca.notice_weeks, ca.non_compete_months, a.id AS application_id
        FROM applications a
        JOIN roles r ON r.id = a.role_id
        JOIN candidates ca ON ca.id = a.candidate_id
        WHERE r.client_id = ? AND a.status = 'active'
          AND a.next_interview_at IS NOT NULL AND a.next_interview_at >= ?
          AND (? IS NULL OR ca.id != ?)
        ORDER BY (r.id = ?) DESC, a.next_interview_at, a.id
        """,
        (client_id, config.DEMO_TODAY, exclude_candidate_id, exclude_candidate_id, role_id),
    )


def pipeline_for_consultant(consultant_id: int) -> list[dict]:
    """Active applications for one consultant, with the last contact WITH THE CANDIDATE.

    Only activities with with_party = 'candidate' count: a CV sent to the client, a chase for feedback or an
    internal note is not contact with the candidate. last_call_at is the latest call with the candidate.
    """
    return _all(
        """
        WITH last AS (
          SELECT candidate_id, kind, at, summary,
                 ROW_NUMBER() OVER (PARTITION BY candidate_id ORDER BY at DESC, id DESC) AS rn
          FROM activities
          WHERE with_party = 'candidate'
        ),
        last_call AS (
          SELECT candidate_id, MAX(at) AS at
          FROM activities
          WHERE with_party = 'candidate' AND kind = 'call'
          GROUP BY candidate_id
        )
        SELECT a.id AS application_id, ca.id AS candidate_id, ca.name AS candidate_name,
               ca.known_as, ca.pronouns,
               cl.name AS client_name, r.title AS role_title, r.status AS role_status, a.stage, a.stage_updated,
               a.next_interview_at, a.offer_sent_at, ca.notice_weeks, ca.non_compete_months, ca.phone,
               l.at AS last_contact_at, l.kind AS last_contact_kind, l.summary AS last_contact_summary,
               lc.at AS last_call_at
        FROM applications a
        JOIN candidates ca ON ca.id = a.candidate_id
        JOIN roles r ON r.id = a.role_id
        JOIN clients cl ON cl.id = r.client_id
        LEFT JOIN last l ON l.candidate_id = ca.id AND l.rn = 1
        LEFT JOIN last_call lc ON lc.candidate_id = ca.id
        WHERE ca.consultant_id = ? AND a.status = 'active'
        ORDER BY a.id
        """,
        (consultant_id,),
    )


# ---------------------------------------------------------------- transcripts


def _parse_transcript(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0].strip() if lines else path.stem
    date = None
    for line in lines[1:4]:
        m = re.match(r"^Date:\s*(\d{4}-\d{2}-\d{2})", line.strip())
        if m:
            date = m.group(1)
            break
    return {"id": path.stem, "title": title, "date": date, "text": text}


def list_sample_transcripts() -> list[dict]:
    titles = {r["title"] for r in _all("SELECT title FROM debriefs")}
    out = []
    for path in sorted(Path(config.TRANSCRIPTS_DIR).glob("*.txt")):
        t = _parse_transcript(path)
        out.append({"id": t["id"], "title": t["title"], "date": t["date"], "in_db": t["title"] in titles,
                    "text": t["text"]})
    return out


def schema_text() -> str:
    return Path(config.SCHEMA_PATH).read_text(encoding="utf-8")


# ---------------------------------------------------------------- read-only SQL for "ask the pipeline"

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
_BLOCKED_WORDS = re.compile(
    r"\b(pragma|attach|detach|insert|update|delete|drop|create|alter|vacuum|reindex|analyze|"
    r"begin|commit|rollback|savepoint|release|load_extension)\b|\b(pragma_\w+)",
    re.IGNORECASE,
)
_TICK_OPS = 1000            # SQLite VM instructions between progress-handler ticks
_MAX_STEPS = 50_000         # ticks, i.e. 50 million VM instructions
_MAX_SECONDS = 1.0          # wall-clock cap, whichever comes first
_MAX_LENGTH = 100_000       # longest string or blob a query may build (about 100 KB per value)
_MAX_RESULT_BYTES = 1_000_000  # total size of the text and blob cells returned (about 1 MB)


def _authorizer(action, arg1, arg2, dbname, source):
    if action in _ALLOWED_ACTIONS:
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _strip_literals(sql: str) -> str:
    """Blank out quoted strings and quoted identifiers so keyword and ';' checks don't trip on text inside them."""
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    return re.sub(r'"(?:[^"]|"")*"', '"x"', sql)


def run_readonly_sql(sql: str, limit: int = 200) -> dict:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("The query is empty.")
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    bare = _strip_literals(text)
    if "--" in bare or "/*" in bare:
        raise ValueError("Comments are not allowed in the query.")
    if ";" in bare:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"^(select|with)\b", bare, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    bad = _BLOCKED_WORDS.search(bare)
    if bad:
        raise ValueError(f"'{bad.group(0).upper()}' is not allowed. The pipeline can only be read.")
    if not sqlite3.complete_statement(text + ";"):
        raise ValueError("The query looks incomplete.")
    limit = max(1, min(int(limit), 1000))

    try:
        conn = connect()
    except FileNotFoundError as e:
        raise ValueError(str(e)) from None
    try:
        conn.row_factory = None
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_LENGTH)
        conn.set_authorizer(_authorizer)
        steps = [0]
        deadline = time.perf_counter() + _MAX_SECONDS

        def _tick():
            steps[0] += 1
            return 1 if steps[0] > _MAX_STEPS or time.perf_counter() > deadline else 0

        conn.set_progress_handler(_tick, _TICK_OPS)
        try:
            cur = conn.execute(text)
            rows, size = [], 0
            for _ in range(limit + 1):  # row by row, so an oversized result stops early
                r = cur.fetchone()
                if r is None:
                    break
                size += sum(len(v.encode("utf-8")) if isinstance(v, str) else len(v)
                            for v in r if isinstance(v, (str, bytes)))
                if size > _MAX_RESULT_BYTES:
                    raise ValueError("That result is too large to show.")
                rows.append(r)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "not authorized" in msg:
                raise ValueError("That query tries to do something other than read the pipeline.") from None
            if "interrupted" in msg:
                raise ValueError("The query took too long and was stopped.") from None
            if "too big" in msg:
                raise ValueError("The query built a value that is too large and was stopped.") from None
            raise ValueError(f"The query failed: {msg}") from None
        except (sqlite3.Warning, sqlite3.ProgrammingError) as e:
            raise ValueError(f"The query was rejected: {e}") from None
        columns = [d[0] for d in (cur.description or [])]
        truncated = len(rows) > limit
        return {"columns": columns, "rows": [list(r) for r in rows[:limit]], "truncated": truncated}
    finally:
        conn.close()
