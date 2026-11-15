"""The review desk: a person decides a finding, and the next run obeys.

Implements LLD section 5 (The review desk). A decision is about one record, named by a key
that does not change from run to run. Decisions are kept in a small JSON file, each with the
person's name and a note. No model is involved: a person decides, and code applies it.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa

DECISIONS = ["accept", "exclude"]
# The column that holds each record's own id.
ID_COLUMN = {
    "order_items": "order_item_id",
    "refunds": "refund_id",
    "shipments": "shipment_id",
    "payment_fees": "fee_id",
}


def record_key(check_name: str, source_table: str, record_id: str) -> str:
    """The name a decision is filed under, for example refund_exceeds_line|refunds|REF-0002."""
    return f"{check_name}|{source_table}|{record_id}"


def read_decisions(decisions_file: Path | None) -> dict[str, dict]:
    """Every decision made so far, by record key. Empty when there is no file."""
    if decisions_file is None or not decisions_file.exists():
        return {}
    return json.loads(decisions_file.read_text(encoding="utf-8"))


def decide(decisions_file: Path, key: str, decision: str, person: str, note: str = "") -> dict:
    """Record a person's decision on one record. A later decision replaces an earlier one."""
    if decision not in DECISIONS:
        raise ValueError(f"A decision must be one of: {', '.join(DECISIONS)}")
    decisions = read_decisions(decisions_file)
    decisions[key] = {
        "decision": decision,
        "person": person,
        "note": note,
        "decided_at": datetime.now().isoformat(timespec="seconds"),
    }
    decisions_file.parent.mkdir(parents=True, exist_ok=True)
    decisions_file.write_text(json.dumps(decisions, indent=2) + "\n", encoding="utf-8")
    return decisions[key]


def remove_decision(decisions_file: Path, key: str) -> None:
    """Take a decision back. The finding needs review again on the next run."""
    decisions = read_decisions(decisions_file)
    decisions.pop(key, None)
    decisions_file.write_text(json.dumps(decisions, indent=2) + "\n", encoding="utf-8")


def add_decisions(
    bad_records: pd.DataFrame, numbered_sources: dict[str, pa.Table], decisions: dict[str, dict]
) -> pd.DataFrame:
    """Give each bad record its key, and the decision made about it, if any."""
    ids: dict[str, list] = {}
    for table, column in ID_COLUMN.items():
        ids[table] = numbered_sources[table].column(column).to_pylist()
    keys, made, people = [], [], []
    for row in bad_records.to_dict(orient="records"):
        key = ""
        if row["source_table"] in ids and not pd.isna(row["row_number"]):
            record_id = ids[row["source_table"]][int(row["row_number"]) - 1]
            key = record_key(row["check_name"], row["source_table"], record_id)
        decision = decisions.get(key, {})
        keys.append(key)
        made.append(decision.get("decision", ""))
        people.append(decision.get("person", ""))
    with_decisions = bad_records.copy()
    with_decisions["record_key"] = keys
    with_decisions["decision"] = made
    with_decisions["decided_by"] = people
    return with_decisions


def open_reviews(findings: pd.DataFrame, finding_records: pd.DataFrame) -> list[dict]:
    """The records still waiting for a decision, each with its finding's description."""
    described = {row["finding_id"]: row for row in findings.to_dict(orient="records")}
    waiting = []
    for record in finding_records.to_dict(orient="records"):
        finding = described[record["finding_id"]]
        if finding["outcome"] != "needs_review" or not record.get("record_key"):
            continue
        waiting.append({
            "record_key": record["record_key"],
            "finding_id": record["finding_id"],
            "check_name": finding["check_name"],
            "month": finding["month"],
            "product_id": finding["product_id"],
            "detail": record["detail"],
            "record": json.loads(record["record"]),
        })  # fmt: skip
    return waiting
