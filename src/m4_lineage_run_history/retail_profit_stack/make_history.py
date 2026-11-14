"""Build the two runs this milestone starts with.

Implements LLD section 5 (The two runs the milestone starts with). A history with one run has
nothing to compare. These two runs tell the true story of this project: before milestone 3,
duplicated records were counted; since milestone 3, they are set aside.

Run it with:  uv run python -m retail_profit_stack.make_history
"""

import shutil
from pathlib import Path

from retail_profit_stack.config import SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.transform.pipeline import PipelineRun, run_pipeline

FIRST_NOTE = "Duplicated records are counted, as before milestone 3"
SECOND_NOTE = "Duplicated records are set aside"


def make_history(
    warehouse_dir: Path = WAREHOUSE_DIR, source_dir: Path = SOURCE_DIR, engine_name: str = "sql"
) -> list[PipelineRun]:
    """Clear the warehouse folder, then make RUN-0001 and RUN-0002."""
    if warehouse_dir.exists():
        shutil.rmtree(warehouse_dir)
    first = run_pipeline(engine_name, source_dir, warehouse_dir, quarantine=False, note=FIRST_NOTE)
    second = run_pipeline(engine_name, source_dir, warehouse_dir, quarantine=True, note=SECOND_NOTE)
    return [first, second]


if __name__ == "__main__":
    for made in make_history():
        print(f"{made.run_id}: {made.record['note']}")
        print(f"  findings: {made.record['findings']}, quarantined: {made.record['quarantined']}")
        print(f"  lineage adds up: {made.record['lineage_adds_up']}")
