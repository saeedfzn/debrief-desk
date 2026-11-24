"""Build data/crm.db from schema.sql, the hand-written roster below and the debrief transcripts.

Deterministic: every date is hard-coded relative to DEMO_TODAY 2026-11-25 (a Wednesday), and the
only randomness (filler activity history) uses a fixed seed. Run from the repo root:

    py -3 data/seed.py            # builds data/crm.db
    py -3 data/seed.py other.db   # builds somewhere else

All people, firms, figures, emails (example.com) and phone numbers (Ofcom drama range) are fictional.
"""
from __future__ import annotations

import random
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema.sql"
TRANSCRIPTS = HERE / "transcripts"
DEFAULT_DB = HERE / "crm.db"

HEADER_RE = re.compile(r"^Debrief call: (?P<cand>.+?) after (?P<round>.+?) at (?P<client>.+?) \((?P<role>.+)\)$")
DATE_RE = re.compile(r"^Date: (\d{4}-\d{2}-\d{2})$")

CONSULTANTS = [
    (1, "Hannah Pryce", "Quant Research"),
    (2, "Tom Okafor", "Low-Latency Engineering"),
    (3, "Priya Raman", "AI/ML"),
]

CLIENTS = [
    (1, "Fernhallow Capital", "Hedge fund", "London"),
    (2, "Brackenvane Trading", "Prop trading firm", "London"),
    (3, "Lumenfold Research", "AI lab", "London"),
]

ROLES = [
    (1, 1, "Quantitative Researcher, Systematic Equities", "Systematic Equities", "£120k-£190k base + discretionary bonus", "open"),
    (2, 1, "Quant Developer, Research Platform", "Research Technology", "£110k-£160k base + bonus", "open"),
    (3, 2, "Low-Latency C++ Developer", "Execution Technology", "£130k-£180k base + bonus", "open"),
    (4, 2, "Quantitative Trader, Options Market Making", "Index Options", "£90k-£150k base + bonus", "open"),
    (5, 2, "FPGA Engineer", "Hardware", "£120k-£170k base + bonus", "on hold"),
    (6, 3, "Research Engineer, Training Infrastructure", "Pre-training Infrastructure", "£150k-£210k base + equity", "open"),
    (7, 3, "Research Scientist, Evaluations", "Evaluations", "£140k-£200k base + equity", "open"),
    (8, 3, "Applied ML Engineer, Inference", "Inference", "£130k-£180k base + equity", "filled"),
]

# name, employer, title, location, skills, base, currency, notice_weeks, non_compete_months, consultant_id
# Grouped by where each person first came in; the last field is who owns them now, matched to the desk:
# 1 Hannah (quant research and trading), 2 Tom (low-latency and quant developers), 3 Priya (AI/ML).
CANDIDATES = [
    # ---- first group (mostly Hannah; Callum and Samir now Tom's, Hugo and Nikhil now Priya's) ----
    ("Oliver Brennan", "Brindlecombe Asset Management", "Quantitative Analyst", "London", "Python, pandas, equity momentum, factor models", 115000, "GBP", 12, 3, 1),
    ("Mei Lin Tan", "Pennick Systematic", "Quantitative Researcher", "London", "Python, statistical arbitrage, cross-sectional equities, transaction cost modelling", 135000, "GBP", 13, 6, 1),
    ("Rohan Mehta", "Sallowmere Asset Management", "Senior Quantitative Researcher", "London", "Python, event-driven equities, earnings signals, factor neutralisation", 160000, "GBP", 12, 6, 1),
    ("Sofia Marchetti", "Ketterby Bank", "Quantitative Researcher, QIS", "London", "Python, R, portfolio construction, signal combination, transaction costs", 125000, "GBP", 12, 0, 1),
    ("Aisha Karim", "Draymoor Investments", "Quantitative Analyst", "London", "Python, PhD statistics, Bayesian methods, equity signals", 110000, "GBP", 8, 3, 1),
    ("Chloe Adeyemi", "Kelmscroft Derivatives", "Junior Options Trader", "London", "Options pricing, volatility, Python, mental maths", 95000, "GBP", 12, 6, 1),
    ("Grace Holloway", "Varnley Securities", "Index Arbitrage Trader", "London", "Index arbitrage, futures, Python, probability", 88000, "GBP", 12, 6, 1),
    ("Ewan Fairley", "Kelmscroft Derivatives", "Volatility Trader", "London", "Volatility trading, options market making, risk management", 120000, "GBP", 12, 12, 1),
    ("Callum Reid", "Brindlecombe Asset Management", "Quant Developer", "London", "Python, C++, backtesting frameworks, time-series databases", 105000, "GBP", 12, 3,2),
    ("Freya Lindqvist", "Quillmont Analytics", "Data Scientist", "London", "Python, machine learning, alternative data", 85000, "GBP", 4, 0, 1),
    ("Marek Novak", "Varnley Securities", "Quantitative Strategist", "London", "C++, Python, rates, stochastic calculus", 100000, "GBP", 12, 0, 1),
    ("Hugo Laurent", "Ombrelle Quantitative", "ML Researcher", "Paris", "PyTorch, LLM evaluation, statistics", 95000, "EUR", 12, 0, 3),
    ("Nikhil Rao", "Whitfenn Analytics", "ML Research Scientist", "London", "PyTorch, benchmark design, reinforcement learning", 130000, "GBP", 8, 0, 3),
    ("Isabel Ferreira", "Ketterby Bank", "Quantitative Researcher", "London", "Python, macro signals, time series", 98000, "GBP", 12, 0, 1),
    ("Samir Haddad", "Quarnby Systems", "Senior C++ Engineer", "London", "C++20, networking, kernel bypass, Linux performance", 125000, "GBP", 8, 0, 2),
    ("Jonah Whitcombe", "Draymoor Investments", "Junior Quantitative Researcher", "London", "Python, R, econometrics", 72000, "GBP", 4, 0, 1),
    ("Leah Donovan", "Varnley Securities", "Options Trader", "London", "Options market making, Python, volatility surfaces", 92000, "GBP", 12, 6, 1),
    # ---- second group (Tom) ----
    ("Lukas Brandt", "Quarnby Systems", "C++ Developer", "London", "C++20, lock-free data structures, market data, kernel bypass", 118000, "GBP", 8, 0, 2),
    ("Ben Hartley", "Pennick Systematic", "Software Engineer, Research Tools", "London", "Python, C++, distributed backtesting", 112000, "GBP", 12, 3, 2),
    ("Dmitri Sokolov", "Teshwick Technologies", "FPGA Engineer", "London", "Verilog, FPGA, low-latency networking", 115000, "GBP", 8, 0, 2),
    ("Kwame Mensah", "Quarnby Systems", "Senior C++ Developer", "London", "C++17, order gateways, FIX", 130000, "GBP", 8, 0, 2),
    ("Elena Petrova", "Corrish Exchange Services", "Low-Latency Engineer", "Amsterdam", "C++20, matching engines, performance profiling", 125000, "EUR", 8, 0, 2),
    ("Tariq Aziz", "Teshwick Technologies", "Senior Software Engineer", "London", "C++, Linux kernel tuning, multicast", 135000, "GBP", 12, 0, 2),
    ("Ryan Gallagher", "Halbury Data", "Systems Engineer", "Dublin", "C++, Rust, networking", 95000, "EUR", 4, 0, 2),
    ("Wei Zhang", "Sallowmere Asset Management", "Quant Developer", "London", "Python, C++, research infrastructure, data pipelines", 120000, "GBP", 12, 6, 2),
    ("Harriet Cole", "Brackenvane Trading", "C++ Developer", "London", "C++, market data handlers, SIMD", 110000, "GBP", 8, 0, 2),
    ("Oskar Nilsson", "Corrish Exchange Services", "Software Engineer", "Stockholm", "Java, C++, exchange connectivity", 85000, "EUR", 12, 0, 2),
    ("Mateo Ruiz", "Teshwick Technologies", "Hardware Engineer", "London", "FPGA, SystemVerilog, timing closure", 98000, "GBP", 8, 0, 2),
    ("Laura Schmidt", "Halbury Data", "C++ Engineer", "London", "C++20, templates, benchmarking", 105000, "GBP", 8, 0, 2),
    ("Imran Shah", "Brindlecombe Asset Management", "Data Engineer", "London", "Python, Spark, research data platforms", 95000, "GBP", 8, 0, 2),
    # ---- third group (Priya; Ruth now Hannah's) ----
    ("Arjun Nair", "Whitfenn Analytics", "Machine Learning Engineer", "London", "PyTorch, FSDP, distributed training, checkpointing, data mixing", 140000, "GBP", 8, 0, 3),
    ("Zara Hussain", "Merrowind AI", "Research Scientist", "London", "LLM evaluation, red teaming, Python", 145000, "GBP", 12, 0, 3),
    ("Liam O'Connor", "Halbury Data", "ML Engineer", "London", "Inference optimisation, CUDA, quantisation", 125000, "GBP", 8, 0, 3),
    ("Chen Yu", "Whitfenn Analytics", "Senior ML Engineer", "London", "PyTorch, tensor parallelism, GPU kernels", 150000, "GBP", 12, 0, 3),
    ("Fatima Bello", "Merrowind AI", "Research Engineer", "London", "Benchmarks, Python, statistics", 115000, "GBP", 8, 0, 3),
    ("Daniel Weiss", "Quillmont Analytics", "ML Platform Engineer", "Berlin", "Kubernetes, Ray, training pipelines", 110000, "EUR", 12, 0, 3),
    ("Ana Costa", "Merrowind AI", "Applied Scientist", "London", "Evaluation design, NLP, Python", 120000, "GBP", 8, 0, 3),
    ("Kenji Watanabe", "Whitfenn Analytics", "Research Engineer", "London", "JAX, distributed training, profiling", 135000, "GBP", 8, 0, 3),
    ("Ruth Abernethy", "Ombrelle Quantitative", "ML Researcher", "London", "Python, machine learning for alpha, time series", 118000, "GBP", 12, 6, 1),
    ("Pavel Horak", "Halbury Data", "ML Engineer", "Prague", "PyTorch, data pipelines, evaluation", 80000, "EUR", 8, 0, 3),
    ("Sara Okoye", "Quillmont Analytics", "ML Engineer", "London", "Model serving, inference servers, Python", 112000, "GBP", 4, 0, 3),
    # ---- added later; appended so earlier ids, phones and filler history stay the same ----
    ("Joel Varga", "Halbury Data", "Senior C++ Engineer", "London", "C++20, FIX engines, kernel bypass", 128000, "GBP", 8, 0, 2),
    ("Nina Kowalczyk", "Quarnby Systems", "C++ Developer", "London", "C++, Python, research tooling, SIMD", 112000, "GBP", 8, 0, 2),
    ("Ines Duarte", "Merrowind AI", "Research Scientist", "London", "LLM evaluation, statistics, Python", 138000, "GBP", 12, 0, 3),
    ("Rafael Mendes", "Halbury Data", "ML Engineer", "London", "PyTorch, distributed training, data loaders", 118000, "GBP", 8, 0, 3),
]

# Greeting name where it is not simply the first word of the full name.
KNOWN_AS = {"Mei Lin Tan": "Mei Lin", "Chen Yu": "Chen Yu"}

PRONOUNS = {
    "he": {"Oliver Brennan", "Rohan Mehta", "Ewan Fairley", "Callum Reid", "Marek Novak", "Hugo Laurent", "Nikhil Rao",
           "Samir Haddad", "Jonah Whitcombe", "Lukas Brandt", "Ben Hartley", "Dmitri Sokolov", "Kwame Mensah",
           "Tariq Aziz", "Ryan Gallagher", "Wei Zhang", "Oskar Nilsson", "Mateo Ruiz", "Imran Shah", "Arjun Nair",
           "Liam O'Connor", "Chen Yu", "Daniel Weiss", "Kenji Watanabe", "Pavel Horak", "Joel Varga", "Rafael Mendes"},
    "she": {"Mei Lin Tan", "Sofia Marchetti", "Aisha Karim", "Chloe Adeyemi", "Grace Holloway", "Freya Lindqvist",
            "Isabel Ferreira", "Leah Donovan", "Elena Petrova", "Harriet Cole", "Laura Schmidt", "Zara Hussain",
            "Fatima Bello", "Ana Costa", "Ruth Abernethy", "Sara Okoye", "Nina Kowalczyk", "Ines Duarte"},
}


def _pronouns(name: str) -> str:
    return next((p for p, names in PRONOUNS.items() if name in names), "they")


def _known_as(name: str) -> str:
    return KNOWN_AS.get(name) or name.split()[0]

# candidate name, role_id, stage, stage_updated, next_interview_at, offer_sent_at, status
APPLICATIONS = [
    # first group
    ("Oliver Brennan", 1, "rejected", "2026-11-13", None, None, "closed"),
    ("Mei Lin Tan", 1, "final_round", "2026-11-13", None, None, "active"),
    ("Rohan Mehta", 1, "offer", "2026-11-19", None, "2026-11-19", "active"),
    ("Sofia Marchetti", 1, "second_round", "2026-11-24", None, None, "active"),
    ("Aisha Karim", 1, "second_round", "2026-11-20", "2026-11-27 14:00", None, "active"),
    ("Chloe Adeyemi", 4, "final_round", "2026-11-20", "2026-12-03 10:00", None, "active"),
    ("Grace Holloway", 4, "first_round", "2026-11-13", "2026-11-26 09:30", None, "active"),
    ("Ewan Fairley", 4, "second_round", "2026-11-18", "2026-12-04 09:00", None, "active"),
    ("Callum Reid", 2, "submitted", "2026-11-20", None, None, "active"),
    ("Freya Lindqvist", 1, "sourced", "2026-10-14", None, None, "active"),
    ("Marek Novak", 4, "screened", "2026-10-28", None, None, "active"),
    ("Hugo Laurent", 7, "submitted", "2026-10-30", None, None, "active"),
    ("Nikhil Rao", 7, "first_round", "2026-11-20", "2026-12-01 10:00", None, "active"),
    ("Isabel Ferreira", 1, "screened", "2026-11-24", None, None, "active"),
    ("Samir Haddad", 3, "submitted", "2026-11-17", None, None, "active"),
    ("Jonah Whitcombe", 4, "sourced", "2026-11-20", None, None, "active"),
    ("Leah Donovan", 4, "placed", "2026-09-15", None, "2026-09-08", "closed"),
    # second group
    ("Lukas Brandt", 3, "final_round", "2026-11-16", "2026-12-01 13:00", None, "active"),
    ("Ben Hartley", 2, "first_round", "2026-11-23", "2026-12-02 11:00", None, "active"),
    ("Dmitri Sokolov", 5, "submitted", "2026-10-21", None, None, "active"),
    ("Kwame Mensah", 3, "rejected", "2026-11-06", None, None, "closed"),
    ("Elena Petrova", 3, "final_round", "2026-11-19", "2026-11-30 10:00", None, "active"),
    ("Elena Petrova", 2, "withdrawn", "2026-11-02", None, None, "closed"),
    ("Tariq Aziz", 3, "offer", "2026-11-23", None, "2026-11-23", "active"),
    ("Ryan Gallagher", 3, "screened", "2026-11-18", None, None, "active"),
    ("Ryan Gallagher", 5, "sourced", "2026-11-04", None, None, "active"),
    ("Wei Zhang", 2, "second_round", "2026-11-17", None, None, "active"),
    ("Harriet Cole", 3, "placed", "2026-08-24", None, "2026-08-14", "closed"),
    ("Oskar Nilsson", 2, "withdrawn", "2026-10-19", None, None, "closed"),
    ("Mateo Ruiz", 5, "sourced", "2026-10-09", None, None, "active"),
    ("Laura Schmidt", 3, "first_round", "2026-11-23", "2026-11-27 15:00", None, "active"),
    ("Imran Shah", 2, "screened", "2026-11-12", None, None, "active"),
    # third group
    ("Arjun Nair", 6, "final_round", "2026-11-20", "2026-11-27 11:00", None, "active"),
    ("Zara Hussain", 7, "offer", "2026-11-20", None, "2026-11-20", "active"),
    ("Liam O'Connor", 8, "placed", "2026-10-05", None, "2026-09-25", "closed"),
    ("Chen Yu", 6, "second_round", "2026-11-19", "2026-12-02 15:00", None, "active"),
    ("Chen Yu", 7, "rejected", "2026-10-22", None, None, "closed"),
    ("Fatima Bello", 7, "rejected", "2026-11-11", None, None, "closed"),
    ("Daniel Weiss", 6, "submitted", "2026-11-16", None, None, "active"),
    ("Daniel Weiss", 2, "rejected", "2026-10-28", None, None, "closed"),
    ("Ana Costa", 7, "screened", "2026-11-23", None, None, "active"),
    ("Kenji Watanabe", 6, "first_round", "2026-11-18", "2026-12-03 14:00", None, "active"),
    ("Ruth Abernethy", 1, "submitted", "2026-11-18", None, None, "active"),
    ("Pavel Horak", 6, "sourced", "2026-11-02", None, None, "active"),
    ("Sara Okoye", 8, "withdrawn", "2026-09-30", None, None, "closed"),
    # added later
    ("Joel Varga", 3, "screened", "2026-11-05", None, None, "active"),
    ("Nina Kowalczyk", 2, "first_round", "2026-11-12", None, None, "active"),
    ("Ines Duarte", 7, "second_round", "2026-11-19", "2026-11-26 16:00", None, "active"),
    ("Rafael Mendes", 6, "first_round", "2026-11-12", None, None, "active"),
]

# The story beats for each candidate: (name, kind, date, with_party, summary).
# with_party says who the contact was with: 'candidate' (a call or email with the candidate themself),
# 'client' (with the hiring firm, e.g. a CV submission or a chase for feedback) or 'internal' (a note).
# Only 'candidate' rows count as contact for the call list. The latest 'candidate' row is the last contact.
# Filler history is generated strictly BEFORE each candidate's earliest key activity.
KEY_ACTIVITIES = [
    # Oliver: rejected after second round
    ("Oliver Brennan", "call", "2026-11-03", "candidate", "Debrief after Fernhallow first round with Graham Lowe. Felt unsure, brainteasers mostly fine. 12 weeks notice, 3 months non-compete."),
    ("Oliver Brennan", "email", "2026-11-05", "candidate", "Fernhallow feedback: through to second round. Sent him the technical round format."),
    ("Oliver Brennan", "call", "2026-11-13", "candidate", "Told him Fernhallow are not progressing after the second round: cost modelling too light. Taking it well, open to other roles."),
    # Mei Lin: final round, then silence (situation: final-round candidate not contacted for 8+ days)
    ("Mei Lin Tan", "call", "2026-11-10", "candidate", "Debrief after Fernhallow second round. Strong on survivorship and multiple testing, hand-wavy on market impact. Wants £155k base."),
    ("Mei Lin Tan", "email", "2026-11-13", "candidate", "Told Mei Lin she is through to the Fernhallow final round. Asked for her availability for the research presentation."),
    # Rohan: offer out, nothing since (situation: offer sent 3+ working days ago, no activity since)
    ("Rohan Mehta", "call", "2026-11-17", "candidate", "Debrief after Fernhallow final round. Went well with Marcus Elling. Garden leave not bought out. Has a competing prop offer this week."),
    ("Rohan Mehta", "call", "2026-11-18", "client", "Ingrid Saarinen at Fernhallow: offer coming, references requested. Asked her about a guaranteed first-year bonus."),
    # Sofia: the fresh debrief (her second round on 24 Nov is not logged yet)
    ("Sofia Marchetti", "call", "2026-11-12", "candidate", "Debrief after Fernhallow first round with Graham Lowe. Comfortable with the probability questions."),
    ("Sofia Marchetti", "email", "2026-11-13", "candidate", "Fernhallow feedback: through to second round, booked for Tue 24 Nov."),
    ("Sofia Marchetti", "call", "2026-11-20", "candidate", "Prep call for Fernhallow second round: survivorship traps in the data, costs, Graham's poker face."),
    # Aisha: the next candidate at Fernhallow (healthy)
    ("Aisha Karim", "call", "2026-11-19", "candidate", "Debrief after Fernhallow first round. Good on the probability questions, CV deep dive on her Bayesian work."),
    ("Aisha Karim", "email", "2026-11-20", "candidate", "Fernhallow feedback: through to second round, booked Fri 27 Nov 14:00 at their office."),
    ("Aisha Karim", "call", "2026-11-23", "candidate", "Prep call: walked through the Fernhallow second round format. Second prep call booked for Thu 26 Nov."),
    # Chloe: final round booked (healthy)
    ("Chloe Adeyemi", "call", "2026-11-19", "candidate", "Debrief after Brackenvane market-making game. Widened well under pressure, one position slip. Worried about maths speed."),
    ("Chloe Adeyemi", "email", "2026-11-20", "candidate", "Brackenvane feedback positive: final round with the head of the index options desk, Thu 3 Dec 10:00."),
    # Grace: interview tomorrow, nothing logged since the booking (situation)
    ("Grace Holloway", "call", "2026-11-06", "candidate", "Screening call. Index arb background, interested in options market making at Brackenvane."),
    ("Grace Holloway", "email", "2026-11-13", "candidate", "Emailed Grace to confirm her Brackenvane first round: Thu 26 Nov 09:30."),
    # Ewan: long non-compete (situation)
    ("Ewan Fairley", "call", "2026-11-12", "candidate", "Debrief after Brackenvane first round. Strong. 12-month non-compete at Kelmscroft, enforced in full last time someone left."),
    ("Ewan Fairley", "call", "2026-11-20", "candidate", "Told Ewan his Brackenvane second round is booked for 4 Dec. Brackenvane checking whether they would cover a 12-month non-compete."),
    # Callum: healthy, just submitted
    ("Callum Reid", "call", "2026-11-18", "candidate", "Screening call for the Fernhallow quant developer role. Keen, good C++ and Python."),
    ("Callum Reid", "email", "2026-11-20", "client", "Submitted CV to Fernhallow for the Quant Developer, Research Platform role."),
    # stale early-stage ones (situation)
    ("Freya Lindqvist", "note", "2026-10-14", "internal", "Sourced via referral. Interested in Fernhallow, not yet screened."),
    ("Marek Novak", "call", "2026-10-28", "candidate", "Screened for the Brackenvane options role. Strong maths, wants to think about leaving rates."),
    ("Hugo Laurent", "email", "2026-10-30", "client", "Submitted to Lumenfold for Research Scientist, Evaluations."),
    ("Hugo Laurent", "email", "2026-11-03", "client", "Chased Lumenfold for CV feedback. Nothing yet."),
    # healthy ones
    ("Nikhil Rao", "email", "2026-11-20", "candidate", "Told Nikhil that Lumenfold want a first round: Tue 1 Dec 10:00, evaluation design."),
    ("Nikhil Rao", "call", "2026-11-24", "candidate", "Prep call for Lumenfold first round on 1 Dec. Talked through benchmark contamination questions."),
    ("Isabel Ferreira", "call", "2026-11-24", "candidate", "Screening call. Keen on Fernhallow systematic equities, updating her CV this week."),
    ("Samir Haddad", "call", "2026-11-16", "candidate", "Screening call. Kernel bypass and order gateways, open to prop firms."),
    ("Samir Haddad", "email", "2026-11-17", "client", "CV submitted to Brackenvane execution technology team."),
    # Jonah: sourced, never contacted (no activities on purpose)
    # Leah: placed earlier in the year
    ("Leah Donovan", "email", "2026-09-08", "candidate", "Sent Leah the Brackenvane offer: £105k base plus desk bonus."),
    ("Leah Donovan", "call", "2026-09-15", "candidate", "Leah accepted Brackenvane. Start date after 6 months garden leave."),
    # second group
    ("Lukas Brandt", "call", "2026-11-12", "candidate", "Debrief after Brackenvane C++ coding round. Ring buffer strong, order book unfinished. Worried about hours."),
    ("Lukas Brandt", "email", "2026-11-16", "candidate", "Told Lukas he is through to the Brackenvane final round, Tue 1 Dec 13:00: system design, then the head of the team."),
    ("Lukas Brandt", "call", "2026-11-24", "candidate", "Prep call for Brackenvane system design: market data handler end to end."),
    ("Ben Hartley", "email", "2026-11-23", "candidate", "Emailed Ben his Fernhallow first round time: Wed 2 Dec 11:00."),
    ("Dmitri Sokolov", "email", "2026-10-21", "client", "Submitted to Brackenvane FPGA role. Role since put on hold."),
    ("Kwame Mensah", "call", "2026-11-06", "candidate", "Brackenvane declined after first round. Fed back to Kwame."),
    ("Elena Petrova", "email", "2026-11-02", "candidate", "Elena emailed to withdraw from the Fernhallow developer process to focus on Brackenvane."),
    ("Elena Petrova", "call", "2026-11-23", "candidate", "Prep call for Brackenvane final round on Mon 30 Nov. Relocation from Amsterdam discussed."),
    ("Tariq Aziz", "email", "2026-11-23", "candidate", "Sent Tariq the Brackenvane offer: £165k base plus bonus."),
    ("Tariq Aziz", "call", "2026-11-24", "candidate", "Tariq reviewing the Brackenvane offer, wants to talk about the bonus structure on Friday."),
    ("Ryan Gallagher", "call", "2026-11-18", "candidate", "Screening call. Open to relocating from Dublin."),
    ("Wei Zhang", "call", "2026-11-17", "candidate", "Debrief after Fernhallow developer second round. Waiting on feedback."),
    ("Wei Zhang", "email", "2026-11-23", "client", "Chased Fernhallow for Wei's second round feedback."),
    ("Harriet Cole", "call", "2026-08-24", "candidate", "Harriet accepted Brackenvane offer."),
    ("Oskar Nilsson", "email", "2026-10-19", "candidate", "Oskar withdrew: staying in Stockholm."),
    ("Mateo Ruiz", "note", "2026-10-09", "internal", "Sourced for the Brackenvane FPGA role."),
    ("Laura Schmidt", "email", "2026-11-20", "client", "CV submitted to Brackenvane for the low-latency role."),
    ("Laura Schmidt", "email", "2026-11-23", "candidate", "Emailed Laura her Brackenvane first round: Fri 27 Nov 15:00, C++ coding with the execution tech team."),
    ("Laura Schmidt", "call", "2026-11-24", "candidate", "Prep call for Brackenvane first round: lock-free queues, cache behaviour, moving off the naive version."),
    ("Imran Shah", "call", "2026-11-12", "candidate", "Screening call for the Fernhallow research platform role."),
    # third group
    ("Arjun Nair", "call", "2026-11-18", "candidate", "Debrief after Lumenfold second round. Checkpointing design and loss-spike debugging. Worried about equity versus base."),
    ("Arjun Nair", "email", "2026-11-20", "candidate", "Told Arjun his Lumenfold final round is Fri 27 Nov 11:00: values chat and head of infra."),
    ("Zara Hussain", "email", "2026-11-20", "candidate", "Sent Zara the Lumenfold offer: £185k base plus options."),
    ("Zara Hussain", "call", "2026-11-24", "candidate", "Zara has questions on the option vesting schedule. Asked Lumenfold for the valuation detail."),
    ("Liam O'Connor", "call", "2026-10-05", "candidate", "Liam accepted Lumenfold inference role."),
    ("Chen Yu", "email", "2026-11-19", "candidate", "Emailed Chen Yu his Lumenfold second round time: Wed 2 Dec 15:00."),
    ("Fatima Bello", "call", "2026-11-11", "candidate", "Lumenfold declined after first round. Fed back."),
    ("Daniel Weiss", "email", "2026-11-16", "client", "CV submitted to Lumenfold training infrastructure role."),
    ("Ana Costa", "call", "2026-11-23", "candidate", "Screening call for Lumenfold evaluations role."),
    ("Kenji Watanabe", "call", "2026-11-20", "candidate", "Lumenfold first round booked for 3 Dec. Talked about JAX versus PyTorch at Lumenfold."),
    ("Ruth Abernethy", "email", "2026-11-18", "client", "CV submitted to Fernhallow systematic equities."),
    ("Pavel Horak", "note", "2026-11-02", "internal", "Sourced. Prague based, would relocate."),
    ("Sara Okoye", "email", "2026-09-30", "candidate", "Sara withdrew from Lumenfold process: accepted a counter-offer."),
    # added later
    ("Joel Varga", "call", "2026-11-05", "candidate", "Screened for the Brackenvane low-latency role. Wants to see the team's stack before going further."),
    ("Nina Kowalczyk", "email", "2026-11-09", "client", "CV submitted to Fernhallow for the Quant Developer, Research Platform role."),
    ("Nina Kowalczyk", "call", "2026-11-13", "candidate", "Debrief after Fernhallow first round. Felt it went well. Waiting on feedback."),
    ("Ines Duarte", "email", "2026-11-19", "candidate", "Emailed Ines her Lumenfold second round: Thu 26 Nov 16:00, evaluation design case."),
    ("Ines Duarte", "call", "2026-11-24", "candidate", "Prep call for Lumenfold second round: contamination checks and how to design an eval."),
    ("Rafael Mendes", "email", "2026-11-06", "client", "CV submitted to Lumenfold training infrastructure role."),
    ("Rafael Mendes", "call", "2026-11-13", "candidate", "Debrief after Lumenfold first round. Coding went well, unsure on the systems questions. Waiting on feedback."),
]

# Generic history. Deliberately never mentions "prep", offers or interviews, so it cannot
# blur the situations above.
FILLER = {
    "call": [
        "Catch-up call. Still keen, nothing new on their side.",
        "Call about the market and what kind of team they want next.",
        "Intro call. Talked through background and what would make them move.",
        "Call: walked through current comp and bonus timing.",
        "Quick call about notice period and contract terms.",
    ],
    "email": [
        "Sent role details and the team overview.",
        "Emailed to confirm interest and ask for an updated CV.",
        "Sent a summary of our last conversation.",
        "Shared two roles that might fit.",
    ],
    "note": [
        "Note: referral came via a former placement.",
        "Note: prefers a research-heavy role over pure engineering.",
        "Note: bonus paid in March, unlikely to move before then without a buyout.",
        "Note: open to relocation within Europe.",
    ],
}


def parse_header(text: str) -> dict:
    lines = text.splitlines()
    m = HEADER_RE.match(lines[0].strip())
    d = DATE_RE.match(lines[1].strip()) if len(lines) > 1 else None
    if not m or not d:
        raise ValueError(f"bad transcript header: {lines[:2]!r}")
    return {**m.groupdict(), "title": lines[0].strip(), "date": d.group(1)}


def _phone(i: int) -> str:
    return f"07700 900{100 + i:03d}"


def _email(name: str) -> str:
    slug = re.sub(r"[^a-z.]", "", name.lower().replace(" ", "."))
    return f"{slug}@example.com"


def build(db_path: Path | str = DEFAULT_DB) -> Path:
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.executemany("INSERT INTO consultants VALUES (?,?,?)", CONSULTANTS)
        conn.executemany("INSERT INTO clients VALUES (?,?,?,?)", CLIENTS)
        conn.executemany("INSERT INTO roles VALUES (?,?,?,?,?,?)", ROLES)

        cand_id: dict[str, int] = {}
        cand_owner: dict[str, int] = {}
        for i, c in enumerate(CANDIDATES, start=1):
            cand_id[c[0]] = i
            cand_owner[c[0]] = c[9]
            conn.execute(
                "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (i, *c, _email(c[0]), _phone(i), _known_as(c[0]), _pronouns(c[0])),
            )

        app_ids: dict[tuple[str, int], int] = {}
        for i, (name, role_id, stage, upd, nxt, offer, status) in enumerate(APPLICATIONS, start=1):
            app_ids[(name, role_id)] = i
            conn.execute(
                "INSERT INTO applications VALUES (?,?,?,?,?,?,?,?)",
                (i, cand_id[name], role_id, stage, upd, nxt, offer, status),
            )

        # Activities: filler history (fixed seed) strictly before each candidate's earliest key beat,
        # then the key beats. Inserted in date order so ids rise with time.
        rng = random.Random(20261125)
        earliest: dict[str, str] = {}
        for name, _kind, at, _party, _s in KEY_ACTIVITIES:
            earliest[name] = min(at, earliest.get(name, at))
        stage_of = {}
        for a in APPLICATIONS:
            if a[6] == "active":
                stage_of.setdefault(a[0], set()).add(a[2])
        rows = []
        for c in CANDIDATES:
            name = c[0]
            if name not in earliest:
                continue  # never contacted (Jonah Whitcombe)
            first = date.fromisoformat(earliest[name])
            for k in range(rng.randint(1, 3)):
                at = first - timedelta(days=rng.randint(3 + 9 * k, 10 + 9 * k))
                while at.weekday() >= 5:  # keep history on working days
                    at -= timedelta(days=1)
                kind = rng.choice(["call", "call", "email", "note"])
                text = rng.choice(FILLER[kind])
                if stage_of.get(name) == {"sourced"}:
                    continue  # sourced and not yet screened: no earlier contact may exist (draws kept, so others are unchanged)
                rows.append((cand_id[name], cand_owner[name], kind, at.isoformat(),
                             "internal" if kind == "note" else "candidate", text))
        for name, kind, at, party, summary in KEY_ACTIVITIES:
            rows.append((cand_id[name], cand_owner[name], kind, at, party, summary))
        rows.sort(key=lambda r: (r[3], r[0]))
        conn.executemany(
            "INSERT INTO activities (candidate_id, consultant_id, kind, at, with_party, summary) VALUES (?,?,?,?,?,?)", rows
        )

        # Debriefs from the transcript files, except fresh_* (that one is for the live paste).
        role_by_title = {(r[1], r[2]): r[0] for r in ROLES}
        client_by_name = {c[1]: c[0] for c in CLIENTS}
        for path in sorted(TRANSCRIPTS.glob("*.txt")):
            if path.stem.startswith("fresh_"):
                continue
            text = path.read_text(encoding="utf-8")
            h = parse_header(text)
            client_id = client_by_name[h["client"]]
            role_id = role_by_title[(client_id, h["role"])]
            conn.execute(
                "INSERT INTO debriefs (application_id, candidate_id, client_id, round, held_on, title, transcript)"
                " VALUES (?,?,?,?,?,?,?)",
                (app_ids[(h["cand"], role_id)], cand_id[h["cand"]], client_id, h["round"], h["date"], h["title"], text),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    path = build(target)
    conn = sqlite3.connect(path)
    tables = ["consultants", "clients", "roles", "candidates", "applications", "activities", "debriefs"]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    print(f"Built {path}")
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
