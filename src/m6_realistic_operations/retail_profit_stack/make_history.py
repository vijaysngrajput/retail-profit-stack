"""Build the two runs this milestone starts with.

Implements LLD section 5 (The two runs the milestone starts with). A history with one run has
nothing to compare. These two runs tell the true story of this project: before milestone 3,
duplicated records were counted; since milestone 3, they are set aside.

Run it with:  uv run python -m retail_profit_stack.make_history          (month-end close)
         or:  uv run python -m retail_profit_stack.make_history --late   (and the late files)
"""

import shutil
import sys
from dataclasses import replace
from pathlib import Path

from retail_profit_stack.config import LATE_DIR, SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.ingest.dispatch import load_batch
from retail_profit_stack.ingest.feeds import Places
from retail_profit_stack.transform.pipeline import PipelineRun, run_pipeline

FIRST_NOTE = "Duplicated records are counted, as before milestone 3"
SECOND_NOTE = "Duplicated records are set aside"


def make_history(
    warehouse_dir: Path = WAREHOUSE_DIR, source_dir: Path = SOURCE_DIR, engine_name: str = "sql"
) -> list[PipelineRun]:
    """Clear the warehouse folder, then make RUN-0001 and RUN-0002.

    New in milestone 5: when the real folders are used, the landing files are loaded first.
    Loading is safe to repeat, so files that are already loaded are left alone.
    """
    if source_dir == SOURCE_DIR:
        load_batch()
    if warehouse_dir.exists():
        shutil.rmtree(warehouse_dir)
    first = run_pipeline(engine_name, source_dir, warehouse_dir, quarantine=False, note=FIRST_NOTE)
    second = run_pipeline(engine_name, source_dir, warehouse_dir, quarantine=True, note=SECOND_NOTE)
    return [first, second]


LATE_NOTE = "Late and corrected files arrived after month-end close"


def apply_late_files(
    places: Places | None = None,
    warehouse_dir: Path = WAREHOUSE_DIR,
    late_dir: Path = LATE_DIR,
    decisions_file: Path | None = None,
) -> PipelineRun:
    """New in milestone 6: load the files that arrived late, then run only what they touch.

    The late files are loaded into the same records as the first wave. The corrected file has
    the same name as one loaded earlier, and replaces it. The run after is incremental.
    """
    places = places or Places()
    late_places = replace(places, landing=late_dir)
    load_batch(places=late_places)
    return run_pipeline(
        "sql", places.loaded, warehouse_dir, note=LATE_NOTE, incremental=True,
        decisions_file=decisions_file,
    )  # fmt: skip


if __name__ == "__main__":
    for made in make_history():
        print(f"{made.run_id}: {made.record['note']}")
        print(f"  findings: {made.record['findings']}, quarantined: {made.record['quarantined']}")
        print(f"  lineage adds up: {made.record['lineage_adds_up']}")
    if "--late" in sys.argv:
        late = apply_late_files()
        print(f"{late.run_id}: {late.record['note']}")
        print(f"  mode: {late.record['mode']}, months: {late.record['months_recalculated']}")
