"""Paths and settings shared by the milestone's modules.

Implements LLD section 1 (Files). Every path is inside this milestone's own
folder; only the .env file is shared at the project root.
"""

from pathlib import Path

MILESTONE_DIR = Path(__file__).resolve().parent.parent
MOCK_DIR = MILESTONE_DIR / "data" / "mock"  # still mocked: the reporting period
# New in milestone 5: records arrive as files and are loaded piece by piece.
LANDING_DIR = MILESTONE_DIR / "data" / "landing"  # the files as they arrive (generated)
LOADED_DIR = MILESTONE_DIR / "data" / "loaded"  # one loaded piece per file, by feed
STATE_FILE = MILESTONE_DIR / "data" / "loader_state.sqlite"  # load record and saved workflows
MAPPINGS_FILE = MILESTONE_DIR / "data" / "approved_mappings.json"
# New in milestone 6.
LATE_DIR = MILESTONE_DIR / "data" / "landing_late"  # files that arrive after month-end close
DECISIONS_FILE = MILESTONE_DIR / "data" / "review_decisions.json"  # what people decided at the desk
VERSIONS_FILE = MILESTONE_DIR / "data" / "analyst_versions.json"  # the analyst's later versions
# The business's records are now the loaded pieces. Earlier code still calls this SOURCE_DIR.
SOURCE_DIR = LOADED_DIR
WAREHOUSE_DIR = MILESTONE_DIR / "data" / "warehouse"  # calculated tables, written by the pipeline
RULEBOOK_FILE = MILESTONE_DIR / "data" / "quality_rulebook.md"
EVALS_DIR = MILESTONE_DIR / "evals"
DEFINITIONS_FILE = Path(__file__).resolve().parent / "definitions" / "metrics_v1.json"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"

METRIC_VERSION = "1.0.0"
