"""Ask the pipeline. No network: llm.call_json is patched."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import ask as ask_mod  # noqa: E402
from app import crm, llm, main  # noqa: E402

META = {"model": "m", "ms": 1, "input_tokens": 10, "output_tokens": 5}


class AskTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(crm, "schema_text", return_value="CREATE TABLE x(a INT);", create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_happy_path_two_calls(self):
        replies = iter([({"sql": "SELECT stage, COUNT(*) AS n FROM applications GROUP BY stage", "note": ""}, META),
                        ({"answer": "Most active applications are at first round."}, META)])
        with mock.patch.object(llm, "call_json", side_effect=lambda *a, **k: next(replies)) as cj, \
                mock.patch.object(crm, "run_readonly_sql", create=True,
                                  return_value={"columns": ["stage", "n"], "rows": [["first_round", 9], ["offer", 2]]}):
            res = ask_mod.ask("How many per stage?")
        self.assertEqual(cj.call_count, 2)
        self.assertEqual(res["columns"], ["stage", "n"])
        self.assertEqual(res["rows"], [["first_round", 9], ["offer", 2]])
        self.assertEqual(res["answer"], "Most active applications are at first round.")
        self.assertTrue(res["sql"].startswith("SELECT"))
        for k in ("question", "sql", "columns", "rows", "answer", "meta"):
            self.assertIn(k, res)
        # the prompt must carry the demo date, not the system clock
        system = cj.call_args_list[0][0][0]
        self.assertIn("2026-11-25", system)

    def test_single_number_answered_by_code(self):
        with mock.patch.object(llm, "call_json", return_value=({"sql": "SELECT COUNT(*) AS active FROM applications"}, META)) as cj, \
                mock.patch.object(crm, "run_readonly_sql", create=True, return_value={"columns": ["active"], "rows": [[42]]}):
            res = ask_mod.ask("How many active?")
        self.assertEqual(cj.call_count, 1)
        self.assertIn("42", res["answer"])

    def test_truncated_result_says_first_200_rows(self):
        rows = [[f"name {i}", i] for i in range(200)]
        for truncated in (True, False):  # False: exactly 200 rows, as from the model's own LIMIT 200
            replies = iter([({"sql": "SELECT name, id FROM candidates LIMIT 200", "note": ""}, META),
                            ({"answer": "Here are the candidates."}, META)])
            with mock.patch.object(llm, "call_json", side_effect=lambda *a, **k: next(replies)) as cj, \
                    mock.patch.object(crm, "run_readonly_sql", create=True,
                                      return_value={"columns": ["name", "id"], "rows": rows, "truncated": truncated}):
                res = ask_mod.ask("List everyone")
            self.assertIn("first 200 rows", res["answer"])
            self.assertTrue(res["meta"]["truncated"])
            self.assertIn("do not state a total", cj.call_args_list[1][0][1])
            self.assertNotIn("200 in total", cj.call_args_list[1][0][1])

    def test_empty_result(self):
        with mock.patch.object(llm, "call_json", return_value=({"sql": "SELECT 1 WHERE 0"}, META)), \
                mock.patch.object(crm, "run_readonly_sql", create=True, return_value={"columns": ["x"], "rows": []}):
            res = ask_mod.ask("Anything?")
        self.assertIn("Nothing", res["answer"])

    def test_rejected_sql_raises_with_sql(self):
        with mock.patch.object(llm, "call_json", return_value=({"sql": "DELETE FROM candidates"}, META)), \
                mock.patch.object(crm, "run_readonly_sql", create=True,
                                  side_effect=ValueError("Only SELECT queries are allowed.")):
            with self.assertRaises(ask_mod.AskError) as cm:
                ask_mod.ask("Delete everyone")
        self.assertEqual(cm.exception.sql, "DELETE FROM candidates")
        self.assertIn("Only SELECT", cm.exception.message)

    def test_api_returns_400_shape(self):
        client = TestClient(main.app)
        with mock.patch.object(llm, "has_key", return_value=True), \
                mock.patch.object(llm, "call_json", return_value=({"sql": "DROP TABLE candidates"}, META)), \
                mock.patch.object(crm, "run_readonly_sql", create=True,
                                  side_effect=ValueError("Only one SELECT statement is allowed.")):
            r = client.post("/api/ask", json={"question": "drop it"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "Only one SELECT statement is allowed.", "sql": "DROP TABLE candidates"})

    def test_api_503_without_key(self):
        client = TestClient(main.app)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            r = client.post("/api/ask", json={"question": "anything"})
            self.assertEqual(r.status_code, 503)
            self.assertIn("error", r.json())
            h = client.get("/api/health").json()
            self.assertFalse(h["has_key"])
            self.assertEqual(h["mode"], "live")

    def test_real_call_json_raises_without_key(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaises(llm.LLMUnavailable):
                llm.call_json("s", "u")

    def test_extract_json(self):
        self.assertEqual(llm._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm._extract_json('Here you go: {"a": {"b": 2}} done'), {"a": {"b": 2}})


if __name__ == "__main__":
    unittest.main()
