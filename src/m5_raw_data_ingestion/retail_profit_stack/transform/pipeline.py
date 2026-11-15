"""The pipeline: load the records, check them, calculate the figures, and remember the run.

Implements LLD section 2 (One pipeline run, step by step). Milestone 3's checks and
milestone 2's transformations are unchanged. New in milestone 4: every run gets an id, its own
folder of tables, lineage, and one entry in the run history. Nothing is overwritten.

Run it with:  uv run python -m retail_profit_stack.transform.pipeline [sql|pandas]
"""

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from retail_profit_stack.config import METRIC_VERSION, SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.lineage.lineage import build_lineage, lineage_differences, lineage_steps
from retail_profit_stack.lineage.runs import (
    code_fingerprints,
    input_fingerprints,
    next_run_id,
    run_folder,
    save_run_record,
)
from retail_profit_stack.quality.checks import (
    CHECKS,
    check_outcomes,
    make_findings,
    number_rows,
    run_record_checks,
    run_totals_check,
)
from retail_profit_stack.quality.checks import SQL_DIR as CHECKS_SQL_DIR
from retail_profit_stack.quality.quarantine import split_records, without_row_numbers
from retail_profit_stack.transform.contracts import TableSchema
from retail_profit_stack.transform.engines import Engine, get_engine
from retail_profit_stack.transform.engines.base import IMPLEMENTATIONS_DIR
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS, ordered_specs


@dataclass
class PipelineRun:
    """What one run of the pipeline did."""

    engine: str
    tables: dict[str, pa.Table] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    # From milestone 3: what the quality checks found.
    check_outcomes: dict[str, str] = field(default_factory=dict)  # check name -> pass or outcome
    findings: pd.DataFrame = field(default_factory=pd.DataFrame)
    finding_records: pd.DataFrame = field(default_factory=pd.DataFrame)
    quarantined_counts: dict[str, int] = field(default_factory=dict)  # table -> rows set aside
    # New in milestone 4: the run's id, its lineage, and its record in the history.
    run_id: str = ""
    lineage: pd.DataFrame = field(default_factory=pd.DataFrame)
    lineage_steps: pd.DataFrame = field(default_factory=pd.DataFrame)
    record: dict = field(default_factory=dict)


def read_source(schema: TableSchema, source_dir: Path = SOURCE_DIR) -> pa.Table:
    """Build one source table from its loaded pieces (changed in milestone 5).

    Each loaded file is one piece. The table is every piece of its feed, read in file-name
    order and put end to end. A feed with no pieces gives an empty table.
    """
    pieces = sorted((source_dir / schema.name).glob("*.parquet"))
    if not pieces:
        return schema.arrow_schema().empty_table()
    return pa.concat_tables([pq.read_table(piece) for piece in pieces])


def load_sources(source_dir: Path = SOURCE_DIR) -> dict[str, pa.Table]:
    """Every source table, built from the pieces the loader wrote."""
    return {name: read_source(schema, source_dir) for name, schema in SOURCE_SCHEMAS.items()}


def run_transformations(engine: Engine, sources: dict[str, pa.Table]) -> dict[str, pa.Table]:
    """Run the six transformations in order on one engine. Each output feeds the next."""
    for name, table in sources.items():
        engine.register(name, table)
    outputs = {}
    for spec in ordered_specs():
        outputs[spec.name] = engine.run(spec)
        engine.register(spec.name, outputs[spec.name])
    return outputs


def code_files(engine_name: str) -> dict[str, Path]:
    """The file behind each transformation (for this engine) and each check."""
    extension = "sql" if engine_name == "sql" else "py"
    files = {}
    for spec in ordered_specs():
        files[spec.name] = IMPLEMENTATIONS_DIR / engine_name / f"{spec.name}.{extension}"
    for check in CHECKS:
        files[check.name] = CHECKS_SQL_DIR / f"{check.name}.sql"
    return files


def run_pipeline(
    engine_name: str | None = None,
    source_dir: Path = SOURCE_DIR,
    warehouse_dir: Path | None = WAREHOUSE_DIR,
    quarantine: bool = True,
    note: str = "",
) -> PipelineRun:
    """Calculate every table, and save the run. Pass warehouse_dir=None to save nothing.

    quarantine=False counts every record, the way the business calculated before milestone 3.
    note is one sentence saying why the run was made.
    """
    start = time.time()
    started_at = datetime.now().isoformat(timespec="seconds")
    engine = get_engine(engine_name)
    run = PipelineRun(engine=engine.name)

    # 1. Load the source tables and number their rows.
    sources = number_rows(load_sources(source_dir))
    # 2. Run the four record checks. Each returns its bad records.
    bad_records = run_record_checks(sources)
    # 3. Set the quarantined rows aside. With quarantine off, every row is kept.
    if quarantine:
        kept_numbered, quarantined = split_records(sources, bad_records, keep_row_numbers=True)
    else:
        kept_numbered, quarantined = sources, {}
    kept = without_row_numbers(kept_numbered)
    # 4. Calculate the figures from the kept rows only.
    run.tables = run_transformations(engine, kept)
    profit = run.tables["monthly_product_profit"]
    # 5. Check that the profit table adds up to the kept rows.
    totals_problems = run_totals_check(kept, profit)
    bad_records = pd.concat([bad_records, totals_problems], ignore_index=True)
    # 6. Group the bad records into findings.
    run.findings, run.finding_records = make_findings(bad_records, sources, quarantine)
    # 7. New: build the lineage, and prove that it adds up to the profit table.
    files = code_files(engine.name)
    code = code_fingerprints(files)
    run.lineage = build_lineage(kept_numbered)
    run.lineage_steps = lineage_steps(code)
    lineage_adds_up = lineage_differences(run.lineage, profit.to_pandas()).empty

    run.check_outcomes = check_outcomes(bad_records)
    if not quarantine:
        # Nothing was set aside, so a check that would quarantine only needs review.
        for check_name, outcome in run.check_outcomes.items():
            if outcome == "quarantine":
                run.check_outcomes[check_name] = "needs_review"
    run.quarantined_counts = {name: table.num_rows for name, table in quarantined.items()}
    run.row_counts = {name: table.num_rows for name, table in run.tables.items()}
    run.seconds = round(time.time() - start, 2)
    if warehouse_dir is None:
        return run

    # 8. New: give the run an id, save its tables in its own folder, and record it.
    run.run_id = next_run_id(warehouse_dir)
    folder = run_folder(run.run_id, warehouse_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for name, table in run.tables.items():
        pq.write_table(table, folder / f"{name}.parquet")
    run.findings.to_parquet(folder / "quality_findings.parquet", index=False)
    run.finding_records.to_parquet(folder / "finding_records.parquet", index=False)
    run.lineage.to_parquet(folder / "figure_lineage.parquet", index=False)
    run.lineage_steps.to_parquet(folder / "lineage_steps.parquet", index=False)

    source_rows = {name: table.num_rows for name, table in sources.items()}
    run.record = {
        "run_id": run.run_id,
        "started_at": started_at,
        "note": note,
        "settings": {"engine": engine.name, "quarantine": quarantine},
        "metric_version": METRIC_VERSION,
        "inputs": input_fingerprints(source_dir, source_rows),
        "code": code,
        "check_outcomes": run.check_outcomes,
        "findings": len(run.findings),
        "quarantined": run.quarantined_counts,
        "lineage_adds_up": lineage_adds_up,
        "seconds": run.seconds,
    }
    save_run_record(run.record, warehouse_dir)
    return run


if __name__ == "__main__":
    result = run_pipeline(sys.argv[1] if len(sys.argv) > 1 else None, note="Run by hand")
    print(f"{result.run_id} ran on the {result.engine} engine in {result.seconds} seconds")
    for table_name, count in result.row_counts.items():
        print(f"  {table_name}: {count} rows")
    for check_name, outcome in result.check_outcomes.items():
        print(f"  check {check_name}: {outcome}")
    print(f"  findings: {len(result.findings)}")
    print(f"  lineage adds up: {result.record['lineage_adds_up']}")
    print(f"Saved to {run_folder(result.run_id)}")
