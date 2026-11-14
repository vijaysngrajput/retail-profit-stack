-- Lineage: one row for each kept record and each term it adds to (LLD section 4).
-- The rules are the same as the transformations: which month a record counts in, and
-- that lines of cancelled orders are left out.
-- Every source table here has a row_number column, added when the records were loaded.

WITH kept_lines AS (
    -- Order lines that count, with the month of their order.
    SELECT strftime(o.order_date, '%Y-%m') AS month, i.*
    FROM order_items AS i
    JOIN orders AS o ON o.order_id = i.order_id
    WHERE o.status <> 'cancelled'
),
units AS (
    SELECT month, product_id, sum(quantity) AS units_sold
    FROM kept_lines
    GROUP BY month, product_id
)

-- Order lines add units, gross sales, and discounts.
SELECT month, product_id, 'units_sold' AS term, 'order_items' AS source_table, row_number,
       order_item_id AS record_id, CAST(quantity AS DOUBLE) AS amount
FROM kept_lines
UNION ALL
SELECT month, product_id, 'gross_sales', 'order_items', row_number, order_item_id,
       quantity * unit_list_price
FROM kept_lines
UNION ALL
SELECT month, product_id, 'discounts', 'order_items', row_number, order_item_id,
       discount_amount
FROM kept_lines

-- Refunds add to refunds and to return cost, in the month of the refund.
UNION ALL
SELECT strftime(refund_date, '%Y-%m'), product_id, 'refunds', 'refunds', row_number,
       refund_id, refund_amount
FROM refunds
UNION ALL
SELECT strftime(refund_date, '%Y-%m'), product_id, 'return_cost', 'refunds', row_number,
       refund_id, return_handling_cost
FROM refunds

-- Shipments add to fulfilment cost and shipping cost, in the month they shipped.
UNION ALL
SELECT strftime(ship_date, '%Y-%m'), product_id, 'fulfillment_cost', 'shipments', row_number,
       shipment_id, pick_pack_cost
FROM shipments
UNION ALL
SELECT strftime(ship_date, '%Y-%m'), product_id, 'shipping_cost', 'shipments', row_number,
       shipment_id, carrier_cost
FROM shipments

-- Payment fees count in the month the payment was captured.
UNION ALL
SELECT strftime(capture_date, '%Y-%m'), product_id, 'payment_fees', 'payment_fees',
       row_number, fee_id, fee_amount
FROM payment_fees

-- The product's cost row for the month. Its amount is the unit cost times the units sold.
UNION ALL
SELECT c.month, c.product_id, 'product_cost', 'product_costs', c.row_number,
       c.product_id || '/' || c.month, c.unit_cost * u.units_sold
FROM product_costs AS c
JOIN units AS u ON u.month = c.month AND u.product_id = c.product_id

ORDER BY month, product_id, term, source_table, row_number
