"""Generate the business's records: orders, lines, refunds, shipments, fees, and costs.

Implements LLD section 2 (Source tables). The records are fictional. They are built so that
the profit calculated from them equals milestone 1's prepared figures exactly: this module
starts from the same monthly inputs per product and spreads them over individual orders.

The files are the same every time, because the random choices use a fixed seed.

Run it with:  uv run python -m retail_profit_stack.source_data
"""

import calendar
import csv
import random
from datetime import date, timedelta

from retail_profit_stack.config import SOURCE_DIR

SEED = 20261113
MONTHS = ["2026-09", "2026-10"]
PAYMENT_FEE_RATE = 0.03

# product_id: (name, category, list price, unit cost, pick-and-pack per unit, carrier per unit)
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
# These are milestone 1's monthly inputs. The records below must add up to them.
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

# ---- What is planted on purpose (LLD section 2) -----------------------------
MISSING_COST = {("P007", "2026-10")}  # behind quality flag QF-001
DUPLICATED = ("P001", "2026-10", 3)  # three lines loaded twice, behind QF-002
OVERSIZED_REFUND = ("P011", "2026-09", 60.0)  # a $60 refund on a $25 line, behind QF-003
TWO_REFUNDS_ON_ONE_LINE = ("P009", "2026-10")  # exposes a join of detail to detail
CANCELLED_PER_PRODUCT_MONTH = 1


def cents(amount: float) -> int:
    return round(amount * 100)


def split_units(rng: random.Random, units: int) -> list[int]:
    """Split a month's units into order lines of 1 to 4 units."""
    quantities = []
    while units > 0:
        quantity = min(units, rng.choice([1, 1, 1, 2, 2, 3, 4]))
        quantities.append(quantity)
        units -= quantity
    return quantities


def spread(total: int, parts: list[int], weights: list[int], adjustable: list[bool]) -> list[int]:
    """Nudge rounded parts by a cent at a time until their weighted sum equals the total.

    parts are amounts in cents, one per line. weights is how many times each line is counted
    (2 for a line that was loaded twice). Only adjustable lines are changed.
    """
    difference = total - sum(part * weight for part, weight in zip(parts, weights, strict=True))
    targets = [index for index, can in enumerate(adjustable) if can]
    step = 1 if difference > 0 else -1
    position = 0
    while difference != 0:
        parts[targets[position % len(targets)]] += step
        difference -= step
        position += 1
    return parts


def build() -> dict[str, list[dict]]:
    """Build every source table as a list of rows."""
    rng = random.Random(SEED)
    lines = []  # every order line, with the facts we need to derive the other tables

    for (product_id, month), (units, rate, _, _) in MONTHLY.items():
        price = PRODUCTS[product_id][2]
        year, month_number = (int(part) for part in month.split("-"))
        last_day = calendar.monthrange(year, month_number)[1]

        duplicated = DUPLICATED[2] if (product_id, month) == DUPLICATED[:2] else 0
        # A duplicated line is a single unit that was loaded twice, so it counts as 2 units.
        quantities = [1] * duplicated + split_units(rng, units - 2 * duplicated)
        weights = [2 if index < duplicated else 1 for index in range(len(quantities))]
        adjustable = [weight == 1 for weight in weights]

        gross = [cents(quantity * price) for quantity in quantities]
        discounts = [round(amount * rate) for amount in gross]
        total_gross = cents(units * price)
        total_discounts = cents(round(units * price * rate, 2))
        spread(total_discounts, discounts, weights, adjustable)
        fees = [
            round((amount - discount) * PAYMENT_FEE_RATE)
            for amount, discount in zip(gross, discounts, strict=True)
        ]
        total_fees = cents(round((total_gross - total_discounts) / 100 * PAYMENT_FEE_RATE, 2))
        spread(total_fees, fees, weights, adjustable)

        for index, quantity in enumerate(quantities):
            order_day = rng.randint(1, last_day)
            order_date = date(year, month_number, order_day)
            ship_date = min(
                order_date + timedelta(days=rng.randint(0, 3)), date(year, month_number, last_day)
            )
            lines.append({
                "product_id": product_id, "month": month, "order_date": order_date,
                "ship_date": ship_date, "quantity": quantity, "price": price,
                "discount": discounts[index], "fee": fees[index], "copies": weights[index],
                "status": "completed",
            })  # fmt: skip

        for _ in range(CANCELLED_PER_PRODUCT_MONTH):
            quantity = rng.choice([1, 1, 2])
            lines.append({
                "product_id": product_id, "month": month,
                "order_date": date(year, month_number, rng.randint(1, last_day)),
                "ship_date": None, "quantity": quantity, "price": price,
                "discount": round(cents(quantity * price) * rate), "fee": 0, "copies": 1,
                "status": "cancelled",
            })  # fmt: skip

    # Put the lines into orders: most orders have one line, some have two different products.
    lines.sort(key=lambda line: (line["order_date"], line["product_id"], line["quantity"]))
    order_number, line_number, index = 20000, 0, 0
    while index < len(lines):
        line = lines[index]
        order_number += 1
        group = [line]
        following = lines[index + 1] if index + 1 < len(lines) else None
        if (
            following and rng.random() < 0.15
            and following["order_date"] == line["order_date"]
            and following["product_id"] != line["product_id"]
            and following["status"] == line["status"] == "completed"
            and following["copies"] == line["copies"] == 1
        ):  # fmt: skip
            following["ship_date"] = line["ship_date"]
            group.append(following)
        for member in group:
            line_number += 1
            member["order_id"] = f"ORD-{order_number}"
            member["order_item_id"] = f"OI-{line_number:05d}"
        index += len(group)

    tables: dict[str, list[dict]] = {
        "products": [
            {"product_id": product_id, "product_name": values[0], "category": values[1]}
            for product_id, values in PRODUCTS.items()
        ],
        "orders": [], "order_items": [], "shipments": [], "payment_fees": [], "refunds": [],
        "product_costs": [
            {"product_id": product_id, "month": month, "unit_cost": f"{values[3]:.2f}"}
            for product_id, values in PRODUCTS.items() for month in MONTHS
            if (product_id, month) not in MISSING_COST
        ],
    }  # fmt: skip

    seen_orders = set()
    for line in lines:
        if line["order_id"] not in seen_orders:
            seen_orders.add(line["order_id"])
            tables["orders"].append({
                "order_id": line["order_id"], "order_date": line["order_date"].isoformat(),
                "status": line["status"],
            })  # fmt: skip
        fulfil, carrier = PRODUCTS[line["product_id"]][4:6]
        number = line["order_item_id"].split("-")[1]
        # A line that was loaded twice appears twice here, and so do its shipment and its fee.
        for _ in range(line["copies"]):
            tables["order_items"].append({
                "order_item_id": line["order_item_id"], "order_id": line["order_id"],
                "product_id": line["product_id"], "quantity": line["quantity"],
                "unit_list_price": f"{line['price']:.2f}",
                "discount_amount": f"{line['discount'] / 100:.2f}",
            })  # fmt: skip
            if line["status"] == "cancelled":
                continue
            tables["shipments"].append({
                "shipment_id": f"SHP-{number}", "order_item_id": line["order_item_id"],
                "product_id": line["product_id"], "ship_date": line["ship_date"].isoformat(),
                "pick_pack_cost": f"{line['quantity'] * fulfil:.2f}",
                "carrier_cost": f"{line['quantity'] * carrier:.2f}",
            })  # fmt: skip
            tables["payment_fees"].append({
                "fee_id": f"FEE-{number}", "order_item_id": line["order_item_id"],
                "product_id": line["product_id"], "capture_date": line["order_date"].isoformat(),
                "fee_amount": f"{line['fee'] / 100:.2f}",
            })  # fmt: skip

    tables["refunds"] = build_refunds(rng, lines)
    return tables


def build_refunds(rng: random.Random, lines: list[dict]) -> list[dict]:
    """Refunds that add up to each product's monthly refund total, counted in the refund month."""
    refundable = [line for line in lines if line["status"] == "completed" and line["copies"] == 1]
    refunds = []
    for (product_id, month), (_, rate, refund_total, return_cost) in MONTHLY.items():
        if refund_total == 0:
            continue
        year, month_number = (int(part) for part in month.split("-"))
        unit_paid = cents(PRODUCTS[product_id][2] * (1 - rate))
        total = cents(refund_total)

        if (product_id, month) == OVERSIZED_REFUND[:2]:
            oversized = cents(OVERSIZED_REFUND[2])
            count = 1 + round((total - oversized) / unit_paid)
            amounts = [oversized] + [unit_paid] * (count - 1)
        else:
            count = max(1, round(total / unit_paid))
            amounts = [unit_paid] * count
        amounts[-1] += total - sum(amounts)
        handling = [cents(return_cost) // count] * count
        handling[-1] += cents(return_cost) - sum(handling)

        same_month = [
            line
            for line in refundable
            if (line["product_id"], line["month"]) == (product_id, month)
        ]
        earlier = [
            line for line in refundable
            if line["product_id"] == product_id and line["month"] < month and line["order_date"].day >= 20
        ]  # fmt: skip
        for index, amount in enumerate(amounts):
            if (product_id, month) == TWO_REFUNDS_ON_ONE_LINE and index < 2:
                # Two refunds on the same line: a partial refund, then the rest.
                line = max(
                    same_month,
                    key=lambda candidate: (candidate["quantity"], candidate["order_item_id"]),
                )
            elif (product_id, month) == OVERSIZED_REFUND[:2] and index == 0:
                line = min(
                    same_month,
                    key=lambda candidate: (candidate["quantity"], candidate["order_item_id"]),
                )
            elif index == 0 and count >= 2 and earlier:
                line = rng.choice(earlier)  # ordered last month, refunded this month
            else:
                line = rng.choice(same_month)
            earliest = max(line["order_date"], date(year, month_number, 1)) + timedelta(days=1)
            last = date(year, month_number, calendar.monthrange(year, month_number)[1])
            refund_date = min(earliest + timedelta(days=rng.randint(0, 6)), last)
            refunds.append({
                "order_item_id": line["order_item_id"], "product_id": product_id,
                "refund_date": refund_date.isoformat(), "refund_amount": f"{amount / 100:.2f}",
                "return_handling_cost": f"{handling[index] / 100:.2f}",
            })  # fmt: skip

    refunds.sort(key=lambda refund: (refund["refund_date"], refund["order_item_id"]))
    return [
        {"refund_id": f"REF-{number:04d}", **refund}
        for number, refund in enumerate(refunds, start=1)
    ]


def write_source_data() -> dict[str, int]:
    """Write every source table to data/source/ and return the row counts."""
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, rows in build().items():
        with (SOURCE_DIR / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        counts[name] = len(rows)
    return counts


if __name__ == "__main__":
    for table, count in write_source_data().items():
        print(f"{table}: {count} rows")
    print(f"Written to {SOURCE_DIR}")
