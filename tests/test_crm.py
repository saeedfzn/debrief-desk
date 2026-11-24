"""Tests for the seed data and the CRM layer. Builds a throwaway DB; never touches data/crm.db.

Run: py -3 -m unittest discover -s tests -p "test_crm.py"
"""
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, crm  # noqa: E402

_spec = importlib.util.spec_from_file_location("seed", ROOT / "data" / "seed.py")
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


class CrmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.db = seed.build(cls.tmp / "crm_test.db")
        cls._orig = (config.DB_PATH, config.DEMO_TODAY)
        config.DB_PATH = cls.db
        config.DEMO_TODAY = "2026-11-25"
        cls.client_a = crm.find_client_by_name("Fernhallow Capital")
        fresh = [t for t in crm.list_sample_transcripts() if t["id"].startswith("fresh_")]
        cls.fresh = fresh[0]
        cls.fresh_header = seed.parse_header(cls.fresh["text"])

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH, config.DEMO_TODAY = cls._orig
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- seed

    def test_seed_builds_with_expected_volumes(self):
        conn = sqlite3.connect(self.db)
        n = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
        self.assertEqual(n("consultants"), 3)
        self.assertEqual(n("clients"), 3)
        self.assertTrue(6 <= n("roles") <= 8)
        self.assertTrue(40 <= n("candidates") <= 50)
        self.assertTrue(45 <= n("applications") <= 55)
        self.assertTrue(120 <= n("activities") <= 180)
        self.assertEqual(n("debriefs"), 6)
        # nothing dated after DEMO_TODAY except future interviews
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM activities WHERE at > '2026-11-25'").fetchone()[0], 0)
        conn.close()

    def test_seed_is_deterministic(self):
        other = seed.build(self.tmp / "again.db")

        def dump(p):
            c = sqlite3.connect(p)
            out = list(c.iterdump())
            c.close()
            return out

        self.assertEqual(dump(self.db), dump(other))

    def test_fictional_contact_details(self):
        conn = sqlite3.connect(self.db)
        for email, phone in conn.execute("SELECT email, phone FROM candidates"):
            self.assertTrue(email.endswith("@example.com"), email)
            self.assertRegex(phone, r"^07700 900\d{3}$")
        conn.close()

    def test_transcript_headers_and_length(self):
        files = sorted((ROOT / "data" / "transcripts").glob("*.txt"))
        self.assertEqual(len(files), 7)
        for f in files:
            text = f.read_text(encoding="utf-8")
            h = seed.parse_header(text)
            self.assertIsNotNone(crm.find_candidate_by_name(h["cand"]), f.name)
            body = "\n".join(text.splitlines()[2:])
            words = len(body.split())
            self.assertTrue(450 <= words <= 700, f"{f.name}: {words} words")
            self.assertNotIn(chr(0x2014), text)
            self.assertNotIn(chr(0x2013), text)

    # ---------------------------------------------------------------- lookups

    def test_consultants_and_clients_keys(self):
        cons = crm.list_consultants()
        self.assertEqual(len(cons), 3)
        self.assertEqual(set(cons[0]), {"id", "name", "desk"})
        self.assertEqual(crm.get_consultant(1)["id"], 1)
        self.assertIsNone(crm.get_consultant(999))
        clients = crm.list_clients()
        self.assertEqual(set(clients[0]), {"id", "name", "kind", "city"})

    def test_name_matching_is_tolerant(self):
        self.assertEqual(crm.find_client_by_name("fernhallow")["id"], self.client_a["id"])
        self.assertEqual(crm.find_client_by_name("FERNHALLOW CAPITAL LLP")["id"], self.client_a["id"])
        self.assertEqual(crm.find_candidate_by_name("aisha karim")["name"], "Aisha Karim")
        self.assertEqual(crm.find_candidate_by_name("Marchetti")["name"], "Sofia Marchetti")
        self.assertEqual(crm.find_client_by_name("Lumenfold")["name"], "Lumenfold Research")
        self.assertEqual(crm.find_candidate_by_name("Dr Sofia Marchetti")["name"], "Sofia Marchetti")
        self.assertIsNone(crm.find_client_by_name(""))
        # unknown names must not fall onto a real record through a generic word
        self.assertIsNone(crm.find_client_by_name("Northgate Capital"))
        self.assertIsNone(crm.find_client_by_name("Some Other Trading"))
        self.assertIsNone(crm.find_client_by_name("Research"))
        self.assertIsNone(crm.find_candidate_by_name("Daniel Smith"))
        self.assertIsNone(crm.find_candidate_by_name("Sofia Rossi"))

    def test_get_application_keys(self):
        cand = crm.find_candidate_by_name(self.fresh_header["cand"])
        app = crm.get_application(cand["id"], self.client_a["id"])
        for k in ("id", "candidate_id", "role_id", "role_title", "stage", "stage_updated",
                  "next_interview_at", "offer_sent_at", "status"):
            self.assertIn(k, app)
        self.assertEqual(app["role_title"], self.fresh_header["role"])

    def test_client_a_has_three_debriefs_oldest_first(self):
        ds = crm.debriefs_for_client(self.client_a["id"])
        self.assertEqual(len(ds), 3)
        for d in ds:
            for k in ("id", "round", "held_on", "title", "transcript", "candidate_name"):
                self.assertIn(k, d)
        self.assertEqual([d["held_on"] for d in ds], sorted(d["held_on"] for d in ds))
        self.assertEqual(len({d["candidate_name"] for d in ds}), 3)
        self.assertEqual(len({d["round"] for d in ds}), 3)
        # client B has 2, client C has 1
        self.assertEqual(len(crm.debriefs_for_client(crm.find_client_by_name("Brackenvane")["id"])), 2)
        self.assertEqual(len(crm.debriefs_for_client(crm.find_client_by_name("Lumenfold")["id"])), 1)

    def test_fresh_transcript_candidate_in_db_but_debrief_not(self):
        self.assertFalse(self.fresh["in_db"])
        cand = crm.find_candidate_by_name(self.fresh_header["cand"])
        self.assertEqual(cand["name"], self.fresh_header["cand"])
        self.assertIsNotNone(crm.get_application(cand["id"], self.client_a["id"]))
        titles = {d["title"] for d in crm.debriefs_for_client(self.client_a["id"])}
        self.assertNotIn(self.fresh["title"], titles)
        others = [t for t in crm.list_sample_transcripts() if not t["id"].startswith("fresh_")]
        self.assertEqual(len(others), 6)
        self.assertTrue(all(t["in_db"] for t in others))
        self.assertEqual(set(others[0]), {"id", "title", "date", "in_db", "text"})

    def test_client_a_has_a_next_candidate(self):
        cand = crm.find_candidate_by_name(self.fresh_header["cand"])
        nxt = crm.next_candidates_for_client(self.client_a["id"], exclude_candidate_id=cand["id"])
        self.assertTrue(nxt)
        first = nxt[0]
        for k in ("candidate_id", "candidate_name", "role_title", "stage", "next_interview_at", "skills",
                  "current_title"):
            self.assertIn(k, first)
        self.assertEqual(first["candidate_name"], "Aisha Karim")
        self.assertEqual(first["role_title"], self.fresh_header["role"])
        self.assertTrue("2026-11-25" <= first["next_interview_at"] <= "2026-11-30")
        self.assertNotIn(cand["id"], [n["candidate_id"] for n in nxt])
        self.assertEqual([n["next_interview_at"] for n in nxt], sorted(n["next_interview_at"] for n in nxt))

    def test_next_candidates_prefer_the_same_role(self):
        brack = crm.find_client_by_name("Brackenvane Trading")
        lukas = crm.find_candidate_by_name("Lukas Brandt")
        app = crm.get_application(lukas["id"], brack["id"])
        nxt = crm.next_candidates_for_client(brack["id"], exclude_candidate_id=lukas["id"], role_id=app["role_id"])
        self.assertTrue(nxt)
        self.assertEqual(nxt[0]["role_id"], app["role_id"])
        same = [n for n in nxt if n["role_id"] == app["role_id"]]
        self.assertEqual(nxt[:len(same)], same)  # all same-role rows come first
        self.assertTrue(any(n["role_id"] != app["role_id"] for n in nxt))  # Grace is on a different role
        for k in ("notice_weeks", "non_compete_months", "pronouns", "known_as"):
            self.assertIn(k, nxt[0])

    def test_run_readonly_sql_truncates_and_stops_runaways(self):
        import time
        res = crm.run_readonly_sql("SELECT * FROM activities", limit=5)
        self.assertEqual(len(res["rows"]), 5)
        self.assertTrue(res["truncated"])
        self.assertFalse(crm.run_readonly_sql("SELECT 1")["truncated"])
        t0 = time.perf_counter()
        with self.assertRaises(ValueError):
            crm.run_readonly_sql("SELECT COUNT(*) FROM activities a, activities b, activities c, activities d")
        self.assertLess(time.perf_counter() - t0, 2.0)
        with self.assertRaises(ValueError):
            crm.run_readonly_sql("SELECT length(hex(zeroblob(20000000)))")

    def test_pipeline_for_consultant_keys_and_situations(self):
        rows = crm.pipeline_for_consultant(1)
        self.assertGreaterEqual(len(rows), 12)
        keys = {"application_id", "candidate_id", "candidate_name", "known_as", "pronouns", "client_name",
                "role_title", "role_status", "stage",
                "stage_updated", "next_interview_at", "offer_sent_at", "notice_weeks", "non_compete_months",
                "phone", "last_contact_at", "last_contact_kind", "last_contact_summary", "last_call_at"}
        for r in rows:
            self.assertTrue(keys <= set(r), keys - set(r))
        by = {r["candidate_name"]: r for r in rows}
        # offer sent 3+ working days ago, nothing since
        rohan = by["Rohan Mehta"]
        self.assertEqual(rohan["stage"], "offer")
        self.assertLess(rohan["last_contact_at"], rohan["offer_sent_at"])
        # interview tomorrow, no prep logged
        grace = by["Grace Holloway"]
        self.assertTrue(grace["next_interview_at"].startswith("2026-11-26"))
        self.assertNotIn("prep", grace["last_contact_summary"].lower())
        # final round, not contacted for 8+ days
        self.assertEqual(by["Mei Lin Tan"]["stage"], "final_round")
        self.assertLessEqual(by["Mei Lin Tan"]["last_contact_at"], "2026-11-17")
        # long non-compete
        self.assertGreaterEqual(by["Ewan Fairley"]["non_compete_months"], 12)
        # never contacted
        self.assertIsNone(by["Jonah Whitcombe"]["last_contact_at"])
        # only active applications
        conn = sqlite3.connect(self.db)
        for r in rows:
            st = conn.execute("SELECT status FROM applications WHERE id = ?", (r["application_id"],)).fetchone()[0]
            self.assertEqual(st, "active")
        conn.close()

    def test_run_readonly_sql_caps_result_size(self):
        # one value over the per-value limit: SQLite refuses to build it (an error, or NULL from printf)
        try:
            res = crm.run_readonly_sql("SELECT printf('%.*c', 5000000, 'x') FROM activities LIMIT 200")
            self.assertTrue(all(v is None or len(v) <= 100_000 for r in res["rows"] for v in r))
        except ValueError:
            pass
        with self.assertRaises(ValueError):
            crm.run_readonly_sql("SELECT length(zeroblob(200000))")
        # many values each under the per-value limit, but too much in total
        with self.assertRaises(ValueError) as cm:
            crm.run_readonly_sql("SELECT printf('%.*c', 90000, 'x') FROM activities LIMIT 200")
        self.assertIn("too large to show", str(cm.exception))
        with self.assertRaises(ValueError):
            crm.run_readonly_sql("SELECT zeroblob(90000) FROM activities LIMIT 200")
        # an ordinary result is untouched
        res = crm.run_readonly_sql("SELECT printf('%.*c', 2000, 'x') FROM activities LIMIT 100")
        self.assertEqual(len(res["rows"]), 100)

    def test_last_contact_counts_only_contact_with_the_candidate(self):
        conn = sqlite3.connect(self.db)
        parties = {r[0] for r in conn.execute("SELECT DISTINCT with_party FROM activities")}
        self.assertEqual(parties, {"candidate", "client", "internal"})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM activities WHERE kind = 'note'"
                                      " AND with_party != 'internal'").fetchone()[0], 0)
        for summary in ("Chased Lumenfold for CV feedback%", "Ingrid Saarinen at Fernhallow: offer coming%",
                        "CV submitted to%", "Submitted%"):
            got = {r[0] for r in conn.execute("SELECT with_party FROM activities WHERE summary LIKE ?", (summary,))}
            self.assertEqual(got, {"client"}, summary)
        conn.close()
        for cid in (1, 2, 3):
            for r in crm.pipeline_for_consultant(cid):
                if r["last_contact_at"]:
                    row = crm._one("SELECT with_party FROM activities WHERE candidate_id = ? AND at = ?"
                                   " AND summary = ?", (r["candidate_id"], r["last_contact_at"],
                                                        r["last_contact_summary"]))
                    self.assertEqual(row["with_party"], "candidate", r["candidate_name"])
                if r["last_call_at"]:
                    self.assertLessEqual(r["last_call_at"], r["last_contact_at"])
        by = {r["candidate_name"]: r for r in crm.pipeline_for_consultant(3)}
        # Hugo's latest activities are emails to the client: they are not his last contact
        self.assertLess(by["Hugo Laurent"]["last_contact_at"], "2026-10-30")
        by = {r["candidate_name"]: r for r in crm.pipeline_for_consultant(1)}
        # Rohan: the call with Ingrid on 18 Nov was with the client, so nothing with him since the offer
        self.assertEqual(by["Rohan Mehta"]["last_contact_at"], "2026-11-17")

    def test_seed_histories_match_stages(self):
        conn = sqlite3.connect(self.db)
        # sourced and not yet screened: no call or email with the candidate may exist
        rows = conn.execute(
            "SELECT c.name FROM candidates c JOIN activities act ON act.candidate_id = c.id"
            " WHERE act.with_party = 'candidate' AND c.id IN (SELECT candidate_id FROM applications"
            " WHERE status = 'active' GROUP BY candidate_id HAVING MIN(stage = 'sourced') = 1)").fetchall()
        self.assertEqual(rows, [])
        # anyone placed whose start date has passed works at the firm they were placed with
        placed = conn.execute(
            "SELECT c.name, c.current_employer, cl.name, a.stage_updated, c.notice_weeks FROM applications a"
            " JOIN candidates c ON c.id = a.candidate_id JOIN roles r ON r.id = a.role_id"
            " JOIN clients cl ON cl.id = r.client_id WHERE a.stage = 'placed'").fetchall()
        from datetime import date, timedelta
        for name, employer, firm, upd, notice in placed:
            gone = date.fromisoformat(upd) + timedelta(weeks=notice or 0) < date(2026, 11, 25)
            garden = conn.execute("SELECT COUNT(*) FROM activities a JOIN candidates c ON c.id = a.candidate_id"
                                  " WHERE c.name = ? AND a.summary LIKE '%garden leave%'", (name,)).fetchone()[0]
            if gone and not garden:
                self.assertEqual(employer, firm, name)
        conn.close()

    def test_schema_text(self):
        text = crm.schema_text()
        for t in ("consultants", "clients", "roles", "candidates", "applications", "activities", "debriefs"):
            self.assertIn(f"CREATE TABLE {t}", text)

    def test_crm_layer_never_writes(self):
        self.assertFalse(hasattr(crm, "save_debrief"))
        with self.assertRaises(sqlite3.OperationalError):
            crm.connect().execute("DELETE FROM debriefs")

    def test_candidates_sit_with_the_matching_desk(self):
        owner = {c["name"]: c["consultant_id"] for c in
                 crm._all("SELECT name, consultant_id FROM candidates")}
        for name in ("Rohan Mehta", "Grace Holloway", "Mei Lin Tan", "Ewan Fairley", "Sofia Marchetti",
                     "Aisha Karim", "Ruth Abernethy"):
            self.assertEqual(owner[name], 1, name)
        for name in ("Samir Haddad", "Lukas Brandt", "Tariq Aziz", "Elena Petrova"):
            self.assertEqual(owner[name], 2, name)
        for name in ("Nikhil Rao", "Hugo Laurent", "Arjun Nair", "Zara Hussain"):
            self.assertEqual(owner[name], 3, name)
        aisha = crm._one("SELECT a.next_interview_at, a.role_id FROM applications a JOIN candidates c"
                         " ON c.id = a.candidate_id WHERE c.name = 'Aisha Karim' AND a.status = 'active'")
        sofia = crm._one("SELECT a.role_id FROM applications a JOIN candidates c"
                         " ON c.id = a.candidate_id WHERE c.name = 'Sofia Marchetti' AND a.status = 'active'")
        self.assertEqual(aisha["next_interview_at"], "2026-11-27 14:00")
        self.assertEqual(aisha["role_id"], sofia["role_id"])

    def test_known_as_and_pronouns(self):
        mei = crm.find_candidate_by_name("Mei Lin Tan")
        self.assertEqual(mei["known_as"], "Mei Lin")
        self.assertEqual(mei["pronouns"], "she")
        self.assertEqual(crm.find_candidate_by_name("Chen Yu")["known_as"], "Chen Yu")
        self.assertEqual(crm.find_candidate_by_name("Oliver Brennan")["pronouns"], "he")
        n = crm._one("SELECT COUNT(*) AS n FROM candidates WHERE pronouns NOT IN ('he','she','they')"
                     " OR pronouns IS NULL OR known_as IS NULL")["n"]
        self.assertEqual(n, 0)

    # ---------------------------------------------------------------- read-only SQL

    def test_run_readonly_sql_accepts_selects(self):
        res = crm.run_readonly_sql(
            "SELECT cl.name, COUNT(*) AS n FROM applications a JOIN roles r ON r.id = a.role_id "
            "JOIN clients cl ON cl.id = r.client_id WHERE a.status = 'active' GROUP BY cl.name ORDER BY n DESC"
        )
        self.assertEqual(res["columns"], ["name", "n"])
        self.assertEqual(len(res["rows"]), 3)
        self.assertIsInstance(res["rows"][0], list)
        res = crm.run_readonly_sql(
            "WITH last AS (SELECT candidate_id, MAX(at) AS at FROM activities GROUP BY candidate_id) "
            "SELECT c.name, julianday('2026-11-25') - julianday(l.at) AS days FROM candidates c "
            "JOIN last l ON l.candidate_id = c.id WHERE l.at < date('2026-11-25', '-8 days');"
        )
        self.assertTrue(res["rows"])
        self.assertEqual(len(crm.run_readonly_sql("SELECT * FROM activities", limit=5)["rows"]), 5)
        self.assertEqual(crm.run_readonly_sql("SELECT 'a;b' AS x")["rows"], [["a;b"]])
        res = crm.run_readonly_sql('SELECT stage_updated AS "Last update" FROM applications LIMIT 1')
        self.assertEqual(res["columns"], ["Last update"])

    def test_run_readonly_sql_rejects_writes_and_tricks(self):
        bad = [
            "INSERT INTO consultants VALUES (9, 'x', 'y')",
            "UPDATE candidates SET base_salary = 0",
            "DELETE FROM activities",
            "DROP TABLE candidates",
            "PRAGMA table_info(candidates)",
            "ATTACH DATABASE 'x.db' AS x",
            "SELECT 1; DELETE FROM activities",
            "SELECT 1; SELECT 2",
            "SELECT * FROM pragma_table_info('candidates')",
            "WITH x AS (SELECT 1) DELETE FROM activities",
            "SELECT 1 -- ; DROP TABLE candidates",
            "VACUUM",
            "",
        ]
        for sql in bad:
            with self.assertRaises(ValueError, msg=sql):
                crm.run_readonly_sql(sql)
        # and nothing changed
        conn = sqlite3.connect(self.db)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM consultants").fetchone()[0], 3)
        conn.close()

    def test_authorizer_blocks_even_if_text_checks_were_bypassed(self):
        conn = crm.connect()
        conn.set_authorizer(crm._authorizer)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM pragma_table_info('candidates')").fetchall()
        conn.close()


if __name__ == "__main__":
    unittest.main()
