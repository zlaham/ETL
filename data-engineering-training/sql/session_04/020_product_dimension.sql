-- dim_product: one row per product version.
-- The category published by Session 3 is version 1.
-- A later merchandising reclass is a new version. It does not move old sales.

CREATE OR REPLACE TABLE product_version_plan AS
WITH reclass AS (
    SELECT
        product_id,
        new_value AS category,
        CAST(effective_from AS DATE) AS effective_from,
        reason
    FROM product_changes
    WHERE change_type = 'type2'
      AND attribute = 'category'
),
initial AS (
    SELECT
        products.product_id,
        products.sku,
        products.product_name,
        products.category,
        products.subcategory,
        products.enrichment_method,
        CAST(products.source_updated_at AS DATE) AS effective_from,
        1 AS version_number,
        'initial_publish' AS change_reason
    FROM silver_products AS products
),
reclassified AS (
    SELECT
        products.product_id,
        products.sku,
        products.product_name,
        reclass.category,
        products.subcategory,
        'manual' AS enrichment_method,
        reclass.effective_from,
        2 AS version_number,
        reclass.reason AS change_reason
    FROM silver_products AS products
    JOIN reclass ON reclass.product_id = products.product_id
),
combined AS (
    SELECT * FROM initial
    UNION ALL
    SELECT * FROM reclassified
),
sequenced AS (
    SELECT
        *,
        LEAD(effective_from) OVER (
            PARTITION BY product_id
            ORDER BY version_number
        ) AS next_effective_from
    FROM combined
)
SELECT
    product_id,
    sku,
    product_name,
    category,
    subcategory,
    enrichment_method,
    effective_from,
    CAST(next_effective_from - INTERVAL 1 DAY AS DATE) AS effective_to,
    next_effective_from IS NULL AS is_current,
    version_number,
    change_reason
FROM sequenced;

CREATE OR REPLACE TEMP TABLE product_keys_phase1 AS
SELECT
    products.product_id AS business_key,
    1 AS version_number,
    base.max_key + ROW_NUMBER() OVER (ORDER BY products.product_id) AS surrogate_key
FROM silver_products AS products
CROSS JOIN (
    SELECT COALESCE(MAX(surrogate_key), 0) AS max_key
    FROM surrogate_registry
    WHERE entity_name = 'product'
) AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM surrogate_registry AS registry
    WHERE registry.entity_name = 'product'
      AND registry.business_key = products.product_id
      AND registry.version_number = 1
);

INSERT INTO surrogate_registry
SELECT 'product', business_key, version_number, surrogate_key
FROM product_keys_phase1;

CREATE OR REPLACE TEMP TABLE product_keys_phase2 AS
SELECT
    plan.product_id AS business_key,
    plan.version_number,
    base.max_key + ROW_NUMBER() OVER (
        ORDER BY plan.effective_from, plan.product_id, plan.version_number
    ) AS surrogate_key
FROM product_version_plan AS plan
CROSS JOIN (
    SELECT COALESCE(MAX(surrogate_key), 0) AS max_key
    FROM surrogate_registry
    WHERE entity_name = 'product'
) AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM surrogate_registry AS registry
    WHERE registry.entity_name = 'product'
      AND registry.business_key = plan.product_id
      AND registry.version_number = plan.version_number
);

INSERT INTO surrogate_registry
SELECT 'product', business_key, version_number, surrogate_key
FROM product_keys_phase2;

CREATE OR REPLACE TABLE dim_product AS
SELECT
    registry.surrogate_key AS product_key,
    plan.product_id,
    plan.sku,
    plan.product_name,
    plan.category,
    plan.subcategory,
    plan.enrichment_method,
    plan.effective_from,
    plan.effective_to,
    plan.is_current,
    plan.version_number,
    plan.change_reason
FROM product_version_plan AS plan
JOIN surrogate_registry AS registry
  ON registry.entity_name = 'product'
 AND registry.business_key = plan.product_id
 AND registry.version_number = plan.version_number
UNION ALL
SELECT
    -1,
    'UNKNOWN',
    NULL,
    'Unknown product',
    'Unknown',
    NULL,
    'unknown_member',
    DATE '1900-01-01',
    NULL,
    TRUE,
    0,
    'unknown_member';
