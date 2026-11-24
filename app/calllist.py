"""Feature 2: today's call list for one consultant.

Code decides the order (score_row below). The model only writes the reason and the opening line.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

from app import config, crm, llm, prompts

TOP_N = 10

# How many days without contact is fine at each stage before it starts to cost points.
CONTACT_GAP_OK = {"offer": 2, "final_round": 4, "second_round": 5, "first_round": 7,
                  "submitted": 7, "screened": 10, "sourced": 14}
INTERVIEW_STAGES = {"first_round", "second_round", "final_round"}
EARLY_STAGES = {"sourced", "screened", "submitted"}
NON_COMPETE_STAGES = {"first_round", "second_round", "final_round", "offer"}


def _d(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    try:
        return datetime.strptime(s[:16].replace("T", " "), "%Y-%m-%d %H:%M")
    except ValueError:
        pass
    d = _d(s)
    return datetime(d.year, d.month, d.day, 9, 0) if d else None


def working_days_between(start: date, end: date) -> int:
    """Monday to Friday days after start, up to and including end."""
    if end <= start:
        return 0
    n, day = 0, start
    while day < end:
        day += timedelta(days=1)
        if day.weekday() < 5:
            n += 1
    return n


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def interview_window_end(today: date) -> date:
    """The last day of the interview window: the end of the next two working days after today."""
    day, n = today, 0
    while n < 2:
        day += timedelta(days=1)
        if day.weekday() < 5:
            n += 1
    return day


def score_row(row: dict, today) -> tuple[int, list[dict]]:
    """Score one active application. Higher score = call sooner. Pure, deterministic, no I/O.

    `today` is a date or an ISO string. "Now" is taken as 08:00 on that day. Applications on a role that is
    not open (on hold, filled) are left out of the call list before scoring, in build_call_list.

    | Signal                                                                         | Points                         |
    |--------------------------------------------------------------------------------|--------------------------------|
    | Offer out, no contact since it was sent                                        | 40, +2 per working day, max 50 |
    | Offer out, in touch since it was sent (or at offer stage, no date logged)      | 30                             |
    | Interview by the end of the next two working days, no call in the last 3 days  | 35                             |
    | Interview by the end of the next two working days, prep call logged            | 15                             |
    | Final round, no contact for 8+ days                                            | 30                             |
    | Final round, in touch                                                          | 20                             |
    | Early stage (sourced/screened/submitted), no contact for 14+ days, or never    | 12                             |
    | Days since last contact beyond what the stage allows (see below), only when    | 1 per day over, max 20         |
    |   none of the three silence signals fired (offer no contact since, final round |                                |
    |   no contact for 8+ days, early stage 14+ days)                                |                                |
    | Non-compete of 6+ months, from first round to offer                            | 10 (15 if 12+ months)          |

    Days a stage allows without contact: offer 2, final_round 4, second_round 5, first_round 7,
    submitted 7, screened 10, sourced 14. No contact ever logged counts as 99 days.
    The score is the sum of the factor points.

    What this guarantees: an early-stage row scores at most 12, so any open offer (30+), any final round (20+)
    and any interview in the window (15+) is always above a stale early-stage lead.
    """
    today = _d(today) if not isinstance(today, date) else today
    now = datetime(today.year, today.month, today.day, 8, 0)
    stage = (row.get("stage") or "").strip()
    last = _d(row.get("last_contact_at"))
    days_since = (today - last).days if last else 99
    factors: list[dict] = []
    silence = False  # a stage-specific "gone quiet" signal fired, so the generic gap is not added on top

    # Offer out
    offer_at = _d(row.get("offer_sent_at"))
    if stage == "offer" or offer_at:
        if offer_at and (last is None or last <= offer_at):
            wd = working_days_between(offer_at, today)
            factors.append({"label": f"Offer out {_plural(wd, 'working day')}, no contact since",
                            "points": min(50, 40 + 2 * wd)})
            silence = True
        elif offer_at:
            factors.append({"label": "Offer out, in touch since it was sent", "points": 30})
        else:
            factors.append({"label": "At offer stage, keep in touch", "points": 30})

    # Interview by the end of the next two working days
    iv = _dt(row.get("next_interview_at"))
    if iv and iv >= now and iv.date() <= interview_window_end(today):
        when = "today" if iv.date() == today else ("tomorrow" if iv.date() == today + timedelta(days=1)
                                                   else iv.strftime("%a %d %b"))
        prepped = row.get("last_contact_kind") == "call" and last is not None and days_since <= 3
        if prepped:
            factors.append({"label": f"Interview {when}, prep call logged", "points": 15})
        else:
            factors.append({"label": f"Interview {when}, no prep call logged", "points": 35})

    # Final round
    if stage == "final_round":
        if days_since >= 8:
            factors.append({"label": f"Final round, no contact for {_plural(days_since, 'day')}"
                            if last else "Final round, no contact logged", "points": 30})
            silence = True
        else:
            factors.append({"label": "Final round in progress", "points": 20})

    # Early stage gone stale
    if stage in EARLY_STAGES and days_since >= 14:
        factors.append({"label": f"Early stage, stale for {_plural(days_since, 'day')}" if last
                        else "Early stage, never contacted", "points": 12})
        silence = True

    # Contact gap by stage, only when no silence signal above already covers it
    allowed = CONTACT_GAP_OK.get(stage)
    if not silence and allowed is not None and days_since > allowed:
        pts = min(20, days_since - allowed)
        label = (f"{_plural(days_since, 'day')} since last contact ({stage.replace('_', ' ')} allows {allowed})"
                 if last else "No contact logged yet")
        factors.append({"label": label, "points": pts})

    # Long non-compete
    nc = row.get("non_compete_months") or 0
    try:
        nc = int(nc)
    except (TypeError, ValueError):
        nc = 0
    if nc >= 6 and stage in NON_COMPETE_STAGES:
        factors.append({"label": f"{nc}-month non-compete, worth an early talk on timing",
                        "points": 15 if nc >= 12 else 10})

    return sum(f["points"] for f in factors), factors


def _last_contact_text(row: dict) -> str:
    if not row.get("last_contact_at"):
        return "No contact logged"
    s = f"{str(row['last_contact_at'])[:10]} {row.get('last_contact_kind') or 'contact'}"
    if row.get("last_contact_summary"):
        s += f": {row['last_contact_summary']}"
    return s


def greeting_name(row: dict) -> str:
    """The name to greet a candidate by: known_as from the CRM, else the full name (never a blind split)."""
    return (row.get("known_as") or row.get("candidate_name") or "").strip() or "there"


def _first_name(name: str | None) -> str:
    return (name or "").split()[0] if name else ""


def _template(call: dict, consultant_first: str) -> tuple[str, str]:
    top = call["factors"][0]["label"] if call["factors"] else "Regular check-in"
    hi = f"Hi {call['_greet']}, it's {consultant_first}." if consultant_first else f"Hi {call['_greet']}."
    reason = f"{top} on the {call['role']} process at {call['client']}."
    label = top.lower()
    if "offer" in label:
        opener = f"{hi} How are you feeling about the {call['client']} offer?"
    elif "interview" in label:
        opener = f"{hi} Have you got ten minutes to run through your {call['client']} interview?"
    elif "non-compete" in label:
        opener = f"{hi} Have you got a few minutes to talk through timings around your notice and non-compete?"
    else:
        opener = f"{hi} I wanted to catch up on where you are with the {call['client']} process."
    return reason, opener


def build_call_list(consultant_id: int) -> dict:
    """Rank the consultant's active applications and word the top ten."""
    t0 = time.perf_counter()
    consultant = crm.get_consultant(int(consultant_id))
    if not consultant:
        raise LookupError(f"No consultant with id {consultant_id}.")
    today = config.DEMO_TODAY
    scored = []
    for row in crm.pipeline_for_consultant(int(consultant_id)):
        if (row.get("role_status") or "open") != "open":
            continue  # on hold or filled: nothing to push today, and it must never outrank live work
        score, factors = score_row(row, today)
        if score <= 0:
            continue
        iv = _dt(row.get("next_interview_at"))
        scored.append((score, iv or datetime.max, row.get("candidate_name") or "", row.get("application_id") or 0,
                       row, factors))
    scored.sort(key=lambda t: (-t[0], t[1], t[2], t[3]))

    seen, calls = set(), []
    for score, _, _, _, row, factors in scored:
        if row.get("candidate_id") in seen:
            continue
        seen.add(row.get("candidate_id"))
        factors = sorted(factors, key=lambda f: -f["points"])
        calls.append({"rank": len(calls) + 1, "candidate": row.get("candidate_name"), "phone": row.get("phone") or "",
                      "client": row.get("client_name"), "role": row.get("role_title"), "stage": row.get("stage"),
                      "score": score, "factors": factors, "last_contact": _last_contact_text(row),
                      "reason": "", "opener": "", "_greet": greeting_name(row),
                      "_facts": {"greet_as": greeting_name(row), "pronouns": row.get("pronouns") or "they",
                                 "next_interview_at": row.get("next_interview_at"),
                                 "offer_sent_at": row.get("offer_sent_at"),
                                 "notice_weeks": row.get("notice_weeks"),
                                 "non_compete_months": row.get("non_compete_months")}})
        if len(calls) == TOP_N:
            break

    consultant_first = _first_name(consultant.get("name"))
    meta = {"model": llm.model_name(), "ms": 0, "wording": "template"}
    worded = False
    if calls:
        try:
            payload = [{"rank": c["rank"], "candidate": c["candidate"], "client": c["client"], "role": c["role"],
                        "stage": c["stage"], "factors": [f["label"] for f in c["factors"]],
                        "last_contact": c["last_contact"], **c["_facts"]} for c in calls]
            user = (f"Today: {today} ({date.fromisoformat(str(today)).strftime('%A')})\n"
                    f"Consultant's first name, to use in the opener: {consultant_first}\n\n"
                    "Calls in order (JSON). last_contact is the consultant's own internal CRM note: the candidate"
                    " has not seen it.\n" + json.dumps(payload, indent=1, default=str))
            data, m = llm.call_json(prompts.CALLLIST_SYSTEM, user, max_tokens=6000)
            by_rank = {}
            for item in data.get("calls") or []:
                if isinstance(item, dict) and item.get("reason") and item.get("opener"):
                    try:
                        by_rank[int(item.get("rank"))] = item
                    except (TypeError, ValueError):
                        pass
            if all(c["rank"] in by_rank for c in calls):
                for c in calls:
                    c["reason"] = str(by_rank[c["rank"]]["reason"]).strip()
                    c["opener"] = str(by_rank[c["rank"]]["opener"]).strip()
                meta.update(model=m.get("model") or meta["model"], wording="model",
                            input_tokens=m.get("input_tokens", 0), output_tokens=m.get("output_tokens", 0))
                worded = True
        except Exception:  # any model problem: the list still works with template wording
            worded = False
    for c in calls:
        if not worded:
            c["reason"], c["opener"] = _template(c, consultant_first)
        c.pop("_facts", None)
        c.pop("_greet", None)
    meta["ms"] = int((time.perf_counter() - t0) * 1000)
    return {"consultant": {"id": consultant.get("id"), "name": consultant.get("name"), "desk": consultant.get("desk")},
            "date": today, "calls": calls, "meta": meta}
