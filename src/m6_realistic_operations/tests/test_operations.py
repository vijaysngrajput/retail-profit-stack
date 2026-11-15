"""LLD sections 3 to 5 and 10: late files, corrections, incremental runs, the review desk, health."""

import shutil

import pytest

from retail_profit_stack import source_data, tools
from retail_profit_stack.config import LANDING_DIR, LATE_DIR, MAPPINGS_FILE
from retail_profit_stack.ingest import ledger
from retail_profit_stack.ingest.dispatch import load_batch
from retail_profit_stack.ingest.feeds import Places
from retail_profit_stack.lineage.compare import compare_runs
from retail_profit_stack.make_history import apply_late_files, make_history
from retail_profit_stack.quality.review import decide, open_reviews, read_decisions, remove_decision
from retail_profit_stack.store import Store
from retail_profit_stack.transform.pipeline import run_pipeline


@pytest.fixture(scope="module")
def late(tmp_path_factory):
    """One build to month-end close and then the late files: places, warehouse, and RUN-0003."""
    folder = tmp_path_factory.mktemp("late")
    places = Places(
        landing=LANDING_DIR, loaded=folder / "loaded",
        state_file=folder / "state.sqlite", mappings_file=MAPPINGS_FILE,
    )  # fmt: skip
    load_batch(places=places)
    make_history(folder / "warehouse", places.loaded)
    run = apply_late_files(places, folder / "warehouse")
    return places, folder / "warehouse", run


def store_for(late, run_id=None):
    places, warehouse, _ = late
    return Store(source_dir=places.loaded, warehouse_dir=warehouse, run_id=run_id,
                 state_file=places.state_file)  # fmt: skip


# ---- The late files (LLD section 3) ----


def test_the_same_seed_gives_the_same_three_late_files(tmp_path):
    counts = source_data.write_late_files(tmp_path)
    assert sorted(counts) == [
        "product_costs_2026-10_late.csv", "refunds_2026-11-09.csv", "shipments_2026-10-19.csv",
    ]  # fmt: skip
    for file in LATE_DIR.glob("*.csv"):
        assert (tmp_path / file.name).read_bytes() == file.read_bytes(), file.name


def test_a_correction_replaces_the_earlier_version_and_nothing_loads_twice(late):
    places, _, _ = late
    assert ledger.outcome_counts(places.state_file) == {"loaded": 50, "skipped": 1, "rejected": 1}
    replaced = ledger.files_replaced(places.state_file)
    assert [item["file_name"] for item in replaced] == ["shipments_2026-10-19.csv"]
    assert len(list((places.loaded / "shipments").glob("*.parquet"))) == 9  # still nine pieces
    # Loading the late files again changes nothing.
    again = load_batch(
        places=Places(LATE_DIR, places.loaded, places.state_file, places.mappings_file)
    )
    assert {item["outcome"] for item in again} == {"already_loaded"}


# ---- Incremental runs (LLD section 4) ----


def test_the_late_run_is_incremental_and_equals_a_full_rebuild(late):
    places, _, run = late
    assert (run.run_id, run.record["mode"]) == ("RUN-0003", "incremental")
    assert run.record["months_recalculated"] == ["2026-09", "2026-10"]
    full = run_pipeline("sql", places.loaded, warehouse_dir=None)
    for name, table in run.tables.items():
        assert table.equals(full.tables[name]), name
    assert run.record["lineage_adds_up"] is True


def test_only_the_month_a_late_file_touches_is_recalculated(tmp_path):
    places = Places(LANDING_DIR, tmp_path / "loaded", tmp_path / "s.sqlite", MAPPINGS_FILE)
    load_batch(places=places)
    make_history(tmp_path / "warehouse", places.loaded)
    late_dir = tmp_path / "late"
    late_dir.mkdir()
    shutil.copy(LATE_DIR / "refunds_2026-11-09.csv", late_dir)
    run = apply_late_files(places, tmp_path / "warehouse", late_dir)
    assert (run.record["mode"], run.record["months_recalculated"]) == ("incremental", ["2026-09"])
    full = run_pipeline("sql", places.loaded, warehouse_dir=None)
    assert run.tables["monthly_product_profit"].equals(full.tables["monthly_product_profit"])


def test_a_run_with_nothing_new_recalculates_no_month_and_changes_nothing(late):
    places, warehouse, _ = late
    again = run_pipeline("sql", places.loaded, warehouse, incremental=True)
    assert (again.record["mode"], again.record["months_recalculated"]) == ("incremental", [])
    comparison = compare_runs("RUN-0003", again.run_id, warehouse)
    assert comparison["figures_changed"] == [] and comparison["files_added"] == []
    shutil.rmtree(warehouse / "runs" / again.run_id)  # leave the shared build as it was
    history = warehouse / "run_history.json"
    import json

    history.write_text(json.dumps(json.loads(history.read_text())[:-1], indent=2))


def test_a_change_of_setting_forces_a_full_run(late):
    places, _, _ = late
    run = run_pipeline("sql", places.loaded, warehouse_dir=None, quarantine=False, incremental=True)
    assert run.tables["monthly_product_profit"].num_rows == 24  # warehouse_dir=None: always full


# ---- Restatements (LLD sections 4 and 6) ----


def test_the_comparison_names_the_files_and_the_three_restated_figures(late):
    _, warehouse, _ = late
    comparison = compare_runs("RUN-0002", "RUN-0003", warehouse)
    assert comparison["files_added"] == ["product_costs_2026-10_late.csv", "refunds_2026-11-09.csv"]
    assert comparison["files_corrected"] == ["shipments_2026-10-19.csv"]
    moved = {
        (row["month"], row["product_id"]): (row["earlier"], row["later"], row["change"])
        for row in comparison["figures_changed"]
        if row["metric"] == "contribution_profit"
    }
    assert moved == {
        ("2026-09", "P012"): (3869.25, 3793.0, -76.25),
        ("2026-10", "P001"): (5156.94, 5151.94, -5.0),
        ("2026-10", "P007"): (None, 2888.69, None),
    }


def test_an_old_run_is_still_traced_from_its_own_records(late):
    """After the correction, RUN-0002 still answers from the records as they were."""
    close = store_for(late, "RUN-0002")
    now = store_for(late)
    assert (close.previous_run_id, now.previous_run_id) == ("RUN-0001", "RUN-0002")
    before = tools.query_profit("2026-10", "product", store=close).rows[0]
    after = tools.query_profit("2026-10", "product", store=now).rows[0]
    assert (before.contribution_profit, after.contribution_profit) == (5156.94, 5151.94)
    assert tools.get_evidence("2026-10", "P001", store=close).total_records == 754
    changed = tools.compare_runs("2026-10", "trail water bottle", store=now)
    assert changed.files_corrected == ["shipments_2026-10-19.csv"]
    assert tools.compare_runs("2026-10", "trail water bottle", store=close).files_added == []


def test_the_missing_cost_finding_goes_when_the_cost_arrives(late):
    now = store_for(late)
    assert tools.get_quality_flags("2026-10", store=now).confidence_level == "high"
    assert (
        tools.get_quality_flags("2026-10", store=store_for(late, "RUN-0002")).confidence_level
        == "low"
    )


# ---- The review desk (LLD section 5) ----


def a_fresh_close(folder):
    places = Places(LANDING_DIR, folder / "loaded", folder / "s.sqlite", MAPPINGS_FILE)
    load_batch(places=places)
    return places, folder / "warehouse", folder / "decisions.json"


def test_the_desk_lists_what_needs_review_and_a_missing_cost_is_not_on_it(tmp_path):
    places, warehouse, _ = a_fresh_close(tmp_path)
    run = run_pipeline("sql", places.loaded, warehouse)
    waiting = open_reviews(run.findings, run.finding_records)
    assert sorted(item["record_key"] for item in waiting) == [
        "event_out_of_order|refunds|REF-0049",
        "event_out_of_order|shipments|" + waiting_shipment(waiting),
        "refund_exceeds_line|refunds|REF-0002",
    ]


def waiting_shipment(waiting) -> str:
    return next(
        item["record"]["shipment_id"] for item in waiting if "shipment_id" in item["record"]
    )


def test_accept_keeps_the_record_and_stops_it_lowering_confidence(tmp_path):
    places, warehouse, decisions = a_fresh_close(tmp_path)
    before = run_pipeline("sql", places.loaded, warehouse, decisions_file=decisions)
    decide(
        decisions, "refund_exceeds_line|refunds|REF-0002", "accept", "Vijay", "A goodwill refund"
    )
    after = run_pipeline(
        "sql", places.loaded, warehouse, decisions_file=decisions, incremental=True
    )
    assert after.record["mode"] == "full"  # a new decision means everything is checked again
    assert after.tables["monthly_product_profit"].equals(before.tables["monthly_product_profit"])
    finding = after.findings[after.findings["check_name"] == "refund_exceeds_line"].iloc[0]
    assert (finding["outcome"], finding["severity"]) == ("reviewed", "low")
    assert "Reviewed by Vijay" in finding["description"]
    store = Store(source_dir=places.loaded, warehouse_dir=warehouse, state_file=places.state_file)
    assert tools.get_quality_flags("2026-09", "sun hat", store=store).confidence_level == "high"


def test_exclude_sets_the_record_aside_and_the_figure_moves(tmp_path):
    places, warehouse, decisions = a_fresh_close(tmp_path)
    run_pipeline("sql", places.loaded, warehouse, decisions_file=decisions)
    decide(decisions, "refund_exceeds_line|refunds|REF-0002", "exclude", "Vijay", "Typed wrongly")
    after = run_pipeline("sql", places.loaded, warehouse, decisions_file=decisions)
    assert after.quarantined_counts["refunds"] == 2  # the duplicate, and the excluded refund
    moved = [row for row in compare_runs("RUN-0001", "RUN-0002", warehouse)["figures_changed"]
             if row["metric"] == "net_sales"]  # fmt: skip
    assert [(row["product_id"], row["change"]) for row in moved] == [("P011", 60.0)]
    finding = after.findings[after.findings["check_name"] == "refund_exceeds_line"].iloc[0]
    assert finding["outcome"] == "quarantine" and "Set aside by Vijay" in finding["description"]
    assert after.record["lineage_adds_up"] is True


def test_a_decision_can_be_taken_back_and_a_bad_one_is_refused(tmp_path):
    file = tmp_path / "decisions.json"
    decide(file, "k", "accept", "Vijay")
    assert read_decisions(file)["k"]["person"] == "Vijay"
    remove_decision(file, "k")
    assert read_decisions(file) == {}
    with pytest.raises(ValueError, match="accept, exclude"):
        decide(file, "k", "delete", "Vijay")


# ---- A rejected file that was never replaced (LLD section 5) ----


def test_a_rejected_file_never_replaced_lowers_confidence_and_is_named(tmp_path):
    landing = tmp_path / "landing"
    shutil.copytree(LANDING_DIR, landing)
    (landing / "refunds_2026-10-12_complete.csv").unlink()  # the complete file never arrives
    places = Places(landing, tmp_path / "loaded", tmp_path / "s.sqlite", MAPPINGS_FILE)
    load_batch(places=places)
    run_pipeline("sql", places.loaded, tmp_path / "warehouse")
    store = Store(source_dir=places.loaded, warehouse_dir=tmp_path / "warehouse",
                  state_file=places.state_file)  # fmt: skip
    result = tools.get_quality_flags("2026-10", "headlamp", store=store)
    assert result.files_missing == ["refunds_2026-10-12.csv"] and result.confidence_level == "low"
    assert tools.get_quality_flags("2026-09", store=store).files_missing == []


def test_at_close_the_replaced_file_is_not_reported_missing(late):
    assert tools.get_quality_flags("2026-10", store=store_for(late, "RUN-0002")).files_missing == []


# ---- Run health (LLD section 10) ----


def test_every_run_records_its_steps_and_its_warnings(late):
    health = late[2].record["health"]
    assert [step["step"] for step in health["steps"]] == [
        "load the records", "check the records", "set records aside", "calculate",
        "write the findings", "build and prove the lineage", "save the run",
    ]  # fmt: skip
    assert all(step["seconds"] >= 0 and step["rows"] >= 0 for step in health["steps"])
    assert health["warnings"] == ["3 findings are waiting at the review desk."]


def test_a_question_about_one_product_names_only_the_files_that_affected_it(late):
    now = store_for(late)
    bottle = tools.compare_runs("2026-10", "trail water bottle", store=now)
    assert (bottle.files_added, bottle.files_corrected) == ([], ["shipments_2026-10-19.csv"])
    assert bottle.records_changed[0]["changed"] == 1
    pullover = tools.compare_runs("2026-09", "fleece pullover", store=now)
    assert (pullover.files_added, pullover.files_corrected) == (["refunds_2026-11-09.csv"], [])
    stove = tools.compare_runs("2026-10", "camp stove", store=now)
    assert stove.files_added == ["product_costs_2026-10_late.csv"]
    assert len(tools.compare_runs(store=now).files_added) == 2  # with no scope, every file
