# Data quality rulebook

Kestrel Ridge Outfitters. This rulebook is for whoever investigates a data quality finding.

A **finding** is a problem that a quality check found in the business's records. Each finding belongs to one check, one product, and one month.

For each check, this rulebook says what the check means, what the system has already done, and the usual causes. Each cause has a **sign**: something you can see in the records that points to it. To investigate a finding, look at its records and choose the one cause whose sign matches.

Use the cause names exactly as they are written here.

## duplicate_records

**What it means.** The same record appears more than once. Every column is equal.

**What the system has done.** Quarantine. The first copy is kept. The extra copies are set aside and are not in the figures.

**Usual causes.**

| Cause | Sign |
|---|---|
| `batch_loaded_twice` | Three or more records are duplicated, and their orders all have the same order date. A whole day's file was loaded two times. |
| `single_record_resent` | Only one record is duplicated, or the duplicated records belong to orders with different order dates. A system sent single records a second time. |

## missing_product_cost

**What it means.** A product was sold in a month, but there is no cost for that product in that month.

**What the system has done.** Needs review. The product's gross profit and contribution profit are shown as unavailable.

**Usual causes.**

| Cause | Sign |
|---|---|
| `monthly_cost_not_updated` | The product has a cost for an earlier month. This month's cost was not entered. |
| `product_never_costed` | The product has no cost in any month. It was never set up. |

## event_out_of_order

**What it means.** A refund or a shipment is dated before the order it belongs to. That cannot really happen.

**What the system has done.** Needs review. The record is still counted.

**Usual causes.**

| Cause | Sign |
|---|---|
| `order_recorded_late` | The refund or shipment is dated exactly one day before the order. The order was written up the day after it was placed. |
| `date_typed_wrong` | The refund or shipment is dated two or more days before the order. Someone typed a wrong date. |

## refund_exceeds_line

**What it means.** A refund is larger than the value of the order line it refunds. A line's value is quantity × list price, less its discount.

**What the system has done.** Needs review. The refund is still counted.

**Usual causes.**

| Cause | Sign |
|---|---|
| `whole_order_refunded_on_one_line` | The order has more than one line, and the refund equals the value of all its lines together. The whole order was refunded against one line. |
| `amount_typed_wrong` | Anything else. Someone typed a wrong amount. |

## totals_do_not_match

**What it means.** A total in the profit table differs from the total of the records it was calculated from.

**What the system has done.** Needs review. The figure cannot be trusted.

**Usual causes.**

| Cause | Sign |
|---|---|
| `calculation_lost_records` | This is always the cause. The calculation dropped or repeated records. |
