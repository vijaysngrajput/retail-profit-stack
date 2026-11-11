"""Write the mock tables for milestone 1.

Implements LLD section 3 (Mock tables). The inputs below are hand-chosen and
fictional. This module only applies the LLD section 2 formulas to monthly
inputs so that every row is internally consistent. It does not calculate profit
from business events; that is milestone 2's job.

Run it with:  uv run python -m retail_profit_stack.mock_data
"""

import csv
import json

from retail_profit_stack.config import METRIC_VERSION, MOCK_DIR

MONTHS = ["2026-09", "2026-10"]
PAYMENT_FEE_RATE = 0.03

# product_id: (name, category, list price, unit cost, fulfilment per unit, shipping per unit)
PRODUCTS = {
    "P001": ("Trail water bottle", "Hydration", 40.0, 18.0, 2.5, 4.0),
    "P002": ("Insulated flask", "Hydration", 35.0, 15.0, 2.5, 4.0),
    "P003": ("Hydration pack", "Hydration", 90.0, 48.0, 3.0, 6.0),
    "P004": ("Water filter", "Hydration", 55.0, 24.0, 2.5, 4.5),
    "P005": ("Two-person tent", "Camp", 320.0, 190.0, 8.0, 22.0),
    "P006": ("Sleeping bag", "Camp", 150.0, 82.0, 5.0, 12.0),
    "P007": ("Camp stove", "Camp", 85.0, 44.0, 3.5, 7.0),
    "P008": ("Headlamp", "Camp", 30.0, 11.0, 2.0, 3.5),
    "P009": ("Rain jacket", "Apparel", 140.0, 70.0, 3.0, 6.0),
    "P010": ("Hiking socks", "Apparel", 18.0, 6.0, 1.5, 3.0),
    "P011": ("Sun hat", "Apparel", 25.0, 9.0, 1.5, 3.0),
    "P012": ("Fleece pullover", "Apparel", 75.0, 36.0, 2.5, 5.0),
}

# (product_id, month): (units sold, discount rate, refunds in dollars, return handling cost)
MONTHLY = {
    ("P001", "2026-09"): (420, 0.05, 76.0, 12.0),
    ("P001", "2026-10"): (510, 0.10, 108.0, 18.0),
    ("P002", "2026-09"): (260, 0.05, 66.5, 12.0),
    ("P002", "2026-10"): (240, 0.05, 33.25, 6.0),
    ("P003", "2026-09"): (95, 0.10, 162.0, 16.0),
    ("P003", "2026-10"): (120, 0.10, 81.0, 8.0),
    ("P004", "2026-09"): (150, 0.00, 55.0, 7.0),
    ("P004", "2026-10"): (165, 0.05, 104.5, 14.0),
    ("P005", "2026-09"): (48, 0.05, 608.0, 60.0),
    ("P005", "2026-10"): (36, 0.10, 288.0, 30.0),
    ("P006", "2026-09"): (70, 0.05, 285.0, 24.0),
    ("P006", "2026-10"): (88, 0.05, 142.5, 12.0),
    ("P007", "2026-09"): (110, 0.00, 170.0, 18.0),
    ("P007", "2026-10"): (125, 0.05, 80.75, 9.0),
    ("P008", "2026-09"): (300, 0.00, 60.0, 8.0),
    ("P008", "2026-10"): (340, 0.00, 30.0, 4.0),
    ("P009", "2026-09"): (130, 0.05, 399.0, 27.0),
    ("P009", "2026-10"): (150, 0.20, 560.0, 45.0),
    ("P010", "2026-09"): (520, 0.00, 36.0, 6.0),
    ("P010", "2026-10"): (480, 0.10, 32.4, 6.0),
    ("P011", "2026-09"): (210, 0.00, 110.0, 8.0),
    ("P011", "2026-10"): (90, 0.20, 20.0, 4.0),
    ("P012", "2026-09"): (160, 0.05, 213.75, 15.0),
    ("P012", "2026-10"): (175, 0.15, 255.0, 20.0),
}

# The planted problem behind QF-001: no product cost was loaded for this row.
MISSING_COST = {("P007", "2026-10")}

QUALITY_FLAGS = [
    {
        "flag_id": "QF-001",
        "month": "2026-10",
        "product_id": "P007",
        "check_name": "missing_product_cost",
        "severity": "high",
        "affected_metrics": "product_cost;gross_profit;contribution_profit",
        "description": (
            "No product cost is recorded for Camp stove in 2026-10, so its gross profit and "
            "contribution profit cannot be calculated. The Camp category total leaves it out."
        ),
    },
    {
        "flag_id": "QF-002",
        "month": "2026-10",
        "product_id": "P001",
        "check_name": "duplicate_orders",
        "severity": "medium",
        "affected_metrics": "units_sold;gross_sales;net_sales;gross_profit;contribution_profit",
        "description": (
            "Three orders for Trail water bottle appear twice in 2026-10. Its sales and profit "
            "may be overstated."
        ),
    },
    {
        "flag_id": "QF-003",
        "month": "2026-09",
        "product_id": "P011",
        "check_name": "refund_exceeds_order",
        "severity": "low",
        "affected_metrics": "refunds;net_sales;gross_profit;contribution_profit",
        "description": (
            "A 2026-09 refund for Sun hat is larger than the order it refunds. Its September net "
            "sales may be understated, which affects its change from September to October."
        ),
    },
]

REPORTING_PERIOD = {
    "as_of_date": "2026-11-01",
    "current_month": "2026-10",
    "previous_month": "2026-09",
}

PROFIT_COLUMNS = [
    "month",
    "product_id",
    "units_sold",
    "gross_sales",
    "discounts",
    "refunds",
    "net_sales",
    "product_cost",
    "gross_profit",
    "fulfillment_cost",
    "shipping_cost",
    "payment_fees",
    "return_cost",
    "contribution_profit",
    "metric_version",
]


def build_profit_rows() -> list[dict]:
    """Apply the LLD section 2 formulas to the monthly inputs, one row per product per month."""
    rows = []
    for (product_id, month), (units, discount_rate, refunds, return_cost) in MONTHLY.items():
        _, _, price, unit_cost, fulfil, ship = PRODUCTS[product_id]
        gross_sales = round(units * price, 2)
        discounts = round(gross_sales * discount_rate, 2)
        net_sales = round(gross_sales - discounts - refunds, 2)
        fulfillment_cost = round(units * fulfil, 2)
        shipping_cost = round(units * ship, 2)
        payment_fees = round((gross_sales - discounts) * PAYMENT_FEE_RATE, 2)
        if (product_id, month) in MISSING_COST:
            product_cost = gross_profit = contribution_profit = None
        else:
            product_cost = round(units * unit_cost, 2)
            gross_profit = round(net_sales - product_cost, 2)
            contribution_profit = round(
                gross_profit - fulfillment_cost - shipping_cost - payment_fees - return_cost, 2
            )
        rows.append(
            {
                "month": month,
                "product_id": product_id,
                "units_sold": units,
                "gross_sales": gross_sales,
                "discounts": discounts,
                "refunds": refunds,
                "net_sales": net_sales,
                "product_cost": product_cost,
                "gross_profit": gross_profit,
                "fulfillment_cost": fulfillment_cost,
                "shipping_cost": shipping_cost,
                "payment_fees": payment_fees,
                "return_cost": return_cost,
                "contribution_profit": contribution_profit,
                "metric_version": METRIC_VERSION,
            }
        )
    return sorted(rows, key=lambda row: (row["month"], row["product_id"]))


def build_evidence_rows() -> list[dict]:
    """Hand-written style sample records: about three per product per month."""
    rows = []
    order_number = 20400

    def add(month, product_id, record_type, source_table, source_record_id, amount, description):
        rows.append(
            {
                "evidence_id": f"EV-{len(rows) + 1:04d}",
                "month": month,
                "product_id": product_id,
                "record_type": record_type,
                "source_table": source_table,
                "source_record_id": source_record_id,
                "amount": round(amount, 2),
                "description": description,
            }
        )

    for (product_id, month), (_, discount_rate, refunds, _) in sorted(
        MONTHLY.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        name, _, price, unit_cost, _, ship = PRODUCTS[product_id]
        order_number += 1
        order_id = f"ORD-{order_number}"
        paid = price * (1 - discount_rate)
        add(
            month,
            product_id,
            "order_item",
            "order_items",
            order_id,
            paid,
            f"1 x {name} at list price {price:.2f}, discount {discount_rate:.0%}",
        )
        if (product_id, month) in MISSING_COST:
            add(
                month,
                product_id,
                "shipment",
                "shipments",
                f"SHP-{order_number}",
                ship,
                f"Carrier cost for {order_id}",
            )
        else:
            add(
                month,
                product_id,
                "product_cost",
                "product_costs",
                f"COST-{product_id}-{month}",
                unit_cost,
                f"Unit cost of {name} agreed with the vendor",
            )
        if (product_id, month) == ("P001", "2026-10"):
            add(
                month,
                product_id,
                "order_item",
                "order_items",
                order_id,
                paid,
                f"1 x {name}; same order ID as the record above (see QF-002)",
            )
        elif (product_id, month) == ("P011", "2026-09"):
            add(
                month,
                product_id,
                "refund",
                "refunds",
                f"REF-{order_number}",
                60.0,
                f"Refund against {order_id}, larger than the order value (see QF-003)",
            )
        elif refunds > 0:
            add(
                month,
                product_id,
                "refund",
                "refunds",
                f"REF-{order_number}",
                paid,
                f"Full refund of one {name} issued in {month}",
            )
        add(
            month,
            product_id,
            "payment_fee",
            "payment_fees",
            f"FEE-{order_number}",
            paid * PAYMENT_FEE_RATE,
            f"Payment provider fee on {order_id}",
        )
    return rows


def _write_csv(name: str, columns: list[str], rows: list[dict]) -> None:
    with (MOCK_DIR / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("" if value is None else value) for key, value in row.items()})


def write_mock_data() -> None:
    """Write every mock table into data/mock/."""
    MOCK_DIR.mkdir(parents=True, exist_ok=True)
    products = [
        {"product_id": product_id, "product_name": values[0], "category": values[1]}
        for product_id, values in PRODUCTS.items()
    ]
    _write_csv("products.csv", ["product_id", "product_name", "category"], products)
    _write_csv("monthly_product_profit.csv", PROFIT_COLUMNS, build_profit_rows())
    evidence = build_evidence_rows()
    _write_csv("evidence_records.csv", list(evidence[0]), evidence)
    _write_csv("quality_flags.csv", list(QUALITY_FLAGS[0]), QUALITY_FLAGS)
    (MOCK_DIR / "reporting_period.json").write_text(
        json.dumps(REPORTING_PERIOD, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    write_mock_data()
    print(f"Wrote mock tables to {MOCK_DIR}")
