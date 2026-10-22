-- Silver layer.
-- The data lake is source_schema.orders. This script is the transform.
-- The runner creates temp table eltl_run(run_id text) before these statements.

DELETE FROM silver.order_quarantine
WHERE run_id = (SELECT run_id FROM eltl_run);

DELETE FROM silver.order_line
WHERE run_id = (SELECT run_id FROM eltl_run);

CREATE TEMP TABLE eltl_judged ON COMMIT DROP AS
SELECT
    run_id,
    order_id,
    customer_id,
    product_id,
    sku,
    quantity,
    unit_price,
    total_amount,
    currency,
    status,
    channel,
    created_at,
    updated_at,
    ARRAY_REMOVE(ARRAY[
        CASE
            WHEN customer_id IS NULL OR customer_id <= 0
            THEN 'customer_id is required'
        END,
        CASE
            WHEN product_id IS NULL OR product_id <= 0
            THEN 'product_id is required'
        END,
        CASE
            WHEN sku IS NULL OR btrim(sku) = ''
            THEN 'sku is required'
        END,
        CASE
            WHEN quantity IS NULL OR quantity <= 0
            THEN 'quantity must be a positive integer'
        END,
        CASE
            WHEN unit_price IS NULL OR unit_price < 0
            THEN 'unit_price must be zero or positive'
        END,
        CASE
            WHEN currency IS NULL OR btrim(currency) = ''
            THEN 'currency is required'
            WHEN upper(btrim(currency)) <> 'USD'
            THEN 'currency must be USD'
        END,
        CASE
            WHEN status IS NULL
              OR btrim(status) = ''
              OR lower(btrim(status)) NOT IN
                 ('pending', 'paid', 'shipped', 'completed', 'cancelled')
            THEN 'status ' || coalesce(quote_literal(status), 'NULL')
                 || ' is not in the contract'
        END,
        CASE
            WHEN created_at IS NULL
              OR created_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
            THEN 'created_at must be a UTC timestamp'
        END
    ], NULL) AS reasons
FROM source_schema.orders
WHERE run_id = (SELECT run_id FROM eltl_run);

INSERT INTO silver.order_quarantine (
    run_id,
    order_id,
    customer_id,
    product_id,
    sku,
    quantity,
    unit_price,
    total_amount,
    currency,
    status,
    reasons
)
SELECT
    run_id,
    order_id,
    customer_id,
    product_id,
    sku,
    quantity,
    unit_price,
    total_amount,
    currency,
    status,
    reasons
FROM eltl_judged
WHERE cardinality(reasons) > 0;

INSERT INTO silver.order_line (
    run_id,
    order_id,
    customer_id,
    product_id,
    sku,
    quantity,
    unit_price,
    amount,
    currency,
    status,
    order_date,
    changes,
    warnings
)
SELECT
    run_id,
    order_id,
    customer_id,
    product_id,
    btrim(sku),
    quantity,
    unit_price,
    round(quantity * unit_price, 2),
    upper(btrim(currency)),
    lower(btrim(status)),
    left(created_at, 10)::date,
    ARRAY_REMOVE(ARRAY[
        CASE
            WHEN status IS DISTINCT FROM lower(btrim(status))
            THEN 'status ' || quote_literal(status) || ' → ' || lower(btrim(status))
        END,
        CASE
            WHEN currency IS DISTINCT FROM upper(btrim(currency))
            THEN 'currency ' || quote_literal(currency) || ' → ' || upper(btrim(currency))
        END,
        CASE
            WHEN total_amount IS DISTINCT FROM round(quantity * unit_price, 2)
            THEN 'amount recomputed ' || total_amount::text || ' → '
                 || round(quantity * unit_price, 2)::text
        END,
        CASE
            WHEN channel IS NOT NULL AND btrim(channel) <> ''
            THEN 'dropped channel ' || quote_literal(channel)
        END
    ], NULL),
    CASE
        WHEN updated_at < created_at
        THEN ARRAY['updated_at precedes created_at; order_date uses created_at']
        ELSE ARRAY[]::text[]
    END
FROM eltl_judged
WHERE cardinality(reasons) = 0;
