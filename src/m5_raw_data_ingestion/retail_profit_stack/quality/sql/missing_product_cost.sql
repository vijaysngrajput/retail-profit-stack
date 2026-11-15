-- Check: missing_product_cost
-- Finds each product and month that has sales but no row in product_costs.
-- There is no bad row to point at, because the problem is a row that is not there.

WITH sold AS (
    SELECT DISTINCT strftime(o.order_date, '%Y-%m') AS month, i.product_id
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
    WHERE o.status <> 'cancelled'
)
SELECT sold.month,
       sold.product_id,
       'product_costs' AS source_table,
       NULL AS row_number,
       'No cost row for this product in this month.' AS detail
FROM sold
LEFT JOIN product_costs AS c ON c.product_id = sold.product_id AND c.month = sold.month
WHERE c.unit_cost IS NULL
