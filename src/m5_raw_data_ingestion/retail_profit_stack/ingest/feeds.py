"""The feeds, and where the loader keeps its things.

Implements LLD section 3 (The files). A feed is one kind of file that keeps arriving, such as
the weekly order files. Each feed fills one source table, and has the same name as that table.
"""

from dataclasses import dataclass
from pathlib import Path

from retail_profit_stack.config import LANDING_DIR, LOADED_DIR, MAPPINGS_FILE, STATE_FILE
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS

FEEDS = list(SOURCE_SCHEMAS)


@dataclass(frozen=True)
class Places:
    """The folders and files one loader works with. The lab and the tests use their own."""

    landing: Path = LANDING_DIR  # the files as they arrive
    loaded: Path = LOADED_DIR  # one loaded piece per file, by feed
    state_file: Path = STATE_FILE  # the load record and the workflows' saved state
    mappings_file: Path = MAPPINGS_FILE  # the mappings a person has approved


def feed_of(file_name: str) -> str:
    """Which feed a file belongs to, from the start of its name.

    order_items_2026-10-12.csv belongs to order_items. The longest matching name wins.
    """
    matches = [feed for feed in FEEDS if file_name.startswith(feed)]
    if not matches:
        raise ValueError(f"{file_name} does not belong to any feed: {', '.join(FEEDS)}")
    return max(matches, key=len)


def expected_columns(feed: str) -> list[str]:
    """The columns a file of this feed must have, in the contract's order."""
    return SOURCE_SCHEMAS[feed].names


def landing_files(places: Places) -> list[str]:
    """The names of the files in the landing folder, in name order."""
    return sorted(file.name for file in places.landing.glob("*.csv"))


def piece_path(places: Places, file_name: str) -> Path:
    """Where a file's loaded piece is written."""
    return places.loaded / feed_of(file_name) / f"{Path(file_name).stem}.parquet"
