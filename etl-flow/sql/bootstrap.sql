-- Database layout for the ELTL pipeline.
-- source_schema is the data lake. silver and gold are filled by the SQL scripts.

CREATE SCHEMA IF NOT EXISTS source_schema;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

COMMENT ON SCHEMA source_schema IS 'Data lake. Each extract is loaded here before any cleaning.';
COMMENT ON SCHEMA silver IS 'Conformed tables. sql/silver scripts are the only writers.';
COMMENT ON SCHEMA gold IS 'Serving tables loaded from silver by sql/gold scripts.';

CREATE TABLE IF NOT EXISTS source_schema.load_run (
    run_id text PRIMARY KEY,
    source_system text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    duration_ms integer NOT NULL
);

CREATE TABLE IF NOT EXISTS source_schema.orders (
    landing_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES source_schema.load_run (run_id),
    source_system text NOT NULL,
    page_number integer NOT NULL,
    ingested_at timestamptz NOT NULL,
    order_id integer NOT NULL,
    customer_id integer,
    product_id integer,
    sku text,
    quantity integer,
    unit_price numeric(12, 2),
    total_amount numeric(12, 2),
    currency text,
    status text,
    channel text,
    created_at text,
    updated_at text,
    payload jsonb NOT NULL,
    UNIQUE (run_id, order_id)
);

COMMENT ON TABLE source_schema.orders IS
    'Operational orders loaded as they arrived. payload is the source document.';

CREATE TABLE IF NOT EXISTS silver.order_quarantine (
    run_id text NOT NULL,
    order_id integer NOT NULL,
    customer_id integer,
    product_id integer,
    sku text,
    quantity integer,
    unit_price numeric(12, 2),
    total_amount numeric(12, 2),
    currency text,
    status text,
    reasons text[] NOT NULL,
    PRIMARY KEY (run_id, order_id)
);

CREATE TABLE IF NOT EXISTS silver.order_line (
    run_id text NOT NULL,
    order_id integer NOT NULL,
    customer_id integer NOT NULL,
    product_id integer NOT NULL,
    sku text NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12, 2) NOT NULL,
    amount numeric(12, 2) NOT NULL,
    currency text NOT NULL,
    status text NOT NULL,
    order_date date NOT NULL,
    changes text[] NOT NULL,
    warnings text[] NOT NULL,
    PRIMARY KEY (run_id, order_id),
    CONSTRAINT order_line_quantity_ck CHECK (quantity > 0),
    CONSTRAINT order_line_price_ck CHECK (unit_price >= 0),
    CONSTRAINT order_line_amount_ck CHECK (amount = round(quantity * unit_price, 2)),
    CONSTRAINT order_line_currency_ck CHECK (currency = 'USD'),
    CONSTRAINT order_line_status_ck CHECK (
        status IN ('pending', 'paid', 'shipped', 'completed', 'cancelled')
    )
);

COMMENT ON TABLE silver.order_line IS
    'One current silver line per order in a run. Built from source_schema.orders.';

CREATE TABLE IF NOT EXISTS gold.fact_sales (
    fact_id integer NOT NULL,
    run_id text NOT NULL,
    order_id integer NOT NULL,
    customer_id integer NOT NULL,
    product_id integer NOT NULL,
    sku text NOT NULL,
    order_date date NOT NULL,
    status text NOT NULL,
    currency text NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12, 2) NOT NULL,
    amount numeric(12, 2) NOT NULL,
    PRIMARY KEY (run_id, fact_id),
    UNIQUE (run_id, order_id),
    CONSTRAINT fact_sales_quantity_ck CHECK (quantity > 0),
    CONSTRAINT fact_sales_price_ck CHECK (unit_price >= 0),
    CONSTRAINT fact_sales_amount_ck CHECK (amount = round(quantity * unit_price, 2)),
    CONSTRAINT fact_sales_currency_ck CHECK (currency = 'USD'),
    CONSTRAINT fact_sales_status_ck CHECK (status IN ('paid', 'shipped', 'completed'))
);

COMMENT ON TABLE gold.fact_sales IS
    'Revenue lines loaded from silver.order_line.';

CREATE TABLE IF NOT EXISTS gold.load_exclusion (
    run_id text NOT NULL,
    order_id integer NOT NULL,
    sku text NOT NULL,
    status text NOT NULL,
    order_date date NOT NULL,
    amount numeric(12, 2) NOT NULL,
    reason text NOT NULL,
    PRIMARY KEY (run_id, order_id),
    CONSTRAINT load_exclusion_status_ck CHECK (status IN ('pending', 'cancelled'))
);

COMMENT ON TABLE gold.load_exclusion IS
    'Valid silver rows that stay out of fact_sales.';
