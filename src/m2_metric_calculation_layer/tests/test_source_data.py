"""LLD section 2: the generated business records match their schemas and plant what they should."""

import csv

import pyarrow.compute as pc

from retail_profit_stack import source_data
from retail_profit_stack.config import SOURCE_DIR
from retail_profit_stack.transform.pipeline import load_sources
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS


def rows(name):
    return load_sources()[name].to_pylist()


def test_every_source_table_loads_with_its_schema():
    sources = load_sources()
    assert set(sources) == set(SOURCE_SCHEMAS)
    assert sources["products"].num_rows == 12
    assert sources["product_costs"].num_rows == 23  # 12 products x 2 months, less the missing one


def test_files_on_disk_match_the_generator():
    for name, built in source_data.build().items():
        with (SOURCE_DIR / f"{name}.csv").open(encoding="utf-8") as handle:
            on_disk = list(csv.DictReader(handle))
        assert on_disk == [{key: str(value) for key, value in row.items()} for row in built], name


def test_the_generator_gives_the_same_records_every_time():
    assert source_data.build() == source_data.build()


def test_references_between_tables_hold():
    sources = load_sources()
    orders = set(sources["orders"].column("order_id").to_pylist())
    lines = set(sources["order_items"].column("order_item_id").to_pylist())
    assert set(sources["order_items"].column("order_id").to_pylist()) <= orders
    for table in ("refunds", "shipments", "payment_fees"):
        assert set(sources[table].column("order_item_id").to_pylist()) <= lines, table


def test_planted_missing_cost():
    costs = {(row["product_id"], row["month"]) for row in rows("product_costs")}
    assert ("P007", "2026-10") not in costs and ("P007", "2026-09") in costs


def test_planted_duplicates_are_three_trail_water_bottle_lines():
    counts = load_sources()["order_items"].group_by("order_item_id").aggregate([([], "count_all")])
    repeated = counts.filter(pc.greater(counts.column("count_all"), 1))
    assert repeated.num_rows == 3
    ids = set(repeated.column("order_item_id").to_pylist())
    lines = [row for row in rows("order_items") if row["order_item_id"] in ids]
    assert {row["product_id"] for row in lines} == {"P001"} and len(lines) == 6
    for table in ("shipments", "payment_fees"):
        assert sum(row["order_item_id"] in ids for row in rows(table)) == 6, table


def test_planted_oversized_refund():
    line_value = {
        row["order_item_id"]: row["quantity"] * row["unit_list_price"] - row["discount_amount"]
        for row in rows("order_items")
    }
    oversized = [
        r for r in rows("refunds") if r["refund_amount"] > line_value[r["order_item_id"]] + 0.005
    ]
    assert len(oversized) == 1
    assert oversized[0]["product_id"] == "P011" and oversized[0]["refund_amount"] == 60.0


def test_cancelled_orders_have_lines_but_no_shipment_or_fee():
    cancelled = {row["order_id"] for row in rows("orders") if row["status"] == "cancelled"}
    lines = {row["order_item_id"] for row in rows("order_items") if row["order_id"] in cancelled}
    assert len(cancelled) == 24 and lines
    for table in ("shipments", "payment_fees", "refunds"):
        assert not any(row["order_item_id"] in lines for row in rows(table)), table


def test_some_refunds_are_for_orders_from_the_month_before():
    order_of_line = {row["order_item_id"]: row["order_id"] for row in rows("order_items")}
    order_date = {row["order_id"]: row["order_date"] for row in rows("orders")}
    crossing = [
        refund for refund in rows("refunds")
        if order_date[order_of_line[refund["order_item_id"]]].month != refund["refund_date"].month
    ]  # fmt: skip
    assert crossing and all(refund["refund_date"].month == 10 for refund in crossing)


def test_one_line_has_two_refunds():
    counts = load_sources()["refunds"].group_by("order_item_id").aggregate([([], "count_all")])
    assert pc.max(counts.column("count_all")).as_py() == 2
