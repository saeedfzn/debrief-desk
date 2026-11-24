# Debrief Desk

**A desk tool for recruitment consultants: paste a debrief call, get the admin done.**

Work sample by Faizaan Saeed. All people, firms and figures are fictional.

Live page with saved results: [saeedfzn.github.io/debrief-desk](https://saeedfzn.github.io/debrief-desk/)

## What it does

**1. Debrief call to everything that follows.** A candidate comes out of an interview and rings their consultant. Paste the transcript of that call and press Run. Under a minute later you have:

- a CRM note: how it went, what was asked in each round, compensation, notice and non-compete, risks, next actions
- a draft email to the candidate and a draft email to the client
- an interview prep pack for the **next** candidate booked on the same role, built from every debrief on file for that role plus this one (debriefs for other roles at the firm add firm-wide points only)

The pack is the point. One call tells you what one person was asked. Four calls tell you how the firm interviews: which rounds, who runs them, which question themes come up every time, and what tripped people up.

**2. Daily call list.** For one consultant: today's calls in order, each with a reason and an opening line. The order comes from fixed rules in code, so it is the same every time and anyone can see why a name is at the top. The model only writes the reason and the opener. Click the points on any card to see the breakdown.

| Signal | Points |
|---|---|
| Offer out, no contact since it was sent | 40, plus 2 per working day, up to 50 |
| Offer out, in touch since it was sent | 30 |
| At offer stage, no offer date logged | 30 |
| Interview by the end of the next two working days, no call with the candidate in the last 3 days | 35 |
| Interview by the end of the next two working days, a call with the candidate in the last 3 days | 15 |
| Final round, no contact for 8 days or more | 30 |
| Final round, in touch | 20 |
| Early stage (sourced, screened, submitted), no contact for 14 days or more | 12 |
| Days since last contact beyond what the stage allows, unless one of the "no contact" signals above already applies | 1 per day over, up to 20 |
| Non-compete of 6 months or more, first round to offer | 10 (15 if 12 months or more) |

"Contact" means a call or email with the candidate. A CV sent to the client, a chase for feedback or an internal note is logged in the CRM but does not count, so the card's "Last contact" is the last time someone spoke to or emailed the candidate.

Applications on roles that are on hold or filled are left off the list. An early-stage lead with no interview booked in the window scores at most 12, so an open offer or a final round always comes above it.

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

Open http://127.0.0.1:8770/ and paste a debrief call transcript. Without the API server, the page shows the saved results in `saved/`, which came from real runs of the same code (`python scripts/make_saved.py`). The page must be served over HTTP for that, because browsers block it from reading files when opened straight from disk: use the GitHub Pages link above, or run `python -m http.server` in the project folder and open the address it prints.

Tests: `python -m unittest discover -s tests -p "test_*.py"` (or `py -3 -m unittest ...`)

## How it is put together

| File | Job |
|---|---|
| `app/crm.py` | The CRM layer. Today it reads a SQLite file with sample data, and pointing it at a real CRM's API means changing this file. Ask the pipeline runs SQL against this schema, so with a real CRM it would query a read-only copy of the pipeline tables. |
| `app/debrief.py` | Feature 1. Matches the candidate and firm, pulls earlier debriefs for that firm, makes two model calls. |
| `app/calllist.py` | Feature 2. `score_row` is plain Python; one model call writes the wording, with a template fallback. |
| `app/ask.py` | Feature 3. Question to SQL, run read-only, answer from the rows. |
| `app/prompts.py` | Every prompt in one place. They forbid invented facts and keep a candidate's other processes out of the client email. |
| `app/llm.py` | The model call (Claude, via the Anthropic SDK). Debriefs use Claude Opus, because the note and the pack have to stay faithful to long transcripts; the call list and questions use Claude Sonnet, which is quicker. Both are set in `app/config.py`. |
| `data/` | Schema, seed script and seven debrief transcripts. |
| `index.html` | The whole page, one file, no build step. |

Built with Claude Code.
