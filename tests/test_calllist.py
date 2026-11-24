"""Call list scoring and wording. No network: llm.call_json and crm are patched."""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import calllist, llm  # noqa: E402

TODAY = date(2026, 11, 25)  # Wednesday


def row(**kw):
    base = {"application_id": 1, "candidate_id": 1, "candidate_name": "Test Person", "client_name": "Client A",
            "role_title": "Quant Researcher", "stage": "second_round", "stage_updated": "2026-11-20",
            "next_interview_at": None, "offer_sent_at": None, "notice_weeks": 4, "non_compete_months": 0,
            "phone": "07700 900001", "last_contact_at": "2026-11-24", "last_contact_kind": "call",
            "last_contact_summary": "Catch-up", "role_status": "open", "known_as": None, "pronouns": "they"}
    base.update(kw)
    return base


def labels(factors):
    return " | ".join(f["label"] for f in factors)


class ScoreRowTests(unittest.TestCase):
    def test_score_is_sum_of_factors(self):
        for r in [row(), row(stage="offer", offer_sent_at="2026-11-18", last_contact_at="2026-11-18"),
                  row(stage="final_round", last_contact_at="2026-11-10", non_compete_months=12)]:
            score, factors = calllist.score_row(r, TODAY)
            self.assertEqual(score, sum(f["points"] for f in factors))

    def test_offer_out_no_contact_is_highest(self):
        offer = row(stage="offer", offer_sent_at="2026-11-18", last_contact_at="2026-11-18",
                    last_contact_kind="email")
        s_offer, f_offer = calllist.score_row(offer, TODAY)
        self.assertIn("Offer out 5 working days, no contact since", labels(f_offer))
        self.assertEqual(f_offer[0]["points"], 50)
        others = [row(stage="final_round", last_contact_at="2026-11-15"),
                  row(stage="first_round", next_interview_at="2026-11-26 10:00", last_contact_at="2026-11-19",
                      last_contact_kind="email"),
                  row(stage="sourced", last_contact_at=None)]
        for o in others:
            self.assertGreater(s_offer, calllist.score_row(o, TODAY)[0])

    def test_offer_with_contact_since(self):
        _, f = calllist.score_row(row(stage="offer", offer_sent_at="2026-11-18", last_contact_at="2026-11-20"), TODAY)
        self.assertIn("Offer out, in touch since it was sent", labels(f))

    def test_interview_tomorrow_without_prep(self):
        _, f = calllist.score_row(row(stage="first_round", next_interview_at="2026-11-26 10:00",
                                      last_contact_at="2026-11-19", last_contact_kind="email"), TODAY)
        self.assertIn("Interview tomorrow, no call in the last 3 days", labels(f))

    def test_interview_tomorrow_with_prep_call(self):
        _, f = calllist.score_row(row(stage="first_round", next_interview_at="2026-11-26 10:00",
                                      last_contact_at="2026-11-24", last_contact_kind="call"), TODAY)
        self.assertIn("call in the last 3 days", labels(f))
        self.assertNotIn("no call", labels(f))

    def test_interview_next_week_not_flagged(self):
        _, f = calllist.score_row(row(next_interview_at="2026-12-02 10:00"), TODAY)
        self.assertNotIn("Interview", labels(f))

    def test_final_round_quiet(self):
        score, f = calllist.score_row(row(stage="final_round", last_contact_at="2026-11-16"), TODAY)
        self.assertIn("Final round, no contact for 9 days", labels(f))
        self.assertGreaterEqual(score, 30)

    def test_long_non_compete(self):
        _, f = calllist.score_row(row(non_compete_months=12), TODAY)
        self.assertIn("12-month non-compete", labels(f))
        _, f = calllist.score_row(row(non_compete_months=3), TODAY)
        self.assertNotIn("non-compete", labels(f))

    def test_early_stage_stale(self):
        _, f = calllist.score_row(row(stage="screened", last_contact_at="2026-11-01"), TODAY)
        self.assertIn("Early stage, stale for 24 days", labels(f))

    def test_healthy_row_scores_zero(self):
        self.assertEqual(calllist.score_row(row(), TODAY), (0, []))

    def test_accepts_iso_string_and_is_deterministic(self):
        r = row(stage="final_round", last_contact_at="2026-11-10", non_compete_months=9)
        self.assertEqual(calllist.score_row(r, "2026-11-25"), calllist.score_row(r, TODAY))

    def test_interview_window_is_end_of_next_two_working_days(self):
        # Wed 25 Nov: Thu 26 and Fri 27 are in the window at any time; Mon 30 is not.
        for when in ("2026-11-25 14:00", "2026-11-26 09:30", "2026-11-27 08:00", "2026-11-27 18:30"):
            _, f = calllist.score_row(row(stage="first_round", next_interview_at=when, last_contact_kind="email",
                                          last_contact_at="2026-11-19"), TODAY)
            self.assertIn("no call in the last 3 days", labels(f), when)
        for when in ("2026-11-28 10:00", "2026-11-30 09:00", "2026-11-25 07:00"):
            _, f = calllist.score_row(row(next_interview_at=when), TODAY)
            self.assertNotIn("Interview", labels(f), when)
        # Thu 26 Nov: window runs to Mon 30 Nov over the weekend
        self.assertEqual(calllist.interview_window_end(date(2026, 11, 26)), date(2026, 11, 30))
        self.assertEqual(calllist.interview_window_end(TODAY), date(2026, 11, 27))

    def test_no_double_counting_of_silence(self):
        _, f = calllist.score_row(row(stage="sourced", last_contact_at="2026-10-01"), TODAY)
        self.assertEqual([x["points"] for x in f], [12])
        _, f = calllist.score_row(row(stage="final_round", last_contact_at="2026-11-10"), TODAY)
        self.assertNotIn("since last contact", labels(f))
        _, f = calllist.score_row(row(stage="offer", offer_sent_at="2026-11-18", last_contact_at="2026-11-17"), TODAY)
        self.assertNotIn("since last contact", labels(f))

    def test_live_work_always_beats_early_stage(self):
        """Every early-stage row, however stale and whatever its non-compete, is below every open offer,
        every final round and every interview in the window."""
        early_max = 0
        for stage in ("sourced", "screened", "submitted"):
            for last in [None] + [f"2026-{m:02d}-{d:02d}" for m in (9, 10, 11) for d in (1, 8, 15, 22)] + ["2026-11-25"]:
                for nc in (0, 3, 6, 12, 24):
                    s, f = calllist.score_row(row(stage=stage, last_contact_at=last, non_compete_months=nc), TODAY)
                    self.assertEqual(s, sum(x["points"] for x in f))
                    early_max = max(early_max, s)
        self.assertLessEqual(early_max, 12)
        live = [row(stage="offer", offer_sent_at="2026-11-18", last_contact_at="2026-11-24"),
                row(stage="offer", offer_sent_at=None),
                row(stage="final_round", last_contact_at="2026-11-24"),
                row(stage="first_round", next_interview_at="2026-11-27 16:00", last_contact_at="2026-11-24"),
                row(stage="second_round", next_interview_at="2026-11-26 09:00", last_contact_at="2026-11-23")]
        for r in live:
            self.assertGreater(calllist.score_row(r, TODAY)[0], early_max, r)

    def test_early_stage_without_an_interview_never_above_12(self):
        for stage in ("sourced", "screened", "submitted"):
            for offer in (None, "2026-11-01", "2026-11-24"):
                for last in (None, "2026-09-01", "2026-11-12", "2026-11-24"):
                    s, _ = calllist.score_row(row(stage=stage, offer_sent_at=offer, last_contact_at=last,
                                                  non_compete_months=12), TODAY)
                    self.assertLessEqual(s, 12, (stage, offer, last))

    def test_call_in_last_3_days_uses_last_call_not_last_contact(self):
        # a prep call on the 24th followed by an email on the 25th still counts
        _, f = calllist.score_row(row(stage="first_round", next_interview_at="2026-11-26 10:00",
                                      last_contact_at="2026-11-25", last_contact_kind="email",
                                      last_call_at="2026-11-24"), TODAY)
        self.assertIn("call in the last 3 days", labels(f))
        self.assertNotIn("no call", labels(f))
        # an email two days ago and no call for a fortnight does not
        _, f = calllist.score_row(row(stage="first_round", next_interview_at="2026-11-26 10:00",
                                      last_contact_at="2026-11-23", last_contact_kind="email",
                                      last_call_at="2026-11-10"), TODAY)
        self.assertIn("no call in the last 3 days", labels(f))
        _, f = calllist.score_row(row(stage="first_round", next_interview_at="2026-11-26 10:00",
                                      last_contact_at=None, last_call_at=None), TODAY)
        self.assertIn("no call in the last 3 days", labels(f))

    def test_greeting_name_never_splits_blindly(self):
        self.assertEqual(calllist.greeting_name({"candidate_name": "Mei Lin Tan", "known_as": "Mei Lin"}), "Mei Lin")
        self.assertEqual(calllist.greeting_name({"candidate_name": "Chen Yu", "known_as": None}), "Chen Yu")

    def test_working_days(self):
        self.assertEqual(calllist.working_days_between(date(2026, 11, 18), TODAY), 5)
        self.assertEqual(calllist.working_days_between(date(2026, 11, 20), date(2026, 11, 23)), 1)


PIPE = [
    row(application_id=90, candidate_id=90, candidate_name="Hal Onhold", stage="offer", offer_sent_at="2026-11-10",
        last_contact_at="2026-11-09", role_status="on hold"),
    row(application_id=1, candidate_id=1, candidate_name="Ann Offer", stage="offer", offer_sent_at="2026-11-18",
        last_contact_at="2026-11-18", last_contact_kind="email"),
    row(application_id=2, candidate_id=2, candidate_name="Ben Tomorrow", stage="first_round",
        next_interview_at="2026-11-26 10:00", last_contact_at="2026-11-19", last_contact_kind="email"),
    row(application_id=3, candidate_id=3, candidate_name="Cat Healthy"),
    row(application_id=5, candidate_id=5, candidate_name="Mei Lin Tan", known_as="Mei Lin", stage="final_round",
        last_contact_at="2026-11-13", last_contact_kind="email"),
    row(application_id=4, candidate_id=2, candidate_name="Ben Tomorrow", stage="sourced", last_contact_at="2026-11-19"),
] + [row(application_id=10 + i, candidate_id=10 + i, candidate_name=f"Stale {i:02d}", stage="sourced",
         last_contact_at=f"2026-10-{10 + i:02d}") for i in range(12)]


class BuildCallListTests(unittest.TestCase):
    def setUp(self):
        p1 = mock.patch.object(calllist.crm, "get_consultant",
                               return_value={"id": 1, "name": "Sam Consultant", "desk": "Quant Research"}, create=True)
        p2 = mock.patch.object(calllist.crm, "pipeline_for_consultant", return_value=PIPE, create=True)
        p3 = mock.patch.object(calllist.config, "DEMO_TODAY", "2026-11-25", create=True)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_template_fallback_on_model_failure(self):
        with mock.patch.object(llm, "call_json", side_effect=llm.LLMError("boom")):
            res = calllist.build_call_list(1)
        self.assertEqual(res["meta"]["wording"], "template")
        self.assertEqual(len(res["calls"]), 10)
        self.assertEqual(res["calls"][0]["candidate"], "Ann Offer")
        self.assertEqual(res["calls"][1]["candidate"], "Ben Tomorrow")
        self.assertEqual(res["calls"][2]["candidate"], "Mei Lin Tan")
        self.assertTrue(res["calls"][2]["opener"].startswith("Hi Mei Lin, it's Sam."), res["calls"][2]["opener"])
        self.assertTrue(res["calls"][0]["opener"].startswith("Hi Ann Offer, it's Sam."))  # no known_as: full name, no blind split
        self.assertTrue(all(c["reason"] and c["opener"] for c in res["calls"]))
        names = [c["candidate"] for c in res["calls"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("Cat Healthy", names)
        self.assertNotIn("Hal Onhold", names)  # role on hold: never on the list, never above live work
        self.assertEqual([c["rank"] for c in res["calls"]], list(range(1, 11)))
        for k in ("rank", "candidate", "phone", "client", "role", "stage", "score", "factors", "last_contact",
                  "reason", "opener"):
            self.assertIn(k, res["calls"][0])
        self.assertNotIn("_facts", res["calls"][0])
        self.assertNotIn("_greet", res["calls"][0])

    def test_template_fallback_without_key(self):
        with mock.patch.object(llm, "call_json", side_effect=llm.LLMUnavailable("no key")):
            res = calllist.build_call_list(1)
        self.assertEqual(res["meta"]["wording"], "template")

    def test_model_wording_used_when_complete(self):
        def fake(system, user, max_tokens=4000, **kw):
            return ({"calls": [{"rank": i, "reason": f"Reason {i}", "opener": f"Opener {i}"} for i in range(1, 11)]},
                    {"model": "m", "ms": 1, "input_tokens": 1, "output_tokens": 1})
        with mock.patch.object(llm, "call_json", side_effect=fake) as cj:
            res = calllist.build_call_list(1)
        self.assertEqual(cj.call_count, 1)
        user = cj.call_args[0][1]
        self.assertIn("first name, to use in the opener: Sam", user)
        self.assertIn('"greet_as": "Mei Lin"', user)
        self.assertEqual(res["meta"]["wording"], "model")
        self.assertEqual(res["calls"][0]["reason"], "Reason 1")

    def test_partial_model_reply_falls_back(self):
        fake = mock.Mock(return_value=({"calls": [{"rank": 1, "reason": "r", "opener": "o"}]}, {"model": "m"}))
        with mock.patch.object(llm, "call_json", fake):
            res = calllist.build_call_list(1)
        self.assertEqual(res["meta"]["wording"], "template")


if __name__ == "__main__":
    unittest.main()
