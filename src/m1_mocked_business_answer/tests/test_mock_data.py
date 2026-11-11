"""LLD section 3: the mock tables match their contract and the section 2 formulas."""

import csv

import pytest

from retail_profit_stack import mock_data
from retail_profit_stack.config import MOCK_DIR
from retail_profit_stack.store import DataContractError, Store, get_store


def test_row_counts():
    store = get_store()
    assert len(store.product_ids()) == 12
    assert store.months() == ["2026-09", "2026-10"]
    assert store.rows("SELECT COUNT(*) AS n FROM monthly_product_profit")[0]["n"] == 24
    assert store.rows("SELECT COUNT(*) AS n FROM quality_flags")[0]["n"] == 3
    assert store.categories() == ["Apparel", "Camp", "Hydration"]


def test_each_category_has_four_products():
    counts = get_store().rows("SELECT category, COUNT(*) AS n FROM products GROUP BY category")
    assert {row["n"] for row in counts} == {4}


def test_every_row_satisfies_the_metric_formulas():
    for row in get_store().rows("SELECT * FROM monthly_product_profit"):
        assert row["net_sales"] == pytest.approx(
            row["gross_sales"] - row["discounts"] - row["refunds"], abs=0.005
        )
        if row["product_cost"] is None:
            assert row["gross_profit"] is None
            assert row["contribution_profit"] is None
            continue
        assert row["gross_profit"] == pytest.approx(
            row["net_sales"] - row["product_cost"], abs=0.005
        )
        assert row["contribution_profit"] == pytest.approx(
            row["gross_profit"]
            - row["fulfillment_cost"]
            - row["shipping_cost"]
            - row["payment_fees"]
            - row["return_cost"],
            abs=0.005,
        )


def test_only_the_planted_row_has_a_missing_cost():
    missing = get_store().rows(
        "SELECT month, product_id FROM monthly_product_profit WHERE product_cost IS NULL"
    )
    assert missing == [{"month": "2026-10", "product_id": "P007"}]


def test_committed_csv_matches_the_generator():
    with (MOCK_DIR / "monthly_product_profit.csv").open(encoding="utf-8") as handle:
        on_disk = list(csv.DictReader(handle))
    generated = mock_data.build_profit_rows()
    assert len(on_disk) == len(generated)
    for disk_row, built_row in zip(on_disk, generated, strict=True):
        for column, value in built_row.items():
            assert disk_row[column] == ("" if value is None else str(value))


def test_unknown_product_breaks_the_contract(tmp_path):
    for path in MOCK_DIR.iterdir():
        (tmp_path / path.name).write_text(path.read_text("utf-8"), "utf-8")
    with (tmp_path / "quality_flags.csv").open("a", encoding="utf-8") as handle:
        handle.write("QF-999,2026-10,P999,made_up,low,net_sales,Unknown product\n")
    with pytest.raises(DataContractError, match="unknown products"):
        Store(mock_dir=tmp_path)


def test_missing_table_breaks_the_contract(tmp_path):
    with pytest.raises(DataContractError, match="Missing mock table"):
        Store(mock_dir=tmp_path)
