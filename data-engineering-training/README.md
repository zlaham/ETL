# Data engineering training

Instructor-led sessions for senior engineers. Notebooks are the presentation. Attendees do not write code during the session.

## Session 1

`notebooks/01_why_data_engineering_and_medallion.ipynb`

Why a separate copy of operational orders has to exist, what the application database cannot retain, and why the ingestion landing keeps the raw document. ETL discards that document. ELT stores it. The diagram is `docs/medallion_architecture.svg`. The model is `src/architecture/preview.py`. It is not the pipeline.

## Session 2 code

Extraction, retries, checkpoints, and Bronze JSONL live under `src/ingestion`, `src/source`, and `src/storage`. Tests cover that behavior. The Session 2 notebook is the live walkthrough of those modules.

## Session 3

`notebooks/session_03_transformations_ai.ipynb`

Bronze is already landed. This hour publishes a sales fact: one current version of each order line, a star schema, and product categories. Rules cover the phones. A checked-in fixture proposes the rest and is validated before anything is published. The default path makes no network call. Setup, expected totals, and the optional live model are in `docs/session_03_README.md`. The teaching script is `docs/session_03_instructor_guide.md`.

## Session 4

`notebooks/04_Gold_Layer_and_Dimensional_Modeling.ipynb`

The Session 3 star already answers revenue by category and segment. It mints keys with `ROW_NUMBER()` and keeps only the current attribute. This hour publishes Gold: a surrogate registry, Type 1 and Type 2 history, a sales fact and a returns fact on conformed dimensions, a suspense hold, and marts that have to reconcile to the fact. The default path makes no network call. Setup and the numbers are in `docs/session_04_README.md`. The teaching script is `docs/session_04_instructor_guide.md`. The diagram is `docs/gold_dimensional_model.svg`.

## Run

Python 3.11 or later.

```powershell
cd data-engineering-training
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
jupyter lab notebooks/01_why_data_engineering_and_medallion.ipynb
```

```powershell
python -m pytest tests -q
```

No cloud account, database, API key, or network is required after the dependencies are installed. Order data is generated from seed 42.
