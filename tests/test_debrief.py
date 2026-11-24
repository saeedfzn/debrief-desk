"""Debrief feature. No network: llm.call_json and the crm lookups are patched."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import debrief, llm  # noqa: E402

FRESH = """Debrief call: Priya Shah after second round at Fernhallow Capital (Quantitative Researcher)
Date: 2026-11-24

Consultant: Hi Priya, how did it go?
Candidate: Pretty well I think.
"""
ON_FILE = [
    {"id": 1, "round": "first round", "held_on": "2026-11-03", "title": "t1", "transcript": "Debrief one text",
     "candidate_name": "Oliver Brennan", "role_id": 1, "role_title": "Quantitative Researcher"},
    {"id": 2, "round": "final round", "held_on": "2026-11-10", "title": "t2", "transcript": "Debrief two text",
     "candidate_name": "Mei Lin Tan", "role_id": 1, "role_title": "Quantitative Researcher"},
]
META = {"model": "m", "ms": 1, "input_tokens": 100, "output_tokens": 50}

NOTE_REPLY = {
    "round": "second round",
    "crm_note": {"headline": "Went well", "stage_after": "second_round done", "how_it_went": "Fine.",
                 "rounds": [{"round": "second", "format": "coding", "asked": ["a"], "candidate_view": "ok"}],
                 "compensation": {"current": "not discussed", "expectation": "not discussed", "notes": ""},
                 "notice_and_non_compete": "3 months", "competing_processes": [], "risks": [],
                 "next_actions": [{"action": "Chase feedback", "owner": "consultant", "due": "2026-11-26"}]},
    "emails": {"candidate": {"subject": "Thanks", "body": "Hi Priya"},
               "client": {"subject": "Priya feedback", "body": "Hi,"}},
}
PACK_REPLY = {"process": [{"round": "first", "format": "phone", "who": "PM", "what_they_look_for": "clarity"}],
              "question_themes": [{"theme": "probability", "examples": ["dice"], "seen_in": 9}],
              "went_well": ["x"], "tripped_people_up": ["y"], "advice": ["z"], "logistics": []}


def fake_call_json(system, user, max_tokens=4000, **kw):
    if "prep pack" in system:
        fake_call_json.pack_user = user
        return PACK_REPLY, META
    return NOTE_REPLY, META


class DebriefTests(unittest.TestCase):
    def patch_crm(self, client_found=True, on_file=ON_FILE, next_rows=None):
        c = debrief.crm
        patches = [
            mock.patch.object(c, "find_candidate_by_name", create=True,
                              return_value={"id": 7, "name": "Priya Shah", "email": "priya.shah@example.com",
                                            "consultant_id": 1}),
            mock.patch.object(c, "find_client_by_name", create=True,
                              return_value={"id": 1, "name": "Fernhallow Capital", "kind": "Hedge fund",
                                            "city": "London"} if client_found else None),
            mock.patch.object(c, "get_application", create=True,
                              return_value={"role_title": "Quantitative Researcher", "role_id": 1,
                                            "stage": "second_round"}),
            mock.patch.object(c, "get_consultant", create=True,
                              return_value={"id": 1, "name": "Hannah Clarke", "desk": "Quant Research"}),
            mock.patch.object(c, "debriefs_for_client", create=True, return_value=list(on_file)),
            mock.patch.object(c, "next_candidates_for_client", create=True,
                              return_value=next_rows if next_rows is not None else
                              [{"candidate_id": 9, "candidate_name": "Tom Next", "role_id": 1,
                                "role_title": "Quantitative Researcher", "stage": "first_round",
                                "next_interview_at": "2026-11-27 10:00", "skills": "python",
                                "current_title": "Analyst"}]),
            mock.patch.object(debrief.config, "DEMO_TODAY", "2026-11-25", create=True),
            mock.patch.object(llm, "call_json", side_effect=fake_call_json),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_header_parse(self):
        h = debrief.parse_header(FRESH)
        self.assertEqual(h, {"candidate": "Priya Shah", "round": "second round", "client": "Fernhallow Capital",
                             "role": "Quantitative Researcher", "date": "2026-11-24"})
        h = debrief.parse_header("Debrief call: A B after final round at X Y (Researcher, Systematic Equities)\nDate: 2026-11-01")
        self.assertEqual(h["role"], "Researcher, Systematic Equities")

    def test_full_shape_and_built_from(self):
        self.patch_crm()
        res = debrief.run_debrief(FRESH)
        self.assertEqual(set(res), {"matched", "crm_note", "emails", "prep_pack", "meta"})
        self.assertEqual(res["matched"], {"candidate": "Priya Shah", "client": "Fernhallow Capital",
                                          "role": "Quantitative Researcher", "round": "second round"})
        self.assertEqual(res["emails"]["candidate"]["to"], "priya.shah@example.com")
        self.assertIn("Fernhallow Capital", res["emails"]["client"]["to"])
        pack = res["prep_pack"]
        self.assertEqual(pack["for_candidate"]["name"], "Tom Next")
        self.assertEqual([b["candidate"] for b in pack["built_from"]], ["Oliver Brennan", "Mei Lin Tan", "Priya Shah"])
        self.assertEqual(pack["question_themes"][0]["seen_in"], 3)  # clamped to number of debriefs
        self.assertEqual(res["meta"]["calls"], 2)
        for k in ("client", "role", "for_candidate", "built_from", "process", "question_themes", "went_well",
                  "tripped_people_up", "advice", "logistics"):
            self.assertIn(k, pack)
        self.assertIn("Number of debriefs: 3", fake_call_json.pack_user)

    def test_pack_never_addressed_to_a_different_role(self):
        other = [{"candidate_id": 8, "candidate_name": "Other Role", "role_id": 2, "role_title": "Quant Developer",
                  "stage": "first_round", "next_interview_at": "2026-11-26 09:00", "skills": "", "current_title": ""}]
        on_file = ON_FILE + [{"id": 5, "round": "first round", "held_on": "2026-11-01", "title": "t5",
                              "transcript": "Other role text", "candidate_name": "Dev Person", "role_id": 2,
                              "role_title": "Quant Developer"}]
        self.patch_crm(on_file=on_file, next_rows=other)
        res = debrief.run_debrief(FRESH)
        pack = res["prep_pack"]
        self.assertIsNone(pack["for_candidate"]["name"])
        self.assertEqual(pack["role"], "Quantitative Researcher")
        # same-role debriefs first, the other role last and flagged
        self.assertEqual([b["candidate"] for b in pack["built_from"]],
                         ["Oliver Brennan", "Mei Lin Tan", "Priya Shah", "Dev Person"])
        self.assertEqual([b["same_role"] for b in pack["built_from"]], [True, True, True, False])
        self.assertIn("OTHER ROLE", fake_call_json.pack_user)
        self.assertNotIn("Other Role", fake_call_json.pack_user)

    def test_date_guide_resolves_relative_dates_from_the_call(self):
        g = debrief.date_guide("2026-11-24")
        self.assertIn("Tuesday 2026-11-24", g)
        self.assertIn("tomorrow = Wed 2026-11-25", g)
        self.assertIn("Fri 2026-11-27", g)
        self.assertIn("week starting Mon 2026-11-16", g)

    def test_note_prompt_gets_call_date_and_pronouns(self):
        self.patch_crm()
        seen = {}

        def capture(system, user, max_tokens=4000, **kw):
            if "prep pack" in system:
                return PACK_REPLY, META
            seen["user"] = user
            return NOTE_REPLY, META
        with mock.patch.object(llm, "call_json", side_effect=capture):
            debrief.run_debrief(FRESH)
        self.assertIn("tomorrow = Wed 2026-11-25", seen["user"])
        self.assertIn('"pronouns": "they"', seen["user"])  # none on record: they
        self.assertIn("do not comment on those later changes", seen["user"])

    def test_transcript_already_on_file_not_counted_twice(self):
        on_file = ON_FILE + [{"id": 3, "round": "second round", "held_on": "2026-11-24", "title": "t3",
                              "transcript": FRESH, "candidate_name": "Priya Shah"}]
        self.patch_crm(on_file=on_file)
        res = debrief.run_debrief(FRESH)
        self.assertEqual(len(res["prep_pack"]["built_from"]), 3)

    def test_unmatched_client(self):
        self.patch_crm(client_found=False)
        res = debrief.run_debrief(FRESH)
        self.assertIsNone(res["matched"]["client"])
        self.assertEqual(len(res["prep_pack"]["built_from"]), 1)
        self.assertEqual(res["prep_pack"]["client"], "Fernhallow Capital")
        self.assertIsNone(res["prep_pack"]["for_candidate"]["name"])
        self.assertTrue(res["crm_note"]["headline"])

    def test_prompt_rules(self):
        from app import prompts
        for p in (prompts.DEBRIEF_SYSTEM, prompts.PREP_SYSTEM):
            self.assertIn("Do not invent", p)
            self.assertIn("not discussed", p)
        self.assertIn("MUST NOT mention the candidate's other interview", prompts.DEBRIEF_SYSTEM)
        self.assertIn("British English", prompts.DEBRIEF_SYSTEM)
        self.assertIn("Never promise an outcome", prompts.DEBRIEF_SYSTEM)
        self.assertIn("office attendance policy", prompts.DEBRIEF_SYSTEM)
        self.assertIn("No compensation tactics", prompts.DEBRIEF_SYSTEM)
        self.assertIn("relative to that call date", prompts.DEBRIEF_SYSTEM)
        self.assertIn("use the pronouns on their CRM record", prompts.RULES)
        self.assertIn("must not include any other candidate's private", prompts.PREP_SYSTEM)

    def test_empty_transcript(self):
        with self.assertRaises(ValueError):
            debrief.run_debrief("   ")


if __name__ == "__main__":
    unittest.main()
