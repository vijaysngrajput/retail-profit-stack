"""Contracts: what a table must look like, and what a transformation must produce.

Implements LLD section 3 (The standard table format) and section 4 (Contracts). Nothing in
this module knows about SQL, pandas, or Spark.
"""

# pyarrow.compute builds its functions when it is imported, so a type checker cannot see them.
# pyright: reportAttributeAccessIssue=false

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pyarrow as pa
import pyarrow.compute as pc

ColumnType = Literal["string", "integer", "decimal", "month", "date"]

ARROW_TYPES = {
    "string": pa.string(),
    "integer": pa.int64(),
    "decimal": pa.float64(),
    "month": pa.string(),
    "date": pa.date32(),
}
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
DECIMAL_PLACES = 2


class ContractError(ValueError):
    """A table does not match its contract. The message names the rule and the column."""


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType
    nullable: bool = False
    description: str = ""


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[Column, ...]
    key: tuple[str, ...] = ()  # empty means rows are not required to be unique

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def arrow_schema(self) -> pa.Schema:
        return pa.schema([(column.name, ARROW_TYPES[column.type]) for column in self.columns])


@dataclass(frozen=True)
class TransformationSpec:
    """One transformation, described without any engine in it."""

    name: str  # also the name of its output table
    inputs: tuple[str, ...]  # source tables or other transformations
    output: TableSchema
    rule: str  # the business rule, in words
    definitions: tuple[str, ...] = ()  # metric terms from metrics_v1.json this produces


def conform(table: pa.Table, schema: TableSchema) -> pa.Table:
    """Check a table against its contract and return it in the standard form.

    The standard form has exactly the contract's columns, in order, with the contract's types;
    amounts rounded to cents; and rows sorted by the key. Any violation raises ContractError.
    """
    missing = [name for name in schema.names if name not in table.column_names]
    extra = [name for name in table.column_names if name not in schema.names]
    if missing or extra:
        raise ContractError(
            f"{schema.name}: columns do not match the contract. "
            f"Missing: {missing or 'none'}. Unexpected: {extra or 'none'}."
        )

    arrays = []
    for column in schema.columns:
        values = table.column(column.name)
        try:
            if column.type == "decimal":
                values = pc.round(values.cast(pa.float64()), ndigits=DECIMAL_PLACES)
                values = pc.if_else(pc.is_nan(values), pa.scalar(None, pa.float64()), values)
            elif column.type == "integer" and pa.types.is_floating(values.type):
                values = pc.round(values).cast(pa.int64())  # a whole number that arrived as 3.0
            else:
                values = values.cast(ARROW_TYPES[column.type])
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as error:
            raise ContractError(
                f"{schema.name}.{column.name}: expected {column.type}, got {values.type} ({error})"
            ) from error
        if not column.nullable and values.null_count:
            raise ContractError(f"{schema.name}.{column.name}: missing values are not allowed here")
        if column.type == "month":
            bad = [
                value for value in values.to_pylist() if value and not MONTH_PATTERN.match(value)
            ]
            if bad:
                raise ContractError(
                    f"{schema.name}.{column.name}: a month must be text like 2026-10, got {bad[0]!r}"
                )
        arrays.append(values)
    result = pa.table(arrays, schema=schema.arrow_schema())

    if schema.key:
        counts = result.group_by(list(schema.key)).aggregate([([], "count_all")])
        repeated = counts.filter(pc.greater(counts.column("count_all"), 1))
        if repeated.num_rows:
            example = {name: repeated.column(name)[0].as_py() for name in schema.key}
            raise ContractError(f"{schema.name}: more than one row for {example}")
        result = result.sort_by([(name, "ascending") for name in schema.key])
    return result


def table_from_rows(rows: list[dict], schema: TableSchema) -> pa.Table:
    """Build a table from plain rows, such as the rows written out in a hand-worked test case."""
    columns = {}
    for column in schema.columns:
        values = [row.get(column.name) for row in rows]
        if column.type == "date":
            values = [
                date.fromisoformat(value) if isinstance(value, str) else value for value in values
            ]
        columns[column.name] = pa.array(values, type=ARROW_TYPES[column.type])
    return conform(pa.table(columns), schema)


def tables_differ(actual: pa.Table, expected: pa.Table) -> str | None:
    """Compare two tables in the standard form. Returns None if equal, or what differs."""
    if actual.num_rows != expected.num_rows:
        return f"expected {expected.num_rows} rows, got {actual.num_rows}"
    for index, (got, want) in enumerate(zip(actual.to_pylist(), expected.to_pylist(), strict=True)):
        for name, wanted in want.items():
            value = got[name]
            same = (
                abs(value - wanted) <= 0.005
                if isinstance(wanted, float) and isinstance(value, float)
                else value == wanted
            )
            if not same:
                return f"row {index + 1}, {name}: expected {wanted!r}, got {value!r} (row: {got})"
    return None
