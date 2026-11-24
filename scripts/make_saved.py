"""Write the saved/*.json files for the static page from REAL runs of the app's own functions.

Usage (from the project root):
  py -3 scripts/make_saved.py                 # everything
  py -3 scripts/make_saved.py --only index    # just saved/index.json and the transcript files
  py -3 scripts/make_saved.py --only debrief:fresh_a4_xxx
  py -3 scripts/make_saved.py --only calllist:2
  py -3 scripts/make_saved.py --only ask:q3
  py -3 scripts/make_saved.py --out some/other/folder
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ask as ask_mod  # noqa: E402
from app import calllist, config, crm, debrief, llm  # noqa: E402

QUESTIONS = [
    {"id": "q1", "question": "Which final-round candidates have not had a call from us in the last 7 days?"},
    {"id": "q2", "question": "Which offers have been out for more than three working days, and when did we last speak to each candidate?"},
    {"id": "q3", "question": "Which candidates in an active process have a non-compete of six months or more, grouped by client?"},
    {"id": "q4", "question": "How many active applications are there at each stage?"},
    {"id": "q5", "question": "Who has an interview in the next three days, and has each of them had a call since their last stage change?"},
    {"id": "q6", "question": "For each consultant, how many active candidates have not been contacted for more than two weeks?"},
]


FAILURES: list[str] = []


def write(out: Path, name: str, data) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    u = llm.USAGE
    print(f"  wrote {name}   [model calls so far: {u['calls']}, tokens in {u['input_tokens']:,} / out {u['output_tokens']:,}]",
          flush=True)


def do_index(out: Path) -> None:
    ts = crm.list_sample_transcripts()
    write(out, "index.json", {
        "generated": date.today().isoformat(), "model": llm.model_name(), "today": config.DEMO_TODAY,
        "transcripts": [{k: t.get(k) for k in ("id", "title", "date", "in_db")} for t in ts],
        "consultants": [{k: c.get(k) for k in ("id", "name", "desk")} for c in crm.list_consultants()],
        "questions": QUESTIONS,
    })
    for t in ts:
        write(out, f"transcript_{t['id']}.json", {k: t.get(k) for k in ("id", "title", "date", "in_db", "text")})


def do_debrief(out: Path, tid: str) -> None:
    t = next((t for t in crm.list_sample_transcripts() if t["id"] == tid), None)
    if not t:
        raise SystemExit(f"No transcript called {tid}")
    write(out, f"debrief_{tid}.json", debrief.run_debrief(t["text"]))


def do_calllist(out: Path, cid: int) -> None:
    res = calllist.build_call_list(cid)
    if res["meta"].get("wording") != "model":
        print(f"  WARNING: call list {cid} fell back to template wording")
    write(out, f"calllist_{cid}.json", res)


def do_ask(out: Path, qid: str) -> None:
    q = next((q for q in QUESTIONS if q["id"] == qid), None)
    if not q:
        raise SystemExit(f"No question called {qid}")
    try:
        res = ask_mod.ask(q["question"])
    except ask_mod.AskError as e:
        print(f"  FAILED: {qid}: {e.message}\n  SQL: {e.sql}\n  (no file written; reword it and rerun --only ask:{qid})")
        FAILURES.append(f"ask:{qid}")
        return
    write(out, f"ask_{qid}.json", res)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="index | debrief:<id> | calllist:<consultant_id> | ask:<qid> | debrief | calllist | ask")
    ap.add_argument("--out", default=str(ROOT / "saved"), help="output folder (default: saved/)")
    args = ap.parse_args()
    out = Path(args.out)
    if not llm.has_key() and args.only != "index":
        raise SystemExit("ANTHROPIC_API_KEY is not set.")

    only = args.only or ""
    kind, _, item = only.partition(":")
    t0 = time.perf_counter()
    if not only or kind == "index":
        do_index(out)
    if not only or kind == "debrief":
        ids = [item] if item else [t["id"] for t in crm.list_sample_transcripts()]
        for tid in ids:
            print(f"debrief {tid} ...", flush=True)
            do_debrief(out, tid)
    if not only or kind == "calllist":
        ids = [int(item)] if item else [c["id"] for c in crm.list_consultants()]
        for cid in ids:
            print(f"call list {cid} ...", flush=True)
            do_calllist(out, cid)
    if not only or kind == "ask":
        ids = [item] if item else [q["id"] for q in QUESTIONS]
        for qid in ids:
            print(f"ask {qid} ...", flush=True)
            do_ask(out, qid)
    if kind and kind not in ("index", "debrief", "calllist", "ask"):
        raise SystemExit(f"Unknown --only value: {only}")
    u = llm.USAGE
    print(f"Done in {time.perf_counter() - t0:.0f}s. Model calls: {u['calls']}, "
          f"tokens in {u['input_tokens']:,}, out {u['output_tokens']:,}.")
    if FAILURES:
        raise SystemExit("Failed: " + ", ".join(FAILURES))


if __name__ == "__main__":
    main()
