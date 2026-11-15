"""LLD sections 5, 6, and 8: every transformation, on every engine, and the pipeline."""

import csv

import pytest

from retail_profit_stack.config import WAREHOUSE_DIR
from retail_profit_stack.lineage.runs import run_folder
from retail_profit_stack.quality.checks import number_rows, run_record_checks
from retail_profit_stack.quality.quarantine import split_records
from retail_profit_stack.transform.contracts import table_from_rows, tables_differ
from retail_profit_stack.transform.engines import ENGINES, Engine, get_engine
from retail_profit_stack.transform.pipeline import load_sources, run_pipeline, run_transformations
from retail_profit_stack.transform.specs import ALL_IN_ONE, SPECS, TASKS, ordered_specs
from retail_profit_stack.transform.testing import load_cases, run_cases

BUILT_ENGINES = ["sql", "pandas"]


@pytest.mark.parametrize("engine_name", BUILT_ENGINES)
@pytest.mark.parametrize("task", list(TASKS))
def test_every_hand_worked_case_passes(task, engine_name):
    results = run_cases(TASKS[task], engine_name)
    assert results, "no cases for this transformation"
    assert [result.message for result in results if not result.passed] == []


def test_every_transformation_has_cases_including_the_required_ones():
    names = {case.transformation: [] for case in load_cases()}
    for case in load_cases():
        names[case.transformation].append(case.name)
    assert set(names) == set(TASKS)
    assert len(load_cases()) == 22
    required = {
        "sales": ["a discounted line", "a cancelled order is left out"],
        "refund_totals": ["a refund counts in the month it is issued", "two refunds on one line"],
        "product_cost": ["cost missing"],
        "monthly_product_profit": ["cost missing", "no refunds that month"],
    }
    for task, cases in required.items():
        assert set(cases) <= set(names[task]), task


def test_both_engines_agree_on_the_full_data():
    sources = load_sources()
    by_sql = run_transformations(get_engine("sql"), sources)
    by_pandas = run_transformations(get_engine("pandas"), sources)
    assert list(by_sql) == [spec.name for spec in ordered_specs()]
    for name in by_sql:
        assert tables_differ(by_pandas[name], by_sql[name]) is None, name


@pytest.mark.parametrize("engine_name", BUILT_ENGINES)
def test_the_all_in_one_task_agrees_with_the_six_steps(engine_name, calculated_tables):
    # The pipeline calculates from the kept records, so the all-in-one task must too.
    sources = number_rows(load_sources())
    kept, _ = split_records(sources, run_record_checks(sources))
    engine = get_engine(engine_name)
    for name, table in kept.items():
        engine.register(name, table)
    all_in_one = engine.run(ALL_IN_ONE)
    assert tables_differ(all_in_one, calculated_tables.tables["monthly_product_profit"]) is None


def test_the_calculated_table_equals_milestone_1_except_the_trail_water_bottle(calculated_tables):
    """Three duplicated P001 lines are no longer counted. Nothing else may differ."""
    duplicated_lines = 3  # each: 1 unit at $40.00 list, $4.00 discount, $18.00 cost
    changes = {
        "units_sold": 1, "gross_sales": 40.0, "discounts": 4.0, "net_sales": 36.0,
        "product_cost": 18.0, "gross_profit": 18.0, "fulfillment_cost": 2.5,
        "shipping_cost": 4.0, "payment_fees": 1.08, "contribution_profit": 10.42,
    }  # fmt: skip
    with open("tests/fixtures/m1_monthly_product_profit.csv", encoding="utf-8") as handle:
        prepared = []
        for row in csv.DictReader(handle):
            converted = {}
            for name, value in row.items():
                if name in ("month", "product_id", "metric_version"):
                    converted[name] = value
                elif value == "":
                    converted[name] = None
                else:
                    converted[name] = int(value) if name == "units_sold" else float(value)
            if (converted["month"], converted["product_id"]) == ("2026-10", "P001"):
                for name, per_line in changes.items():
                    converted[name] = round(converted[name] - duplicated_lines * per_line, 2)
            prepared.append(converted)
    expected = table_from_rows(prepared, SPECS["monthly_product_profit"].output)
    assert expected.num_rows == 24
    assert tables_differ(calculated_tables.tables["monthly_product_profit"], expected) is None


def test_running_twice_gives_identical_tables(tmp_path):
    first = run_pipeline("sql", warehouse_dir=tmp_path / "one")
    second = run_pipeline("sql", warehouse_dir=tmp_path / "two")
    for name in first.tables:
        assert first.tables[name].equals(second.tables[name]), name
        one = run_folder(first.run_id, tmp_path / "one") / f"{name}.parquet"
        two = run_folder(second.run_id, tmp_path / "two") / f"{name}.parquet"
        assert one.read_bytes() == two.read_bytes()


def test_the_pipeline_saves_every_table_and_reports_what_it_did(calculated_tables):
    assert calculated_tables.engine == "sql"
    assert calculated_tables.row_counts == dict.fromkeys(SPECS, 24)
    folder = run_folder(calculated_tables.run_id, WAREHOUSE_DIR)
    assert {path.stem for path in folder.glob("*.parquet")} >= set(SPECS)


def test_transformations_run_after_their_inputs():
    order = [spec.name for spec in ordered_specs()]
    assert order.index("product_cost") > order.index("sales")
    assert order[-1] == "monthly_product_profit"


def test_the_engine_is_chosen_by_one_setting(monkeypatch):
    assert get_engine().name == "sql"
    monkeypatch.setenv("TRANSFORM_ENGINE", "pandas")
    assert get_engine().name == "pandas"
    with pytest.raises(ValueError, match="Valid values: sql, pandas, spark"):
        get_engine("excel")


def test_every_engine_implements_the_interface():
    assert all(issubclass(engine, Engine) for engine in ENGINES.values())


def test_the_spark_slot_says_clearly_that_it_is_not_built():
    with pytest.raises(NotImplementedError, match="not built yet"):
        get_engine("spark").run(SPECS["sales"])
