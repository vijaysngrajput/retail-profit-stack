"""LLD sections 3 to 8: the files, the rules, the load record, mappings, workflow, dispatcher."""

import json
import shutil
import time

import pytest
from langchain_core.messages import AIMessage

from retail_profit_stack import source_data
from retail_profit_stack.config import LANDING_DIR, MAPPINGS_FILE
from retail_profit_stack.ingest import ledger
from retail_profit_stack.ingest.dispatch import build_dispatcher, clear_loaded, load_batch
from retail_profit_stack.ingest.feeds import Places, expected_columns, feed_of, piece_path
from retail_profit_stack.ingest.mapping import (
    ColumnGuess,
    MappingSuggestion,
    load_mapping_cases,
    mapping_problem,
    read_approved_mappings,
    read_file,
    save_approved_mapping,
    score_suggestions,
)
from retail_profit_stack.ingest.rules import inspect_file
from retail_profit_stack.ingest.workflow import (
    answer,
    build_file_workflow,
    run_file,
    waiting_files,
)
from retail_profit_stack.transform.contracts import ContractError
from retail_profit_stack.transform.pipeline import load_sources


def places_in(folder, approved=True) -> Places:
    """A loader's own folders inside a test folder, with a copy of the landing files."""
    places = Places(
        landing=folder / "landing", loaded=folder / "loaded",
        state_file=folder / "state.sqlite", mappings_file=folder / "mappings.json",
    )  # fmt: skip
    shutil.copytree(LANDING_DIR, places.landing)
    if approved:
        shutil.copy(MAPPINGS_FILE, places.mappings_file)
    return places


class FakeMappingModel:
    """A model that suggests the planted truth for every file, with no network."""

    def __init__(self, wrong=False):
        self.wrong = wrong
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        prompt = messages[1][1]
        truth = next(
            mapping for name, mapping in load_mapping_cases().items() if f"({name})" in prompt
        )
        guesses = [
            ColumnGuess(file_column=column, expected_column=target, reason="by its values")
            for column, target in truth.items()
        ]
        if self.wrong:
            guesses = guesses[:1]
        suggestion = MappingSuggestion(columns=guesses, confidence="high")
        raw = AIMessage(content="", response_metadata={"token_usage": {"cost": 0.001}})
        return {"raw": raw, "parsed": suggestion}


def tables_as_text(loaded_dir) -> dict[str, list[str]]:
    return {
        name: [str(row) for row in table.to_pylist()]
        for name, table in load_sources(loaded_dir).items()
    }


# ---- The files (LLD section 3) ----


def test_the_same_seed_gives_the_same_fifty_files(tmp_path):
    counts = source_data.write_landing_files(tmp_path)
    assert len(counts) == 50
    for file in sorted(LANDING_DIR.glob("*.csv")):
        assert (tmp_path / file.name).read_bytes() == file.read_bytes(), file.name


def test_each_file_belongs_to_one_feed():
    assert feed_of("order_items_2026-10-12.csv") == "order_items"
    assert feed_of("orders_2026-09-14_resend.csv") == "orders"
    with pytest.raises(ValueError, match="does not belong"):
        feed_of("invoices_2026-10.csv")


# ---- The rules (LLD section 4) ----


def write(folder, name, text):
    file = folder / name
    file.write_text(text, encoding="utf-8")
    return file


EXPECTED = ["fee_id", "order_item_id", "product_id", "capture_date", "fee_amount"]
ROW = "FEE-1,OI-1,P001,2026-10-01,1.14\n"


@pytest.mark.parametrize(
    ("header", "approved", "rule", "outcome"),
    [
        ("fee_id,order_item_id,product_id,capture_date,fee_amount", [], 2, "load"),
        ("fee_amount,capture_date,product_id,order_item_id,fee_id", [], 2, "load"),
        ("fee_id,order_item_id,product_id,capture_date,fee_amount,bank", [], 3, "load"),
        ("fee_id,order_item_id,product_id,capture_date", [], 4, "rejected"),
        ("fee_id,order_item_id,product_id,capture_date,fee_usd", [{"fee_usd": "fee_amount"}], 5,
         "load"),
        ("fee_id,order_item_id,product_id,capture_date,fee_usd", [], 6, "needs_mapping"),
        ("fee_id,order_item_id,product_id,capture_date,fee_usd", [{"fee": "fee_amount"}], 6,
         "needs_mapping"),
    ],
)  # fmt: skip
def test_each_rule(tmp_path, header, approved, rule, outcome):
    file = write(tmp_path, "payment_fees_x.csv", header + "\n" + ROW)
    found = inspect_file(file, EXPECTED, {}, approved)
    assert (found.rule, found.outcome) == (rule, outcome), found.reason


def test_rule_one_and_rule_seven(tmp_path):
    file = write(tmp_path, "payment_fees_x.csv", ",".join(EXPECTED) + "\n" + ROW)
    found = inspect_file(file, EXPECTED, {}, [])
    again = inspect_file(file, EXPECTED, {found.fingerprint: "payment_fees_x.csv"}, [])
    assert (again.rule, again.outcome) == (1, "already_loaded")
    resent = inspect_file(file, EXPECTED, {found.fingerprint: "another_name.csv"}, [])
    assert (resent.rule, resent.outcome) == (1, "skipped")
    changed = inspect_file(file, EXPECTED, {}, [], {"payment_fees_x.csv": "an-older-print"})
    assert (changed.rule, changed.outcome) == (7, "rejected")


# ---- The load record (LLD section 5) ----


def test_a_fingerprint_can_be_claimed_only_once(tmp_path):
    state = tmp_path / "state.sqlite"
    assert ledger.claim_content(state, "abc", "first.csv") == "first.csv"
    assert ledger.claim_content(state, "abc", "second.csv") == "first.csv"
    assert ledger.claim_content(state, "abc", "first.csv") == "first.csv"  # safe to repeat
    assert ledger.loaded_fingerprints(state) == {"abc": "first.csv"}


# ---- Mappings (LLD section 6) ----


def test_a_mapping_renames_columns_and_extras_are_dropped():
    table = read_file(
        LANDING_DIR / "shipments_2026-10-26.csv", "shipments",
        {"cost_1": "pick_pack_cost", "cost_2": "carrier_cost"},
    )  # fmt: skip
    assert table.column_names == expected_columns("shipments")
    assert table.column("pick_pack_cost")[0].as_py() == 2.5


def test_values_that_do_not_fit_are_refused(tmp_path):
    file = write(
        tmp_path, "payment_fees_x.csv", ",".join(EXPECTED) + "\nFEE-1,OI-1,P001,2026-10-01,lots\n"
    )
    with pytest.raises((ContractError, Exception), match="fee_amount|lots|convert"):
        read_file(file, "payment_fees")


def test_an_approved_mapping_is_saved_once_and_checked_by_code(tmp_path):
    file = tmp_path / "mappings.json"
    save_approved_mapping(file, "payment_fees", {"fee_usd": "fee_amount"})
    save_approved_mapping(file, "payment_fees", {"fee_usd": "fee_amount"})
    assert read_approved_mappings(file) == {"payment_fees": [{"fee_usd": "fee_amount"}]}
    assert (
        mapping_problem({"fee_usd": "fee_amount"}, "payment_fees", ["fee_amount"], ["fee_usd"])
        is None
    )
    assert "not an expected column" in mapping_problem(
        {"fee_usd": "fee"}, "payment_fees", ["fee_amount"], ["fee_usd"]
    )
    assert "nothing is mapped" in mapping_problem({}, "payment_fees", ["fee_amount"], ["fee_usd"])


def test_suggestions_are_scored_against_the_planted_truth():
    truth = load_mapping_cases()
    assert len(truth) == 6
    suggested = dict(truth)
    suggested["shipments_2026-10-26.csv"] = {"cost_1": "carrier_cost", "cost_2": "pick_pack_cost"}
    del suggested["payment_fees_2026-10-26.csv"]
    scores = score_suggestions(suggested)
    assert scores["result"].value_counts().to_dict() == {"right": 4, "wrong": 1, "not given": 1}


# ---- The file workflow (LLD section 7) ----


def test_a_clean_file_loads_without_pausing(tmp_path):
    places = places_in(tmp_path, approved=False)
    result = run_file(build_file_workflow(places), "orders_2026-09-14.csv")
    assert (result["outcome"], result["rows_loaded"] > 0) == ("loaded", True)
    assert piece_path(places, "orders_2026-09-14.csv").exists()


def test_a_renamed_file_waits_and_loads_only_after_approval(tmp_path):
    places = places_in(tmp_path, approved=False)
    model = FakeMappingModel()
    workflow = build_file_workflow(places, model)
    name = "order_items_2026-10-12.csv"
    result = run_file(workflow, name)
    assert result["outcome"] == "waiting" and result["model_cost"] == 0.001
    assert not piece_path(places, name).exists()  # nothing is loaded before approval
    question = waiting_files(workflow, places)[0]
    assert question["suggested_mapping"] == load_mapping_cases()[name]
    done = answer(workflow, name, approved=True, person="Vijay")
    assert done["outcome"] == "loaded" and piece_path(places, name).exists()
    seen = {entry["file_name"]: entry for entry in ledger.files_seen(places.state_file)}
    assert (seen[name]["approved_by"], seen[name]["mapping"]) == (
        "Vijay",
        load_mapping_cases()[name],
    )
    # The mapping was saved, so the next file from this feed loads without asking.
    assert run_file(workflow, "order_items_2026-10-19.csv")["outcome"] == "loaded"
    assert model.calls == 1


def test_a_refused_mapping_and_an_unusable_mapping_reject_the_file(tmp_path):
    places = places_in(tmp_path, approved=False)
    workflow = build_file_workflow(places, FakeMappingModel(wrong=True))
    run_file(workflow, "payment_fees_2026-10-19.csv")
    refused = answer(workflow, "payment_fees_2026-10-19.csv", approved=False, person="Vijay")
    assert refused["outcome"] == "rejected" and "refused" in refused["reason"]
    run_file(workflow, "order_items_2026-10-12.csv")  # the fake suggests only one of two columns
    unusable = answer(workflow, "order_items_2026-10-12.csv", approved=True, person="Vijay")
    assert unusable["outcome"] == "rejected" and "nothing is mapped" in unusable["reason"]
    assert not (places.loaded / "order_items").exists()


def test_a_person_can_correct_the_mapping_when_approving(tmp_path):
    places = places_in(tmp_path, approved=False)
    workflow = build_file_workflow(places)  # no model: no suggestion
    name = "shipments_2026-10-26.csv"
    assert run_file(workflow, name)["outcome"] == "waiting"
    done = answer(
        workflow, name, True, "Vijay", {"cost_1": "pick_pack_cost", "cost_2": "carrier_cost"}
    )
    assert done["outcome"] == "loaded"


def test_a_waiting_file_survives_a_restart(tmp_path):
    places = places_in(tmp_path, approved=False)
    name = "payment_fees_2026-10-19.csv"
    run_file(build_file_workflow(places, FakeMappingModel()), name)
    # A new workflow on the same SQLite file stands for a new program after a crash.
    after_restart = build_file_workflow(places)
    assert [question["file_name"] for question in waiting_files(after_restart, places)] == [name]
    assert answer(after_restart, name, True, "Vijay")["outcome"] == "loaded"


def test_loading_a_file_again_changes_nothing(tmp_path):
    places = places_in(tmp_path)
    workflow = build_file_workflow(places)
    first = run_file(workflow, "orders_2026-09-14.csv")
    piece = piece_path(places, "orders_2026-09-14.csv").read_bytes()
    again = run_file(workflow, "orders_2026-09-14.csv")
    resent = run_file(workflow, "orders_2026-09-14_resend.csv")
    assert (first["outcome"], again["outcome"], resent["outcome"]) == (
        "loaded", "already_loaded", "skipped",
    )  # fmt: skip
    assert piece_path(places, "orders_2026-09-14.csv").read_bytes() == piece
    assert len(list((places.loaded / "orders").glob("*.parquet"))) == 1
    seen = {entry["file_name"]: entry["outcome"] for entry in ledger.files_seen(places.state_file)}
    assert seen == {"orders_2026-09-14.csv": "loaded", "orders_2026-09-14_resend.csv": "skipped"}


# ---- The dispatcher (LLD section 8) ----


def test_outcomes_without_and_with_approved_mappings(tmp_path):
    without = places_in(tmp_path / "without", approved=False)
    results = load_batch(places=without, max_concurrency=8)
    counts = {}
    for item in results:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    assert counts == {"loaded": 42, "skipped": 1, "rejected": 1, "waiting": 6}
    assert {item["file_name"] for item in results if item["outcome"] == "waiting"} == set(
        load_mapping_cases()
    )
    with_mappings = places_in(tmp_path / "with")
    load_batch(places=with_mappings)
    assert ledger.outcome_counts(with_mappings.state_file) == {
        "loaded": 48, "skipped": 1, "rejected": 1,
    }  # fmt: skip


def test_all_at_once_twice_gives_the_same_tables_as_one_at_a_time_once(tmp_path):
    one = places_in(tmp_path / "one")
    load_batch(places=one, max_concurrency=1)
    many = places_in(tmp_path / "many")
    load_batch(places=many, max_concurrency=50)
    again = load_batch(places=many, max_concurrency=50)
    assert {item["outcome"] for item in again} <= {"already_loaded", "skipped", "rejected"}
    assert tables_as_text(one.loaded) == tables_as_text(many.loaded)


def test_approving_the_waiting_files_gives_the_same_tables_as_saved_mappings(tmp_path):
    asked = places_in(tmp_path / "asked", approved=False)
    load_batch(places=asked, model=FakeMappingModel())
    workflow = build_file_workflow(asked)
    for question in waiting_files(workflow, asked):
        answer(workflow, question["file_name"], True, "Vijay")
    saved = places_in(tmp_path / "saved")
    load_batch(places=saved)
    assert tables_as_text(asked.loaded) == tables_as_text(saved.loaded)
    assert read_approved_mappings(asked.mappings_file) == json.loads(MAPPINGS_FILE.read_text())


def test_the_cap_is_respected_and_a_failed_worker_is_retried():
    running, most, tries = [], [0], {}

    def worker(file_name):
        tries[file_name] = tries.get(file_name, 0) + 1
        if file_name == "f3" and tries[file_name] == 1:
            raise RuntimeError("429 Too Many Requests")
        running.append(file_name)
        most[0] = max(most[0], len(running))
        time.sleep(0.05)
        running.remove(file_name)
        return {"results": [{"file_name": file_name}]}

    files = [f"f{number}" for number in range(10)]
    result = build_dispatcher(worker).invoke({"files": files}, {"max_concurrency": 3})
    assert sorted(item["file_name"] for item in result["results"]) == sorted(files)
    assert most[0] <= 3 and tries["f3"] == 2


def test_clear_loaded_keeps_the_landing_files_and_the_mappings(tmp_path):
    places = places_in(tmp_path)
    load_batch(places=places)
    clear_loaded(places)
    assert not places.loaded.exists() and not places.state_file.exists()
    assert places.mappings_file.exists() and len(list(places.landing.glob("*.csv"))) == 50


def test_the_pipeline_runs_when_only_some_feeds_have_files(tmp_path):
    """A feed with no loaded file gives an empty table, and the pipeline still runs."""
    from retail_profit_stack.transform.pipeline import run_pipeline

    places = places_in(tmp_path)
    some = ["products.csv", "product_costs_2026-09.csv", "orders_2026-09-07.csv",
            "order_items_2026-09-07.csv"]  # fmt: skip
    load_batch(some, places=places)
    run = run_pipeline("sql", places.loaded, tmp_path / "warehouse")
    assert run.row_counts["monthly_product_profit"] == 12
    assert run.record["inputs"]["refunds"] == {
        "rows": 0,
        "files": 0,
        "fingerprint": run.record["inputs"]["refunds"]["fingerprint"],
    }
    assert run.record["lineage_adds_up"] is True
