# ETL lesson

The screen is the three sources. Each card names the technology, then shows the rows that mock returns.

- Accounts: PostgreSQL `ops.customer_account`
- Catalog: `GET /api/sources/catalog`
- Orders: MongoDB `etl_lesson.order_events`

Each source lands in its own schema: `accounts`, `catalog`, or `orders`. `stg_` extracts the jsonb keys from that one table. `reportingdw.dim_customer`, `dim_product`, and `dim_date` conform those keys. `reportingdw.fct_order` is the join.

1. Accounts from `ops.customer_account`.
2. Catalog from `GET /api/sources/catalog`. The extractor calls that HTTP route.
3. Orders from MongoDB database `etl_lesson`, collection `order_events`.
4. `sql/staging/010_stg_changes.sql` writes `stg.stg_customer`, `stg.stg_catalog`, and `stg.stg_order`.

## API

```powershell
cd etl-flow\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8020
```

Connection string: `etl-flow/backend/.env` as `DATABASE_URL`. Copy `.env.example` and point it at local database `etl_flow`.

Swagger: http://127.0.0.1:8020/docs

Port 8000 is left alone.

## UI

```powershell
cd etl-flow\frontend
npm install
npm run dev
```

App: http://127.0.0.1:5173

The Vite proxy sends `/api` to http://127.0.0.1:8020.

## Both

From `etl-flow`, after the two installs:

```powershell
npm run dev
```

## pgAdmin

Refresh the local server on localhost port 5432. Open database `etl_flow`.

| Schema | What it holds |
| --- | --- |
| `ops` | `customer_account` and `catalog_product` |
| `accounts` | `raw_customer`, landing for the Accounts source |
| `catalog` | `raw_catalog`, landing for the Catalog source |
| `orders` | `raw_order`, landing for the Orders source |
| `stg` | `stg_customer`, `stg_catalog`, `stg_order` |
| `reportingdw` | `dim_customer`, `dim_product`, `dim_date`, `fct_order` |
| `ingestion` | `watermark` |

MongoDB stays on `127.0.0.1:27017`, database `etl_lesson`, collection `order_events`.

## Tests

```powershell
cd etl-flow\backend
.\.venv\Scripts\python -m pytest -q
```

Tests reset the lesson tables in `etl_flow` and replace `etl_lesson.order_events`. They do not touch any other database.
