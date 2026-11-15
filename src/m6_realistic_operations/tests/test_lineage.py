"""LLD sections 3 to 6: run records, lineage, comparing runs, and the tools that read them."""

import shutil

import pandas as pd
import pytest

from retail_profit_stack import tools
from retail_profit_stack.config import LANDING_DIR, MAPPINGS_FILE, WAREHOUSE_DIR
from retail_profit_stack.ingest.dispatch import load_batch
from retail_profit_stack.ingest.feeds import Places
from retail_profit_stack.lineage.compare import compare_runs
from retail_profit_stack.lineage.lineage import (
    METRIC_TERMS,
    RECORD_TERMS,
    lineage_differences,
    record_counts,
)
from retail_profit_stack.lineage.runs import (
    fingerprint,
    next_run_id,
    read_history,
    run_folder,
)
from retail_profit_stack.make_history import make_history
from retail_profit_stack.store import Store
from retail_profit_stack.transform.pipeline import run_pipeline


def read(run_id, table, warehouse_dir=WAREHOUSE_DIR):
    return pd.read_parquet(run_folder(run_id, warehouse_dir) / f"{table}.parquet")


# ---- Run records (LLD section 3) ----


def test_fingerprint_is_the_same_for_the_same_content_and_changes_with_one_character(tmp_path):
    (tmp_path / "a.csv").write_text("id,amount\n1,10.00\n")
    (tmp_path / "copy.csv").write_text("id,amount\n1,10.00\n")
    (tmp_path / "changed.csv").write_text("id,amount\n1,10.01\n")
    assert fingerprint(tmp_path / "a.csv") == fingerprint(tmp_path / "copy.csv")
    assert fingerprint(tmp_path / "a.csv") != fingerprint(tmp_path / "changed.csv")
    assert len(fingerprint(tmp_path / "a.csv")) == 12


def test_run_ids_count_up_and_a_later_run_leaves_an_earlier_one_untouched(tmp_path):
    assert next_run_id(tmp_path) == "RUN-0001"
    first = run_pipeline("sql", warehouse_dir=tmp_path)
    saved = (run_folder("RUN-0001", tmp_path) / "monthly_product_profit.parquet").read_bytes()
    second = run_pipeline("sql", warehouse_dir=tmp_path, quarantine=False)
    assert (first.run_id, second.run_id) == ("RUN-0001", "RUN-0002")
    assert [record["run_id"] for record in read_history(tmp_path)] == ["RUN-0001", "RUN-0002"]
    still = (run_folder("RUN-0001", tmp_path) / "monthly_product_profit.parquet").read_bytes()
    assert still == saved


def test_the_run_record_has_every_field(calculated_tables):
    record = calculated_tables.record
    assert set(record) == {
        "run_id", "started_at", "note", "settings", "metric_version", "inputs", "code",
        "check_outcomes", "findings", "quarantined", "lineage_adds_up", "seconds",
        "mode", "months_recalculated", "decisions", "health",  # new in milestone 6
    }  # fmt: skip
    assert record["settings"] == {"engine": "sql", "quarantine": True}
    assert record["inputs"]["order_items"]["rows"] == 2549
    assert len(record["code"]) == 11  # six transformations and five checks
    assert record["lineage_adds_up"] is True


def test_two_runs_with_nothing_changed_differ_only_in_id_and_time(tmp_path):
    first = run_pipeline("sql", warehouse_dir=tmp_path).record
    second = run_pipeline("sql", warehouse_dir=tmp_path).record
    varies = {"run_id", "started_at", "seconds", "health"}  # health holds each step's time
    assert {key for key in first if first[key] != second[key]} <= varies
    comparison = compare_runs("RUN-0001", "RUN-0002", tmp_path)
    for part in ("settings_changed", "inputs_changed", "code_changed", "figures_changed"):
        assert comparison[part] == [], part


# ---- Lineage (LLD section 4) ----


def test_lineage_adds_up_to_every_figure(calculated_tables):
    profit = calculated_tables.tables["monthly_product_profit"].to_pandas()
    assert lineage_differences(calculated_tables.lineage, profit).empty


def test_the_proof_catches_a_removed_row_and_a_changed_amount(calculated_tables):
    profit = calculated_tables.tables["monthly_product_profit"].to_pandas()
    lineage = calculated_tables.lineage
    removed = lineage_differences(lineage.iloc[1:], profit)
    assert len(removed) == 1
    changed = lineage.copy()
    changed.loc[100, "amount"] += 5.0
    found = lineage_differences(changed, profit)
    assert len(found) == 1 and found["term"].iloc[0] == changed.loc[100, "term"]


def test_the_trail_water_bottle_in_october_has_754_records(calculated_tables):
    counts = record_counts(calculated_tables.lineage, "2026-10", "P001")
    assert counts == {
        "order_items": 250, "payment_fees": 250, "product_costs": 1, "refunds": 3,
        "shipments": 250,
    }  # fmt: skip


def test_no_quarantined_record_is_in_the_lineage(calculated_tables):
    records = calculated_tables.finding_records
    set_aside = records[records["quarantined"]]
    in_lineage = set(zip(calculated_tables.lineage["source_table"],
                         calculated_tables.lineage["row_number"], strict=True))  # fmt: skip
    for row in set_aside.to_dict(orient="records"):
        assert (row["source_table"], row["row_number"]) not in in_lineage


def test_metric_terms_rebuild_each_metric_from_its_terms(calculated_tables):
    profit = calculated_tables.tables["monthly_product_profit"].to_pandas()
    for metric, terms in METRIC_TERMS.items():
        rebuilt = sum(profit[term] * sign for term, sign in terms.items())
        assert ((rebuilt - profit[metric]).abs().fillna(0) < 0.005).all(), metric
    assert len(RECORD_TERMS) == 9


def test_lineage_steps_name_each_transformation_and_its_inputs(calculated_tables):
    steps = calculated_tables.lineage_steps
    sales = steps[steps["output_table"] == "sales"]
    assert set(sales["input_table"]) == {"orders", "order_items"}
    assert all(len(code) == 12 for code in steps["code_fingerprint"])


# ---- Comparing runs (LLD section 5) ----


def test_the_two_starting_runs_differ_by_one_setting_and_three_figures():
    comparison = compare_runs("RUN-0001", "RUN-0002")
    assert comparison["settings_changed"] == [
        {"name": "quarantine", "earlier": False, "later": True}
    ]
    assert comparison["inputs_changed"] == [] and comparison["code_changed"] == []
    moved = {
        (row["month"], row["product_id"]): (row["earlier"], row["later"], row["change"])
        for row in comparison["figures_changed"]
        if row["metric"] == "contribution_profit"
    }
    assert moved == {
        ("2026-09", "P005"): (2592.24, 2926.24, 334.0),
        ("2026-10", "P001"): (5188.2, 5156.94, -31.26),
        ("2026-10", "P002"): (2638.14, 2541.35, -96.79),
    }
    assert sum(row["only_in_earlier"] for row in comparison["records_changed"]) == 22
    assert sum(row["only_in_later"] for row in comparison["records_changed"]) == 0


def test_a_run_compared_with_itself_has_no_changes():
    comparison = compare_runs("RUN-0002", "RUN-0002")
    assert comparison["figures_changed"] == [] and comparison["records_changed"] == []


def test_adding_the_missing_cost_changes_one_input_and_makes_the_profit_available(tmp_path):
    # Changed in milestone 5: the cost arrives as one more file, and the loader loads it.
    places = Places(
        landing=tmp_path / "landing", loaded=tmp_path / "loaded",
        state_file=tmp_path / "state.sqlite", mappings_file=MAPPINGS_FILE,
    )  # fmt: skip
    shutil.copytree(LANDING_DIR, places.landing)
    load_batch(places=places)
    run_pipeline("sql", places.loaded, tmp_path / "warehouse")
    late_file = places.landing / "product_costs_2026-10_late.csv"
    late_file.write_text("product_id,month,unit_cost\nP007,2026-10,44.00\n", encoding="utf-8")
    assert load_batch(["product_costs_2026-10_late.csv"], places=places)[0]["outcome"] == "loaded"
    run_pipeline("sql", places.loaded, tmp_path / "warehouse")
    comparison = compare_runs("RUN-0001", "RUN-0002", tmp_path / "warehouse")
    assert [row["name"] for row in comparison["inputs_changed"]] == ["product_costs"]
    assert comparison["settings_changed"] == []
    stove = [row for row in comparison["figures_changed"] if row["metric"] == "contribution_profit"]
    assert len(stove) == 1 and stove[0]["product_id"] == "P007"
    assert stove[0]["earlier"] is None and stove[0]["later"] is not None
    assert stove[0]["change"] is None  # unavailable to available has no amount
    assert comparison["checks_changed"] == [
        {"name": "missing_product_cost", "earlier": "needs_review", "later": "pass"}
    ]


def test_make_history_starts_again_from_nothing(tmp_path):
    make_history(tmp_path)
    runs = make_history(tmp_path)
    assert [run.run_id for run in runs] == ["RUN-0001", "RUN-0002"]
    assert len(read_history(tmp_path)) == 2
    earlier = read("RUN-0001", "quality_findings", tmp_path)
    assert set(earlier["outcome"]) == {"needs_review"}  # nothing was set aside in the first run


# ---- The store and the tools (LLD section 6) ----


def test_the_store_reads_the_latest_run_or_a_named_one():
    assert Store().run_id == "RUN-0002"
    earlier = Store(run_id="RUN-0001")
    rows = tools.query_profit("2026-10", "product", store=earlier).rows
    bottle = next(row for row in rows if row.entity_id == "P001")
    assert bottle.contribution_profit == 5188.20


def test_results_name_their_run():
    assert tools.query_profit("2026-10", "product").run_id == "RUN-0002"
    assert tools.compare_profit("2026-10", "2026-09", "category").run_id == "RUN-0002"
    assert tools.get_quality_flags("2026-10").run_id == "RUN-0002"


def test_evidence_reports_every_record_the_run_and_the_steps():
    evidence = tools.get_evidence("2026-10", "trail water bottle")
    assert evidence.run_id == "RUN-0002"
    assert evidence.total_records == 754 == sum(evidence.record_counts.values())
    assert evidence.set_aside_count == 9
    assert evidence.steps[0] == "sales is made from orders and order_items"
    assert len(evidence.records) == 5 and evidence.is_sample


def test_compare_runs_for_one_figure():
    result = tools.compare_runs("2026-10", "trail water bottle")
    assert (result.earlier_run, result.later_run, result.run_id) == (
        "RUN-0001", "RUN-0002", "RUN-0002",
    )  # fmt: skip
    figure = result.figures_changed[0]
    assert (figure.earlier, figure.later, figure.change) == (5188.2, 5156.94, -31.26)
    assert {row["source_table"] for row in result.records_changed} == {
        "order_items", "payment_fees", "shipments",
    }  # fmt: skip
    assert {row["finding_id"] for row in result.findings} == {"QF-002"}


def test_compare_runs_for_everything_and_for_a_figure_that_did_not_change():
    everything = tools.compare_runs()
    assert [figure.product_id for figure in everything.figures_changed] == ["P005", "P001", "P002"]
    assert everything.figures_unchanged == []
    sun_hat = tools.compare_runs("2026-09", "sun hat", "net_sales")
    assert sun_hat.figures_changed == []
    unchanged = sun_hat.figures_unchanged[0]
    assert (unchanged.earlier, unchanged.later, unchanged.change) == (5140.0, 5140.0, 0.0)


def test_compare_runs_with_one_run_gives_an_error_sentence(tmp_path):
    run_pipeline("sql", warehouse_dir=tmp_path)
    with pytest.raises(tools.ToolInputError, match="only one pipeline run"):
        tools.compare_runs(store=Store(warehouse_dir=tmp_path))
