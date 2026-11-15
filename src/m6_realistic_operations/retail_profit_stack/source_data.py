"""Generate the business's records: orders, lines, refunds, shipments, fees, and costs.

Implements LLD section 3 (Planted problems). The records are fictional. They are built so that
the profit calculated from them equals milestone 1's prepared figures exactly: this module
starts from the same monthly inputs per product and spreads them over individual orders.

The files are the same every time, because the random choices use a fixed seed.

Run it with:  uv run python -m retail_profit_stack.source_data
"""

import calendar
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from retail_profit_stack.config import LANDING_DIR, LATE_DIR

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

# ---- The seven problems planted on purpose (LLD section 3) -------------------
# The first three were already in milestone 2's records.
MISSING_COST = {("P007", "2026-10")}  # 1: no cost for the camp stove in October
DUPLICATED = ("P001", "2026-10", 3)  # 2: three lines sent twice, on different days
OVERSIZED_REFUND = ("P011", "2026-09", 60.0)  # 3: a $60 refund on a $25 line
# The next four are new in milestone 3. They are added after everything else is built.
BATCH_LOADED_TWICE = ("P002", "2026-10", 4)  # 4: four lines from one day, all loaded twice
REFUND_SENT_TWICE = ("P005", "2026-09")  # 5: one refund that appears twice
REFUND_BEFORE_ORDER = ("P003", "2026-10", 12)  # 6: a refund dated 12 days before its order
SHIPPED_BEFORE_ORDER = ("P009", "2026-09", 1)  # 7: a shipment dated 1 day before its order
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
    plant_new_problems(tables)
    return tables


def repeat_rows(rows: list[dict], column: str, values: set[str]) -> list[dict]:
    """Return the rows with a second copy after every row whose column is one of the values."""
    result = []
    for row in rows:
        result.append(row)
        if row[column] in values:
            result.append(dict(row))
    return result


def plant_new_problems(tables: dict[str, list[dict]]) -> None:
    """Add problems 4 to 7 to the finished tables. None of them changes a kept total."""
    order_date = {
        row["order_id"]: date.fromisoformat(row["order_date"]) for row in tables["orders"]
    }
    line_date = {row["order_item_id"]: order_date[row["order_id"]] for row in tables["order_items"]}
    refunded_lines = {row["order_item_id"] for row in tables["refunds"]}

    # 4. A batch loaded twice: four lines of one product, all ordered on the same day.
    product_id, month, count = BATCH_LOADED_TWICE
    lines_by_day: dict[date, list[str]] = {}
    for row in tables["shipments"]:  # a shipped line is a completed line
        line = row["order_item_id"]
        day = line_date[line]
        in_month = row["product_id"] == product_id and day.isoformat().startswith(month)
        if in_month and line not in refunded_lines:
            lines_by_day.setdefault(day, []).append(line)
    batch_day = min(day for day, lines in lines_by_day.items() if len(lines) >= count)
    batch = set(sorted(lines_by_day[batch_day])[:count])
    for table in ("order_items", "shipments", "payment_fees"):
        tables[table] = repeat_rows(tables[table], "order_item_id", batch)

    # 5. One refund sent twice.
    product_id, month = REFUND_SENT_TWICE
    refund = next(
        row for row in tables["refunds"]
        if row["product_id"] == product_id and row["refund_date"].startswith(month)
    )  # fmt: skip
    tables["refunds"] = repeat_rows(tables["refunds"], "refund_id", {refund["refund_id"]})

    # 6. A refund dated before its order. The date stays in the same month.
    product_id, month, days = REFUND_BEFORE_ORDER
    refund = next(
        row for row in tables["refunds"]
        if row["product_id"] == product_id and row["refund_date"].startswith(month)
        and line_date[row["order_item_id"]].isoformat().startswith(month)
        and line_date[row["order_item_id"]].day > days
    )  # fmt: skip
    refund["refund_date"] = (line_date[refund["order_item_id"]] - timedelta(days=days)).isoformat()

    # 7. A shipment dated before its order. The date stays in the same month.
    product_id, month, days = SHIPPED_BEFORE_ORDER
    shipment = next(
        row for row in tables["shipments"]
        if row["product_id"] == product_id and row["ship_date"].startswith(month)
        and line_date[row["order_item_id"]].day > days
        and row["order_item_id"] not in refunded_lines
    )  # fmt: skip
    shipment["ship_date"] = (
        line_date[shipment["order_item_id"]] - timedelta(days=days)
    ).isoformat()


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


# ---- New in milestone 5: the records arrive as files (LLD section 3) ----------

# Which column holds the date that decides a record's week. Order lines go with their order.
DATE_COLUMN = {
    "orders": "order_date",
    "refunds": "refund_date",
    "shipments": "ship_date",
    "payment_fees": "capture_date",
}

# The seven planted file problems. Each names the files it touches.
RESENT_FILE = "orders_2026-09-14"  # 1: the same content again, under a new name
REORDERED_FILE = "refunds_2026-09-21"  # 2: the same columns in a different order
EXTRA_COLUMN_FROM = ("shipments", "2026-10-05")  # 3: an extra column from this week on
INCOMPLETE_FILE = "refunds_2026-10-12"  # 4: a column is missing; a complete file follows
RENAMED_FROM = {  # 5, 6: columns renamed from this week on
    "order_items": ("2026-10-12", {"unit_list_price": "list_price", "discount_amount": "discount"}),
    "payment_fees": ("2026-10-19", {"fee_amount": "fee_usd"}),
}
NO_CLUE_FILE = ("shipments_2026-10-26", {"pick_pack_cost": "cost_1", "carrier_cost": "cost_2"})  # 7


def week_start(day: str) -> str:
    """The Monday of the week a date falls in, as text like 2026-10-05."""
    parsed = date.fromisoformat(day)
    return (parsed - timedelta(days=parsed.weekday())).isoformat()


def split_into_files(tables: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Split the tables into files: file name (without .csv) -> its rows, in the tables' order."""
    files: dict[str, list[dict]] = {"products": tables["products"]}
    for row in tables["product_costs"]:
        files.setdefault(f"product_costs_{row['month']}", []).append(row)
    for feed, date_column in DATE_COLUMN.items():
        for row in tables[feed]:
            files.setdefault(f"{feed}_{week_start(row[date_column])}", []).append(row)
    order_dates = {order["order_id"]: order["order_date"] for order in tables["orders"]}
    for row in tables["order_items"]:
        week = week_start(order_dates[row["order_id"]])
        files.setdefault(f"order_items_{week}", []).append(row)
    return files


def renamed(rows: list[dict], names: dict[str, str]) -> list[dict]:
    """The same rows with some columns given new names."""
    return [{names.get(column, column): value for column, value in row.items()} for row in rows]


def plant_file_problems(files: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Plant the seven file problems. The records themselves are not changed."""
    planted = {}
    for name, rows in files.items():
        feed, _, week = name.rpartition("_")
        # 5 and 6: renamed columns from a certain week on.
        if feed in RENAMED_FROM and week >= RENAMED_FROM[feed][0]:
            rows = renamed(rows, RENAMED_FROM[feed][1])
        # 3: an extra column from a certain week on.
        if feed == EXTRA_COLUMN_FROM[0] and week >= EXTRA_COLUMN_FROM[1]:
            rows = [{**row, "warehouse_code": "WH-EAST"} for row in rows]
        # 7: one file whose new column names give no clue.
        if name == NO_CLUE_FILE[0]:
            rows = renamed(rows, NO_CLUE_FILE[1])
        # 2: the same columns in a different order.
        if name == REORDERED_FILE:
            rows = [dict(reversed(list(row.items()))) for row in rows]
        # 4: a file with a column missing. The complete file arrives under a new name.
        if name == INCOMPLETE_FILE:
            planted[f"{name}_complete"] = rows
            rows = [
                {column: value for column, value in row.items() if column != "return_handling_cost"}
                for row in rows
            ]
        planted[name] = rows
        # 1: the same content sent again under a new name.
        if name == RESENT_FILE:
            planted[f"{name}_resend"] = rows
    return planted


def write_landing_files(landing_dir: Path = LANDING_DIR) -> dict[str, int]:
    """Write every file to the landing folder and return each file's row count.

    The folder is cleared first, so the same seed always leaves the same files.
    """
    if landing_dir.exists():
        for old_file in landing_dir.glob("*.csv"):
            old_file.unlink()
    landing_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    files = plant_file_problems(split_into_files(build()))
    for name, rows in sorted(files.items()):
        with (landing_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        counts[f"{name}.csv"] = len(rows)
    return counts


# ---- New in milestone 6: three files that arrive after month-end close (LLD section 3) ----

LATE_REFUND_PRODUCT = "P012"  # the fleece pullover: a September refund that arrives in November
LATE_REFUND_FILE = "refunds_2026-11-09"
CORRECTED_FILE = "shipments_2026-10-19"  # sent again with one carrier cost corrected
CORRECTED_CARRIER_COST = "9.00"
LATE_COST_FILE = "product_costs_2026-10_late"  # the camp stove's October cost, missing until now


def late_files() -> dict[str, list[dict]]:
    """The three late files: file name (without .csv) -> its rows. Same seed, same files."""
    tables = build()
    order_dates = {order["order_id"]: order["order_date"] for order in tables["orders"]}
    completed = {order["order_id"] for order in tables["orders"] if order["status"] != "cancelled"}
    refunded = {refund["order_item_id"] for refund in tables["refunds"]}

    # 1. A late refund: the first September fleece pullover line that has no refund yet.
    line = next(
        item for item in tables["order_items"]
        if item["product_id"] == LATE_REFUND_PRODUCT
        and order_dates[item["order_id"]].startswith("2026-09")
        and item["order_id"] in completed
        and item["order_item_id"] not in refunded
    )  # fmt: skip
    value = int(line["quantity"]) * float(line["unit_list_price"]) - float(line["discount_amount"])
    late_refund = {
        "refund_id": "REF-9001", "order_item_id": line["order_item_id"],
        "product_id": LATE_REFUND_PRODUCT, "refund_date": "2026-09-25",
        "refund_amount": f"{value:.2f}", "return_handling_cost": "5.00",
    }  # fmt: skip

    # 2. A correction: the shipments file of 19 October again, with its first carrier cost fixed.
    corrected = [dict(row) for row in plant_file_problems(split_into_files(tables))[CORRECTED_FILE]]
    corrected[0]["carrier_cost"] = CORRECTED_CARRIER_COST

    # 3. The cost that was missing: the camp stove in October, at September's cost.
    stove, month = next(iter(MISSING_COST))
    late_cost = {"product_id": stove, "month": month, "unit_cost": f"{PRODUCTS[stove][3]:.2f}"}

    return {LATE_REFUND_FILE: [late_refund], CORRECTED_FILE: corrected, LATE_COST_FILE: [late_cost]}


def write_late_files(late_dir: Path = LATE_DIR) -> dict[str, int]:
    """Write the three late files to their own folder and return each file's row count."""
    if late_dir.exists():
        for old_file in late_dir.glob("*.csv"):
            old_file.unlink()
    late_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, rows in sorted(late_files().items()):
        with (late_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        counts[f"{name}.csv"] = len(rows)
    return counts


if __name__ == "__main__":
    written = write_landing_files()
    print(f"Wrote {len(written)} files and {sum(written.values())} rows to {LANDING_DIR}")
    late = write_late_files()
    print(f"Wrote {len(late)} late files to {LATE_DIR}")
