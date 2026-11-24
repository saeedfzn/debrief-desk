"""Feature 1: debrief transcript -> CRM note, two draft emails, and a prep pack for the next candidate."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from app import config, crm, llm, prompts

HEADER_RE = re.compile(
    r"^\s*Debrief call:\s*(?P<cand>.+?)\s+after\s+(?P<round>.+?)\s+at\s+(?P<client>.+?)\s*(?:\((?P<role>[^)]*)\))?\s*$",
    re.I)
DATE_RE = re.compile(r"^\s*Date:\s*(\d{4}-\d{2}-\d{2})", re.I | re.M)


def parse_header(text: str) -> dict:
    """Read the 'Debrief call: X after Y at Z (Role)' and 'Date:' lines. Missing parts come back as None."""
    out = {"candidate": None, "round": None, "client": None, "role": None, "date": None}
    head = (text or "").strip().splitlines()[:6]
    for line in head:
        m = HEADER_RE.match(line)
        if m:
            out.update(candidate=m.group("cand").strip(), round=m.group("round").strip(),
                       client=m.group("client").strip(), role=(m.group("role") or "").strip() or None)
            break
    d = DATE_RE.search("\n".join(head))
    if d:
        out["date"] = d.group(1)
    return out


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _first_name(name: str | None) -> str:
    return name.split()[0] if name else ""


def _match(text: str) -> dict:
    """Match the candidate, client, application and consultant in the CRM."""
    hdr = parse_header(text)
    cand = crm.find_candidate_by_name(hdr["candidate"]) if hdr["candidate"] else None
    client = crm.find_client_by_name(hdr["client"]) if hdr["client"] else None
    app = crm.get_application(cand["id"], client["id"]) if cand and client else None
    consultant = crm.get_consultant(cand["consultant_id"]) if cand and cand.get("consultant_id") else None
    return {"header": hdr, "candidate": cand, "client": client, "application": app, "consultant": consultant}


def date_guide(call_date: str | None) -> str:
    """Spell out the call date and the days after it, so relative dates in the transcript resolve correctly."""
    try:
        d = date.fromisoformat(str(call_date)[:10])
    except (TypeError, ValueError):
        return "The transcript has no Date line: treat relative dates as relative to today's date."
    after = []
    for i in range(1, 11):
        x = d + timedelta(days=i)
        after.append(("tomorrow = " if i == 1 else "") + f"{x.strftime('%a')} {x.isoformat()}")
    mon = d - timedelta(days=d.weekday())
    return (f"The call took place on {d.strftime('%A')} {d.isoformat()}. Every relative date in the transcript"
            f" (tomorrow, Friday, next week, last week) is relative to {d.isoformat()}, not to today.\n"
            f"Days after the call: {'; '.join(after)}.\n"
            f"'Last week' as said on the call means the week starting Mon {(mon - timedelta(days=7)).isoformat()};"
            f" 'next week' means the week starting Mon {(mon + timedelta(days=7)).isoformat()}.")


def _crm_context(m: dict) -> dict:
    cand, app = m["candidate"], m["application"]
    ctx = {"today": config.DEMO_TODAY, "call_date": m["header"].get("date")}
    if m["consultant"]:
        ctx["consultant"] = {"name": m["consultant"].get("name"),
                             "first_name_to_sign_with": _first_name(m["consultant"].get("name"))}
    if cand:
        ctx["candidate"] = {k: cand.get(k) for k in ("name", "known_as", "pronouns", "current_employer",
                                                     "current_title", "location", "skills", "base_salary",
                                                     "currency", "notice_weeks", "non_compete_months")}
        ctx["candidate"]["pronouns"] = ctx["candidate"].get("pronouns") or "they"
    if m["client"]:
        ctx["client"] = {k: m["client"].get(k) for k in ("name", "kind", "city")}
    if app:
        ctx["application"] = {k: app.get(k) for k in ("role_title", "stage", "stage_updated", "next_interview_at",
                                                      "offer_sent_at", "status")}
    return ctx


def _note_and_emails(text: str, m: dict):
    ctx = _crm_context(m)
    user = (date_guide(m["header"].get("date")) + "\n\n"
            f"CRM record as it stands today, {config.DEMO_TODAY} (JSON). It may show changes made after the call:"
            " describe the call as of its own date and do not comment on those later changes.\n"
            + json.dumps(ctx, indent=1, default=str)
            + "\n\nDebrief transcript:\n<<<\n" + text.strip() + "\n>>>")
    return llm.call_json(prompts.DEBRIEF_SYSTEM, user, max_tokens=16000, effort="medium")


def _debriefs_to_use(text: str, m: dict) -> list[dict]:
    """All debriefs on file for the client plus this one, without counting the same call twice."""
    hdr = m["header"]
    this = {"candidate_name": (m["candidate"] or {}).get("name") or hdr["candidate"] or "Unknown candidate",
            "round": hdr["round"] or "not stated", "held_on": hdr["date"] or config.DEMO_TODAY, "transcript": text,
            "role_title": (m["application"] or {}).get("role_title") or hdr["role"],
            "role_id": (m["application"] or {}).get("role_id")}
    if not m["client"]:
        return [this]
    on_file = list(crm.debriefs_for_client(m["client"]["id"]))
    this_norm = _norm(text)
    dup = any(_norm(d.get("transcript")) == this_norm for d in on_file) or any(
        hdr["date"] and _norm(d.get("candidate_name")) == _norm(this["candidate_name"])
        and str(d.get("held_on", ""))[:10] == hdr["date"] for d in on_file)
    return on_file if dup else on_file + [this]


def same_role(d: dict, role_id, role_title: str | None) -> bool:
    """Is this debrief (or candidate row) about the given role? By role id when both sides have one, else by title."""
    if role_id is not None and d.get("role_id") is not None:
        return int(d["role_id"]) == int(role_id)
    return bool(role_title) and _norm(d.get("role_title")) == _norm(role_title)


def order_debriefs(debriefs: list[dict], role_id, role_title: str | None) -> list[dict]:
    """Same-role debriefs first, then other roles at the firm; each group keeps its date order."""
    same = [d for d in debriefs if same_role(d, role_id, role_title)]
    return same + [d for d in debriefs if not same_role(d, role_id, role_title)]


def _prep_pack(debriefs: list[dict], next_cand: dict | None, client_name: str, role: str, role_id=None):
    parts = []
    n_same = sum(1 for d in debriefs if same_role(d, role_id, role))
    for i, d in enumerate(debriefs, 1):
        tag = ("SAME ROLE: use for the process and the questions" if same_role(d, role_id, role) else
               "OTHER ROLE at this firm: firm-wide points only, and say they came from a different role")
        parts.append(f"=== Debrief {i} of {len(debriefs)} [{tag}]: {d.get('round')} for the role "
                     f"'{d.get('role_title') or 'not stated'}', call dated {str(d.get('held_on'))[:10]} ===\n"
                     + (d.get("transcript") or "").strip())
    if next_cand:
        who = "Next candidate on this role (JSON): " + json.dumps(
            {k: next_cand.get(k) for k in ("candidate_name", "known_as", "pronouns", "current_title", "skills",
                                           "role_title", "stage", "next_interview_at", "notice_weeks",
                                           "non_compete_months")}, default=str)
    else:
        who = ("No other candidate has an interview booked for this role yet: write the pack for whoever"
               " interviews next on this role, without addressing anyone by name.")
    user = (f"Today: {config.DEMO_TODAY}\nFirm: {client_name}\nRole the pack is for: {role}\n{who}\n\n"
            f"Number of debriefs: {len(debriefs)} ({n_same} for this role, {len(debriefs) - n_same} for other roles)"
            "\n\n" + "\n\n".join(parts))
    return llm.call_json(prompts.PREP_SYSTEM, user, max_tokens=16000, effort="medium")


def _list(v):
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def _clean_note(n) -> dict:
    n = n if isinstance(n, dict) else {}
    comp = n.get("compensation") if isinstance(n.get("compensation"), dict) else {}
    return {
        "headline": n.get("headline") or "",
        "stage_after": n.get("stage_after") or "",
        "how_it_went": n.get("how_it_went") or "",
        "rounds": [{"round": r.get("round", ""), "format": r.get("format", ""), "asked": _list(r.get("asked")),
                    "candidate_view": r.get("candidate_view", "")}
                   for r in _list(n.get("rounds")) if isinstance(r, dict)],
        "compensation": {"current": comp.get("current") or "not discussed",
                         "expectation": comp.get("expectation") or "not discussed",
                         "notes": comp.get("notes") or ""},
        "notice_and_non_compete": n.get("notice_and_non_compete") or "not discussed",
        "competing_processes": _list(n.get("competing_processes")),
        "risks": _list(n.get("risks")),
        "next_actions": [{"action": a.get("action", ""), "owner": a.get("owner", "consultant"), "due": a.get("due", "")}
                         for a in _list(n.get("next_actions")) if isinstance(a, dict)],
    }


def _clean_pack(p, n_debriefs: int) -> dict:
    p = p if isinstance(p, dict) else {}
    themes = []
    for t in _list(p.get("question_themes")):
        if not isinstance(t, dict):
            continue
        try:
            seen = int(t.get("seen_in") or 1)
        except (TypeError, ValueError):
            seen = 1
        themes.append({"theme": t.get("theme", ""), "examples": _list(t.get("examples")),
                       "seen_in": max(1, min(seen, n_debriefs))})
    return {
        "process": [{"round": r.get("round", ""), "format": r.get("format", ""), "who": r.get("who") or "not discussed",
                     "what_they_look_for": r.get("what_they_look_for", "")}
                    for r in _list(p.get("process")) if isinstance(r, dict)],
        "question_themes": themes,
        "went_well": _list(p.get("went_well")),
        "tripped_people_up": _list(p.get("tripped_people_up")),
        "advice": _list(p.get("advice")),
        "logistics": _list(p.get("logistics")),
    }


def run_debrief(transcript: str) -> dict:
    """Run feature 1 on one transcript. Two model calls, run side by side."""
    if not transcript or not transcript.strip():
        raise ValueError("The transcript is empty.")
    t0 = time.perf_counter()
    m = _match(transcript)
    hdr, cand, client, app = m["header"], m["candidate"], m["client"], m["application"]
    client_name = client["name"] if client else (hdr["client"] or "Unknown firm")
    role = (app or {}).get("role_title") or hdr["role"] or "not stated"

    role_id = (app or {}).get("role_id")
    debriefs = order_debriefs(_debriefs_to_use(transcript, m), role_id, role)
    next_cands = (crm.next_candidates_for_client(client["id"], exclude_candidate_id=cand["id"] if cand else None,
                                                 role_id=role_id) if client else [])
    # Only a candidate on the SAME role gets the pack addressed to them; otherwise nobody is named.
    next_cand = next((n for n in next_cands if same_role(n, role_id, role)), None)
    pack_role = role

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_note = pool.submit(_note_and_emails, transcript, m)
        f_pack = pool.submit(_prep_pack, debriefs, next_cand, client_name, pack_role, role_id)
        note_json, meta1 = f_note.result()
        pack_json, meta2 = f_pack.result()

    emails = note_json.get("emails") if isinstance(note_json.get("emails"), dict) else {}
    ce = emails.get("candidate") if isinstance(emails.get("candidate"), dict) else {}
    cl = emails.get("client") if isinstance(emails.get("client"), dict) else {}
    pack = {
        "client": client_name,
        "role": pack_role,
        "for_candidate": {"name": next_cand.get("candidate_name") if next_cand else None,
                          "stage": (next_cand or {}).get("stage") or "",
                          "interview_at": (next_cand or {}).get("next_interview_at") or ""},
        "built_from": [{"candidate": d.get("candidate_name") or "", "round": d.get("round") or "",
                        "date": str(d.get("held_on") or "")[:10], "role": d.get("role_title") or "",
                        "same_role": same_role(d, role_id, pack_role)} for d in debriefs],
        **_clean_pack(pack_json, len(debriefs)),
    }
    return {
        "matched": {"candidate": cand["name"] if cand else None,
                    "client": client["name"] if client else None,
                    "role": (app or {}).get("role_title") or (hdr["role"] if client else None),
                    "round": hdr["round"] or note_json.get("round") or ""},
        "crm_note": _clean_note(note_json.get("crm_note")),
        "emails": {
            "candidate": {"to": (cand or {}).get("email") or "", "subject": ce.get("subject", ""),
                          "body": ce.get("body", "")},
            "client": {"to": f"Hiring team, {client_name}", "subject": cl.get("subject", ""),
                       "body": cl.get("body", "")},
        },
        "prep_pack": pack,
        "meta": {"model": meta1.get("model") or llm.model_name(), "ms": int((time.perf_counter() - t0) * 1000),
                 "calls": 2,
                 "input_tokens": meta1.get("input_tokens", 0) + meta2.get("input_tokens", 0),
                 "output_tokens": meta1.get("output_tokens", 0) + meta2.get("output_tokens", 0)},
    }
