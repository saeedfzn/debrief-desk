# Debrief Desk

**A desk tool for recruitment consultants: paste a debrief call, get the admin done.**

Work sample by Faizaan Saeed. All people, firms and figures are fictional.

Live page with saved results: [saeedfzn.github.io/debrief-desk](https://saeedfzn.github.io/debrief-desk/)

## What it does

**1. Debrief call to everything that follows.** A candidate comes out of an interview and rings their consultant. Paste the transcript of that call and press Run. About 20 seconds later you have:

- a CRM note: how it went, what was asked in each round, compensation, notice and non-compete, risks, next actions
- a draft email to the candidate and a draft email to the client
- an interview prep pack for the **next** candidate booked on the same role, built from every debrief on file for that role plus this one (debriefs for other roles at the firm add firm-wide points only)

The pack is the point. One call tells you what one person was asked. Four calls tell you how the firm interviews: which rounds, who runs them, which question themes come up every time, and what tripped people up.

**2. Daily call list.** For one consultant: today's calls in order, each with a reason and an opening line. The order comes from fixed rules in code, so it is the same every time and anyone can see why a name is at the top. The model only writes the reason and the opener. Click the points on any card to see the breakdown.

| Signal | Points |
|---|---|
| Offer out, no contact since it was sent | 40, plus 2 per working day, up to 50 |
| Offer out, in touch since it was sent | 30 |
| Interview by the end of the next two working days, no prep call logged | 35 |
| Interview by the end of the next two working days, prep call logged | 15 |
| Final round, no contact for 8 days or more | 30 |
| Final round, in touch | 20 |
| Early stage (sourced, screened, submitted), no contact for 14 days or more | 12 |
| Days since last contact beyond what the stage allows, unless one of the "no contact" signals above already applies | 1 per day over, up to 20 |
| Non-compete of 6 months or more, first round to offer | 10 (15 if 12 months or more) |

Applications on roles that are on hold or filled are left off the list. An early-stage lead can score at most 12, so an open offer, a final round or an interview in the window always comes above it.

**3. Ask the pipeline.** Type a question in plain English ("which offers have been out for more than three working days?") and get a table and a one-line answer. The SQL that ran is shown underneath. The connection is read-only and accepts a single SELECT statement, so a question can never change the data.

Nothing is sent and nothing is written to the CRM: every connection to it is read-only. Every email is a draft for the consultant.

## Run it

Needs Python 3.11 or later and an Anthropic API key in the environment. On Windows use `py -3`; elsewhere use `python`.

```
pip install -r requirements.txt
python data/seed.py                  # or: py -3 data/seed.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8770
                                     # or: py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8770
```

Open http://127.0.0.1:8770/ and paste a debrief call transcript. Without the server, `index.html` shows the saved results in `saved/`, which came from real runs of the same code (`python scripts/make_saved.py`).

Tests: `python -m unittest discover -s tests -p "test_*.py"` (or `py -3 -m unittest ...`)

## How it is put together

| File | Job |
|---|---|
| `app/crm.py` | The CRM layer. Today it reads a SQLite file with sample data. This is the one file to point at a real CRM's API. |
| `app/debrief.py` | Feature 1. Matches the candidate and firm, pulls earlier debriefs for that firm, makes two model calls. |
| `app/calllist.py` | Feature 2. `score_row` is plain Python; one model call writes the wording, with a template fallback. |
| `app/ask.py` | Feature 3. Question to SQL, run read-only, answer from the rows. |
| `app/prompts.py` | Every prompt in one place. They forbid invented facts and keep a candidate's other processes out of the client email. |
| `app/llm.py` | The model call (Claude, via the Anthropic SDK). |
| `data/` | Schema, seed script and seven debrief transcripts. |
| `index.html` | The whole page, one file, no build step. |

Built with Claude Code.
