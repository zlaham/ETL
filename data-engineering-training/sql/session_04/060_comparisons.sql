-- Two readings of the same fact. as_was uses the key stored on the row.
-- as_is joins onward to the current version. Gold publishes as_was.
-- as_is is a labeled comparison, not a second mart.

CREATE OR REPLACE VIEW cmp_category_history AS
WITH as_was AS (
    SELECT
        products.category,
        CAST(SUM(facts.gross_amount) AS DECIMAL(12, 2)) AS as_was_revenue
    FROM fct_sales_order_lines AS facts
    JOIN dim_product AS products ON products.product_key = facts.product_key
    GROUP BY products.category
),
as_is AS (
    SELECT
        current_product.category,
        CAST(SUM(facts.gross_amount) AS DECIMAL(12, 2)) AS as_is_revenue
    FROM fct_sales_order_lines AS facts
    JOIN dim_product AS historical ON historical.product_key = facts.product_key
    JOIN dim_product AS current_product
      ON current_product.product_id = historical.product_id
     AND current_product.is_current
    GROUP BY current_product.category
)
SELECT
    COALESCE(as_was.category, as_is.category) AS category,
    as_was.as_was_revenue,
    as_is.as_is_revenue
FROM as_was
FULL OUTER JOIN as_is USING (category);

CREATE OR REPLACE VIEW cmp_smartphone_segment_history AS
WITH lines AS (
    SELECT
        historical.customer_segment AS as_was_segment,
        current_customer.customer_segment AS as_is_segment,
        facts.gross_amount
    FROM fct_sales_order_lines AS facts
    JOIN dim_product AS products ON products.product_key = facts.product_key
    JOIN dim_customer AS historical ON historical.customer_key = facts.customer_key
    JOIN dim_customer AS current_customer
      ON current_customer.customer_id = historical.customer_id
     AND current_customer.is_current
    WHERE products.category = 'Smartphones'
)
SELECT
    'as_was' AS reading,
    as_was_segment AS customer_segment,
    CAST(SUM(gross_amount) AS DECIMAL(12, 2)) AS revenue
FROM lines
GROUP BY as_was_segment
UNION ALL
SELECT
    'as_is',
    as_is_segment,
    CAST(SUM(gross_amount) AS DECIMAL(12, 2))
FROM lines
GROUP BY as_is_segment;

-- Not a published return. Shows the keys a return of Priya's phone would use
-- if it were processed on 18 October, after her segment change.
CREATE OR REPLACE VIEW scenario_c101_phone_return AS
SELECT
    sale.order_line_id,
    sale.customer_key AS sale_customer_key,
    sale_customer.customer_segment AS sale_segment,
    return_customer.customer_key AS return_customer_key,
    return_customer.customer_segment AS return_segment,
    sale.gross_amount
FROM fct_sales_order_lines AS sale
JOIN dim_customer AS sale_customer ON sale_customer.customer_key = sale.customer_key
JOIN dim_customer AS return_customer
  ON return_customer.customer_id = sale_customer.customer_id
 AND version_covers(return_customer.effective_from, return_customer.effective_to, DATE '2026-10-18')
WHERE sale.order_line_id = 'OL-1002-1';
