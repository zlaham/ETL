# Session 4 - Gold Layer and Dimensional Modeling

Instructor-led notebook for a 60-minute session. Attendees do not write code.

Session 3 published 11 sales lines and USD 3,779.50. The keys on that star are row numbers, and each customer or product has only its current attributes. This hour keeps that Silver contract and publishes Gold: durable surrogate keys, Type 1 and Type 2 history, a sales fact, a returns fact, a suspense hold, and marts that reconcile to the fact.

Northline's next questions are the ones the current-attribute star answers badly:

- Priya Nair moved from Consumer to Business on 17 October. Which sales keep Consumer?
- Merchandising moved the USB-C adapter from Electronics Accessories to Power on 18 October. Which sales move with it?
- One unit of lotion was returned on 19 October. Does the sale change?
- A line arrives for a customer the warehouse has not loaded. Does the KPI include the 749.00?

## Files

| Path | Role |
| --- | --- |
| `notebooks/04_Gold_Layer_and_Dimensional_Modeling.ipynb` | The session |
| `docs/session_04_instructor_guide.md` | Timing, questions, and the numbers to expect |
| `docs/gold_dimensional_model.svg` | The picture to leave on the screen |
| `sql/session_04/` | The Gold transformations |
| `src/gold/` | Loader, warehouse, and the certified figures |
| `data/session_04/silver/` | The Session 3 publish, checked in so the hour does not rebuild Bronze |
| `data/session_04/changes/` | The name correction, the segment change, the reclass, the return, the late line |
| `data/session_04/generate_sample_data.py` | Rewrites the Silver files from Session 3 Bronze and rewrites the change feed |
| `tests/test_gold_dimensional.py` | The publish, the second run, and the fallbacks |
| `artifacts/session04.duckdb` | Created when the notebook runs |

Session 2 and Session 3 are not modified. The 500-order extract still has no catalog and no order-line grain, so it is not the input. The envelope those sessions landed is the same shape Session 3 already consumed.

## Install

Python 3.11 or later. From `data-engineering-training`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

DuckDB, Pandas, and Matplotlib are in that requirements file. No database server is installed.

## Launch

```powershell
jupyter lab notebooks/04_Gold_Layer_and_Dimensional_Modeling.ipynb
```

Use the virtual environment above as the kernel. Run the notebook from the top. The first code cell finds the project whether the working directory is the project root or `notebooks/`.

## Offline

The notebook does not call a model, an API, or the clock. `ingested_at` and the effective dates come from the files. Running the setup cell twice rebuilds a fresh database and the same keys, because the allocator loads the Silver population first and the change feed second. The second publish inside one database is the idempotency check: it replaces the facts and does not append registry rows.

If `data/session_04/silver/` is missing, the loader rebuilds the same rows from Session 3 Bronze. If that Bronze is missing too, it uses the same 11 lines embedded in `src/gold/fallback_data.py`.

## Expected results

| Check | Result |
| --- | --- |
| Sales lines | 11 |
| Gross sales | USD 3,779.50 |
| Return | USD 12.50 on `OL-1005-1` |
| Net sales | USD 3,767.00 |
| Orders / units / units returned | 10 / 18 / 1 |
| Average order gross | USD 377.95 |
| Weekend gross (17 and 18 October) | USD 889.00 |
| Smartphones, as sold | 3,426.00 |
| Electronics Accessories, as sold / as currently classified | 211.00 / 97.00 |
| Power, as currently classified | 114.00 |
| Consumer smartphones, as sold / as current segment | 1,948.00 / 749.00 |
| Business smartphones, as sold / as current segment | 1,478.00 / 2,677.00 |
| `C100` durable key | 1, name corrected to John A. Smith |
| `C101` version 1 / version 2 | keys 2 and 9 |
| `C050` durable key / row number if the set is renumbered | 10 / 1 |
| Suspense | `OL-1026-1`, USD 749.00, `unknown_customer` |
| Second publish | The same keys, the same gross, the same net |

`OL-1001-1` stays 749.00. `C100` and `C107` stay two customers. The 749.00 for `C109` stays out of the KPI.

## Tests

```powershell
python -m pytest tests -q
```

## Troubleshooting

**`Open this notebook from the data-engineering-training project.`** The kernel's working directory is outside the project. Reopen the notebook from this repo and run from the top.

**`ModuleNotFoundError: duckdb` or `src`.** The kernel is not the virtual environment where `pip install -r requirements.txt` was run.

**`session04.duckdb` is locked.** Restart the kernel. The setup cell closes an existing connection and recreates the file. Then run from the top.

**The gross assertion fails.** The Silver files no longer match the Session 3 contract. Restore `data/session_04/silver/`, or run `python data/session_04/generate_sample_data.py` from the project root. That rewrites the Silver extract from Session 3 Bronze. It does not edit Session 3.

**A Matplotlib font message appears in the setup cell.** Harmless on a new machine. Run the cell again if you want it quiet before the room arrives.
