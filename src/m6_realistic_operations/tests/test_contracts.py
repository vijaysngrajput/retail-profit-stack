"""LLD sections 3 and 4: conform() accepts a correct table and rejects each kind of violation."""

import pyarrow as pa
import pytest

from retail_profit_stack.transform.contracts import (
    Column,
    ContractError,
    TableSchema,
    conform,
    table_from_rows,
    tables_differ,
)

SCHEMA = TableSchema(
    "example",
    (
        Column("month", "month"),
        Column("product_id", "string"),
        Column("units", "integer"),
        Column("amount", "decimal"),
        Column("cost", "decimal", nullable=True),
    ),
    key=("month", "product_id"),
)
ROW = {"month": "2026-10", "product_id": "P001", "units": 2, "amount": 80.0, "cost": 36.0}


def table(*rows):
    return pa.Table.from_pylist(list(rows))


def test_a_correct_table_passes_and_keeps_its_values():
    assert conform(table(ROW), SCHEMA).to_pylist() == [ROW]


def test_columns_are_put_in_the_contract_order():
    shuffled = {name: ROW[name] for name in ["cost", "units", "amount", "product_id", "month"]}
    assert conform(table(shuffled), SCHEMA).column_names == SCHEMA.names


def test_rows_are_sorted_by_the_key():
    later = {**ROW, "product_id": "P009"}
    assert [r["product_id"] for r in conform(table(later, ROW), SCHEMA).to_pylist()] == [
        "P001",
        "P009",
    ]


def test_amounts_are_rounded_to_cents():
    assert conform(table({**ROW, "amount": 80.004999}), SCHEMA).to_pylist()[0]["amount"] == 80.0


def test_not_a_number_becomes_missing():
    assert conform(table({**ROW, "cost": float("nan")}), SCHEMA).to_pylist()[0]["cost"] is None


def test_a_whole_number_that_arrived_as_a_decimal_is_accepted():
    assert conform(table({**ROW, "units": 2.0}), SCHEMA).to_pylist()[0]["units"] == 2


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({key: value for key, value in ROW.items() if key != "amount"}, "Missing: \\['amount'\\]"),
        ({**ROW, "surprise": 1}, "Unexpected: \\['surprise'\\]"),
        ({**ROW, "amount": None}, "missing values are not allowed"),
        ({**ROW, "month": "October 2026"}, "a month must be text like 2026-10"),
        ({**ROW, "units": "two"}, "expected integer"),
    ],
)
def test_each_violation_is_rejected_with_a_clear_message(row, message):
    with pytest.raises(ContractError, match=message):
        conform(table(row), SCHEMA)


def test_two_rows_with_the_same_key_are_rejected():
    with pytest.raises(ContractError, match="more than one row"):
        conform(table(ROW, ROW), SCHEMA)


def test_a_schema_without_a_key_allows_repeated_rows():
    loose = TableSchema("loose", SCHEMA.columns)
    assert conform(table(ROW, ROW), loose).num_rows == 2


def test_an_empty_table_can_be_built_from_no_rows():
    assert table_from_rows([], SCHEMA).num_rows == 0


def test_tables_differ_names_the_first_difference():
    first = table_from_rows([ROW], SCHEMA)
    assert tables_differ(first, first) is None
    assert "amount: expected 80.0, got 81.0" in tables_differ(
        table_from_rows([{**ROW, "amount": 81.0}], SCHEMA), first
    )
    assert "expected 1 rows, got 0" in tables_differ(table_from_rows([], SCHEMA), first)
