-- Check: duplicate_records
-- Finds every copy of a record after the first. Two rows are copies when every column is equal.
-- copy_number is 1 for the first copy, 2 for the second, and so on. We return the rows above 1.

WITH order_item_copies AS (
    SELECT i.row_number, i.product_id, o.order_date AS counted_on,
           row_number() OVER (
               PARTITION BY i.order_item_id, i.order_id, i.product_id, i.quantity,
                            i.unit_list_price, i.discount_amount
               ORDER BY i.row_number
           ) AS copy_number
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
),
shipment_copies AS (
    SELECT row_number, product_id, ship_date AS counted_on,
           row_number() OVER (
               PARTITION BY shipment_id, order_item_id, product_id, ship_date,
                            pick_pack_cost, carrier_cost
               ORDER BY row_number
           ) AS copy_number
    FROM shipments
),
fee_copies AS (
    SELECT row_number, product_id, capture_date AS counted_on,
           row_number() OVER (
               PARTITION BY fee_id, order_item_id, product_id, capture_date, fee_amount
               ORDER BY row_number
           ) AS copy_number
    FROM payment_fees
),
refund_copies AS (
    SELECT row_number, product_id, refund_date AS counted_on,
           row_number() OVER (
               PARTITION BY refund_id, order_item_id, product_id, refund_date,
                            refund_amount, return_handling_cost
               ORDER BY row_number
           ) AS copy_number
    FROM refunds
),
all_copies AS (
    SELECT 'order_items' AS source_table, * FROM order_item_copies
    UNION ALL SELECT 'shipments', * FROM shipment_copies
    UNION ALL SELECT 'payment_fees', * FROM fee_copies
    UNION ALL SELECT 'refunds', * FROM refund_copies
)
SELECT strftime(counted_on, '%Y-%m') AS month,
       product_id,
       source_table,
       row_number,
       'This row is copy number ' || copy_number || ' of the same record.' AS detail
FROM all_copies
WHERE copy_number > 1
