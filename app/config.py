"""Settings. Every "today" in the app comes from DEMO_TODAY, never the system clock."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEMO_TODAY: str = os.environ.get("DEMO_TODAY", "2026-11-25")
DB_PATH: Path = ROOT / "data" / "crm.db"
SCHEMA_PATH: Path = ROOT / "data" / "schema.sql"
TRANSCRIPTS_DIR: Path = ROOT / "data" / "transcripts"
# The call list and Ask the pipeline use MODEL. The CRM note, emails and prep pack use WRITER_MODEL,
# a stronger model, because they have to stay faithful to long transcripts.
MODEL: str = os.environ.get("DEBRIEF_MODEL", "claude-sonnet-5-5")
WRITER_MODEL: str = os.environ.get("DEBRIEF_WRITER_MODEL", "claude-opus-5-5")
