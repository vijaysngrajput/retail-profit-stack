-- product_cost: units sold times unit cost (LLD section 5).
-- LEFT JOIN keeps every sales row. With no cost row, product_cost is null, never zero.
SELECT
    s.month,
    s.product_id,
    s.units_sold * c.unit_cost AS product_cost
FROM sales AS s
LEFT JOIN product_costs AS c
    ON c.product_id = s.product_id AND c.month = s.month
