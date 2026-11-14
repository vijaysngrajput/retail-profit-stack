"""Paths and settings shared by the milestone's modules.

Implements LLD section 1 (Files). Every path is inside this milestone's own
folder; only the .env file is shared at the project root.
"""

from pathlib import Path

MILESTONE_DIR = Path(__file__).resolve().parent.parent
MOCK_DIR = MILESTONE_DIR / "data" / "mock"  # still mocked: quality flags, reporting period
SOURCE_DIR = MILESTONE_DIR / "data" / "source"  # the business's records (generated)
WAREHOUSE_DIR = MILESTONE_DIR / "data" / "warehouse"  # calculated tables, written by the pipeline
EVALS_DIR = MILESTONE_DIR / "evals"
DEFINITIONS_FILE = Path(__file__).resolve().parent / "definitions" / "metrics_v1.json"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"

METRIC_VERSION = "1.0.0"
