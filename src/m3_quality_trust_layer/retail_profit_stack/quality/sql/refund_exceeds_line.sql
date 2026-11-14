-- Check: refund_exceeds_line
-- Finds each refund that is larger than the value of the order line it refunds.
-- A line's value is quantity x list price, less its discount.

WITH line_values AS (
    SELECT DISTINCT order_item_id,
           quantity * unit_list_price - discount_amount AS line_value
    FROM order_items
)
SELECT strftime(r.refund_date, '%Y-%m') AS month,
       r.product_id,
       'refunds' AS source_table,
       r.row_number,
       'Refund of ' || printf('%.2f', r.refund_amount)
           || ' on a line worth ' || printf('%.2f', l.line_value) || '.' AS detail
FROM refunds AS r JOIN line_values AS l ON l.order_item_id = r.order_item_id
WHERE r.refund_amount > l.line_value + 0.005
