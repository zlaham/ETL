-- Copy this lesson's lake batches into typed stg_ tables.
-- The runner fills temp table eltl_batch(batch_id, source_system) first.
-- Which rows are changes was decided by the watermark at extract. This script does not filter again.

INSERT INTO stg.stg_customer (
    batch_id, landing_id, customer_email_pk_id,
    country, region, customer_segment, account_plan, account_status, preferred_currency,
    source_updated_at
)
SELECT
    batch_id,
    landing_id,
    md5(lower(btrim(payload->>'email_address'))),
    payload->>'country',
    payload->>'region',
    payload->>'customer_segment',
    payload->>'account_plan',
    payload->>'account_status',
    payload->>'preferred_currency',
    source_updated_at
FROM accounts.raw_customer
WHERE batch_id IN (SELECT batch_id FROM eltl_batch WHERE source_system = 'structured');

INSERT INTO stg.stg_catalog (
    batch_id, product_id, sku, category, list_price, source_updated_at
)
SELECT
    batch_id,
    payload->>'product_id',
    payload->>'sku',
    payload->>'category',
    (payload->>'list_price')::numeric(12, 2),
    source_updated_at
FROM catalog.raw_catalog
WHERE batch_id IN (SELECT batch_id FROM eltl_batch WHERE source_system = 'api');

INSERT INTO stg.stg_order (
    batch_id, order_id, customer_email_pk_id, sku, status, quantity, source_updated_at
)
SELECT
    batch_id,
    payload->>'order_id',
    md5(lower(btrim(payload->>'email_address'))),
    payload->>'sku',
    payload->>'status',
    (payload->>'quantity')::integer,
    source_updated_at
FROM orders.raw_order
WHERE batch_id IN (SELECT batch_id FROM eltl_batch WHERE source_system = 'mongo');
