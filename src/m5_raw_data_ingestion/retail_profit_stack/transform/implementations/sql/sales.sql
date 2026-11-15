-- sales: units, gross sales, and discounts by order month and product (LLD section 5).
-- Cancelled orders are left out. A line that appears twice is counted twice.
SELECT
    strftime(o.order_date, '%Y-%m') AS month,
    i.product_id,
    SUM(i.quantity) AS units_sold,
    SUM(i.quantity * i.unit_list_price) AS gross_sales,
    SUM(i.discount_amount) AS discounts
FROM order_items AS i
JOIN orders AS o ON o.order_id = i.order_id
WHERE o.status <> 'cancelled'
GROUP BY 1, 2
