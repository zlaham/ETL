-- Whole catalog when the first flag is true.
-- Otherwise rows strictly after the watermark. The extractor always passes false.

SELECT product_id, sku, category, list_price, updated_at
FROM ops.catalog_product
WHERE %s OR (updated_at, product_id) > (%s, %s)
ORDER BY updated_at, product_id
LIMIT %s;
