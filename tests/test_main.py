"""The API when data/crm.db has not been built: a JSON error that says to run the seed, never a bare 500.

No network: llm.call_json is patched to fail the test if anything reaches it.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, crm, llm, main  # noqa: E402


class MissingDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(config, "DB_PATH", Path(self.tmp.name) / "not_built.db")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        guard = mock.patch.object(llm, "call_json", side_effect=AssertionError("model must not be called"))
        guard.start()
        self.addCleanup(guard.stop)
        key = mock.patch.object(llm, "has_key", return_value=True)
        key.start()
        self.addCleanup(key.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def check(self, r):
        self.assertEqual(r.status_code, 503, r.text)
        body = r.json()
        self.assertIn("error", body)
        self.assertIn("data/seed.py", body["error"])

    def test_every_data_endpoint_says_run_the_seed(self):
        self.check(self.client.get("/api/transcripts"))
        self.check(self.client.get("/api/transcripts/a1_oliver_brennan"))
        self.check(self.client.get("/api/consultants"))
        self.check(self.client.get("/api/calllist?consultant_id=1"))
        self.check(self.client.post("/api/debrief", json={"transcript": "Debrief call: A after first round at B\n"}))
        self.check(self.client.post("/api/ask", json={"question": "How many offers are out?"}))

    def test_health_reports_the_missing_database(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["has_db"])

    def test_crm_layer_raises_a_clear_error(self):
        self.assertFalse(crm.db_ready())
        with self.assertRaises(crm.CRMMissing):
            crm.list_consultants()
        with self.assertRaises(ValueError) as cm:
            crm.run_readonly_sql("SELECT 1")
        self.assertIn("data/seed.py", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
