"""The pipeline: load the records, check them, calculate the figures, and remember the run.

Implements LLD section 2 (One pipeline run, step by step). Milestone 3's checks and
milestone 2's transformations are unchanged. New in milestone 4: every run gets an id, its own
folder of tables, lineage, and one entry in the run history. Nothing is overwritten.

Run it with:  uv run python -m retail_profit_stack.transform.pipeline [sql|pandas]
"""

import hashlib
import json
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
    read_history,
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
from retail_profit_stack.quality.review import add_decisions, read_decisions
from retail_profit_stack.transform.contracts import TableSchema, conform
from retail_profit_stack.transform.engines import Engine, get_engine
from retail_profit_stack.transform.engines.base import IMPLEMENTATIONS_DIR
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS, ordered_specs, schema_for


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


# ---- New in milestone 6: recalculating only the months that changed (LLD section 4) ----

# The column that says which month a record counts in. Order lines go with their order.
MONTH_FROM = {
    "orders": "order_date",
    "refunds": "refund_date",
    "shipments": "ship_date",
    "payment_fees": "capture_date",
    "product_costs": "month",
}


def months_of(table: pa.Table, name: str, order_months: dict[str, str]) -> list[str]:
    """The month each row of a source table counts in, as text like 2026-10."""
    if name == "order_items":
        return [order_months.get(order_id, "") for order_id in table.column("order_id").to_pylist()]
    values = table.column(MONTH_FROM[name]).to_pylist()
    return [value if isinstance(value, str) else value.strftime("%Y-%m") for value in values]


def affected_months(
    previous: dict, inputs: dict, settings: dict, code: dict, decisions_print: str,
    sources: dict[str, pa.Table], source_dir: Path,
) -> list[str] | None:  # fmt: skip
    """The months that changed files touch, or None when everything must be recalculated.

    Everything is recalculated when the settings, the code, or the desk's decisions changed,
    when a file went away, or when the product list changed.
    """
    same_rules = (
        previous["settings"] == settings
        and previous["code"] == code
        and previous.get("decisions", "") == decisions_print
    )
    if not same_rules:
        return None
    order_months = dict(
        zip(
            sources["orders"].column("order_id").to_pylist(),
            months_of(sources["orders"], "orders", {}),
            strict=True,
        )
    )
    months: set[str] = set()
    for name, now in inputs.items():
        before = previous["inputs"][name].get("pieces")
        if before is None or set(before) - set(now["pieces"]):
            return None  # an older run with no list of files, or a file that went away
        changed = [piece for piece, print_ in now["pieces"].items() if before.get(piece) != print_]
        if changed and name == "products":
            return None
        for piece in changed:
            table = pq.read_table(source_dir / name / piece)
            months.update(months_of(table, name, order_months))
    return sorted(month for month in months if month)


def rows_for_months(tables: dict[str, pa.Table], months: list[str]) -> dict[str, pa.Table]:
    """The same source tables, keeping only the rows that count in the given months."""
    order_months = dict(
        zip(
            tables["orders"].column("order_id").to_pylist(),
            months_of(tables["orders"], "orders", {}),
            strict=True,
        )
    )
    kept = {}
    for name, table in tables.items():
        if name == "products":
            kept[name] = table
            continue
        wanted = [month in months for month in months_of(table, name, order_months)]
        kept[name] = table.filter(pa.array(wanted, type=pa.bool_()))
    return kept


def merge_months(
    recalculated: dict[str, pa.Table], previous_folder: Path, months: list[str]
) -> dict[str, pa.Table]:
    """Put the recalculated months together with every other month from the run before."""
    merged = {}
    for name, new_rows in recalculated.items():
        old = pq.read_table(previous_folder / f"{name}.parquet")
        untouched = [month not in months for month in old.column("month").to_pylist()]
        old_rows = old.filter(pa.array(untouched, type=pa.bool_()))
        merged[name] = conform(pa.concat_tables([old_rows, new_rows]), schema_for(name))
    return merged


def run_pipeline(
    engine_name: str | None = None,
    source_dir: Path = SOURCE_DIR,
    warehouse_dir: Path | None = WAREHOUSE_DIR,
    quarantine: bool = True,
    note: str = "",
    incremental: bool = False,
    decisions_file: Path | None = None,
) -> PipelineRun:
    """Calculate every table, and save the run. Pass warehouse_dir=None to save nothing.

    quarantine=False counts every record, the way the business calculated before milestone 3.
    note is one sentence saying why the run was made.
    New in milestone 6: incremental=True recalculates only the months that changed files
    touch, and decisions_file holds what people decided at the review desk.
    """
    start = time.time()
    started_at = datetime.now().isoformat(timespec="seconds")
    engine = get_engine(engine_name)
    run = PipelineRun(engine=engine.name)
    steps: list[dict] = []  # run health: one line per step

    def done(step: str, rows: int, since: float) -> float:
        """Note that a step finished: its name, how long it took, and how many rows it handled."""
        steps.append({"step": step, "seconds": round(time.time() - since, 3), "rows": rows})
        return time.time()

    clock = time.time()
    # 1. Load the source tables and number their rows.
    sources = number_rows(load_sources(source_dir))
    source_rows = {name: table.num_rows for name, table in sources.items()}
    clock = done("load the records", sum(source_rows.values()), clock)

    # 2. Run the four record checks, and attach what people decided at the review desk.
    decisions = read_decisions(decisions_file)
    bad_records = add_decisions(run_record_checks(sources), sources, decisions)
    clock = done("check the records", len(bad_records), clock)

    # 3. Set the quarantined rows aside. With quarantine off, every row is kept.
    if quarantine:
        kept_numbered, quarantined = split_records(sources, bad_records, keep_row_numbers=True)
    else:
        kept_numbered, quarantined = sources, {}
    kept = without_row_numbers(kept_numbered)
    run.quarantined_counts = {name: table.num_rows for name, table in quarantined.items()}
    clock = done("set records aside", sum(run.quarantined_counts.values()), clock)

    # 4. Calculate the figures from the kept rows: every month, or only the months that changed.
    files = code_files(engine.name)
    code = code_fingerprints(files)
    settings = {"engine": engine.name, "quarantine": quarantine}
    inputs = input_fingerprints(source_dir, source_rows)
    decisions_print = hashlib.sha256(json.dumps(decisions, sort_keys=True).encode()).hexdigest()[
        :12
    ]
    months = None
    history = read_history(warehouse_dir) if warehouse_dir is not None else []
    if incremental and history and warehouse_dir is not None:
        months = affected_months(
            history[-1], inputs, settings, code, decisions_print, sources, source_dir
        )
    if months is None or warehouse_dir is None:
        months = None
        run.tables = run_transformations(engine, kept)
    else:
        recalculated = run_transformations(engine, rows_for_months(kept, months))
        previous_folder = run_folder(history[-1]["run_id"], warehouse_dir)
        run.tables = merge_months(recalculated, previous_folder, months)
    profit = run.tables["monthly_product_profit"]
    clock = done("calculate", profit.num_rows, clock)

    # 5. Check that the profit table adds up to the kept rows.
    totals_problems = run_totals_check(kept, profit)
    bad_records = pd.concat([bad_records, totals_problems], ignore_index=True)
    for column in ("record_key", "decision", "decided_by"):
        bad_records[column] = bad_records[column].fillna("")
    # 6. Group the bad records into findings.
    run.findings, run.finding_records = make_findings(bad_records, sources, quarantine)
    clock = done("write the findings", len(run.findings), clock)

    # 7. Build the lineage, and prove that it adds up to the profit table.
    run.lineage = build_lineage(kept_numbered)
    run.lineage_steps = lineage_steps(code)
    lineage_adds_up = lineage_differences(run.lineage, profit.to_pandas()).empty
    clock = done("build and prove the lineage", len(run.lineage), clock)

    run.check_outcomes = check_outcomes(bad_records)
    if not quarantine:
        # Nothing was set aside, so a check that would quarantine only needs review.
        for check_name, outcome in run.check_outcomes.items():
            if outcome == "quarantine":
                run.check_outcomes[check_name] = "needs_review"
    run.row_counts = {name: table.num_rows for name, table in run.tables.items()}
    run.seconds = round(time.time() - start, 2)
    if warehouse_dir is None:
        return run

    # 8. Give the run an id, save its tables in its own folder, and record it.
    run.run_id = next_run_id(warehouse_dir)
    folder = run_folder(run.run_id, warehouse_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for name, table in run.tables.items():
        pq.write_table(table, folder / f"{name}.parquet")
    # New in milestone 6: the run keeps the records it used, so it can still be traced
    # after a later correction changes them.
    for name, table in without_row_numbers(sources).items():
        (folder / "sources" / name).mkdir(parents=True, exist_ok=True)
        pq.write_table(table, folder / "sources" / name / "all.parquet")
    run.findings.to_parquet(folder / "quality_findings.parquet", index=False)
    run.finding_records.to_parquet(folder / "finding_records.parquet", index=False)
    run.lineage.to_parquet(folder / "figure_lineage.parquet", index=False)
    run.lineage_steps.to_parquet(folder / "lineage_steps.parquet", index=False)
    done("save the run", len(run.tables) + 4 + len(sources), clock)

    needs_review = run.findings["outcome"].tolist().count("needs_review")
    warnings = []
    if not lineage_adds_up:
        warnings.append("The lineage does not add up to the profit table.")
    if len(totals_problems):
        warnings.append("The profit table does not match the kept records.")
    if needs_review:
        warnings.append(f"{needs_review} findings are waiting at the review desk.")
    run.record = {
        "run_id": run.run_id,
        "started_at": started_at,
        "note": note,
        "settings": settings,
        "metric_version": METRIC_VERSION,
        "inputs": inputs,
        "code": code,
        "check_outcomes": run.check_outcomes,
        "findings": len(run.findings),
        "quarantined": run.quarantined_counts,
        "lineage_adds_up": lineage_adds_up,
        "seconds": run.seconds,
        # New in milestone 6.
        "mode": "full" if months is None else "incremental",
        "months_recalculated": months
        if months is not None
        else sorted(set(profit.column("month").to_pylist())),
        "decisions": decisions_print,
        "health": {"steps": steps, "warnings": warnings},
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
