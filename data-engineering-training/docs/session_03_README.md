# Session 3 - Modern Data Transformation, Dimensional Modeling & GenAI-Powered Enrichment

Instructor-led notebook for 20 October 2026. Sixty minutes. Attendees do not write code.

Northline Commerce wants revenue by product category and customer segment. The orders, customers, and products are already in Bronze, and they are not ready to answer that question. The notebook standardizes them, keeps one current version of each order line, quarantines rows that fail a stated rule, builds a small star schema, and classifies product text. The classification path uses a checked-in fixture. It does not call a model unless you turn that on yourself.

## Files

| Path | Role |
| --- | --- |
| `notebooks/session_03_transformations_ai.ipynb` | The session |
| `docs/session_03_instructor_guide.md` | Timing, questions, and the numbers to expect |
| `data/session_03/bronze/` | Fixed order, customer, and product extracts |
| `data/session_03/fixtures/llm_product_classifications.fixture.json` | Precomputed model output, labeled as such |
| `data/session_03/generate_sample_data.py` | Rewrites those files. The notebook does not need it |
| `artifacts/session03.duckdb` | Created when the notebook runs |

Session 2's extractor and its 500-order population are unchanged. This extract is smaller because it has to carry order lines, a CRM, and a catalog on a projector.

## Install

Python 3.11 or later. From `data-engineering-training`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

DuckDB is in that requirements file. No database server is installed.

## Launch

```powershell
jupyter lab notebooks/session_03_transformations_ai.ipynb
```

Use the virtual environment above as the kernel. Run the notebook from the top. The first cell finds the project whether the working directory is the project root or `notebooks/`.

## Offline demonstration

This is the path for the class.

`LIVE_LLM_ENABLED` in the setup cell is `False`. The enrichment cell prints:

`Precomputed LLM output fixture — no live model inference.`

An `LLM_API_KEY` in the environment does not change that. The notebook also requires `LLM_ENABLE=true` before it will consider a live call, and the setup flag still has to be edited. The executed notebook reports `HTTP calls: 0`.

## Optional live model

Skip this during the session.

1. Set `LIVE_LLM_ENABLED = True` in the setup cell.
2. Set the environment before launching Jupyter:

```powershell
$env:LLM_ENABLE = "true"
$env:LLM_API_KEY = "<your key>"
$env:LLM_MODEL = "<model id>"
$env:LLM_BASE_URL = "https://api.openai.com/v1"
```

`LLM_BASE_URL` defaults to `https://api.openai.com/v1` and can point at any OpenAI-compatible `/chat/completions` endpoint. The client sends temperature 0, waits at most 20 seconds, retries once on HTTP 429 or 5xx, and still passes every response through the same taxonomy checks as the fixture. The published category is still chosen by the precedence rule: approved map, then a legal rule, then an accepted proposal, then `Unclassified`.

## Expected results

Running from the top on the checked-in files produces:

| Check | Result |
| --- | --- |
| Order deliveries | 29, each with one disposition |
| Accepted sales lines | 11 |
| Quarantined | 10 |
| Excluded by the sales policy | 5 |
| Duplicate deliveries | 2 |
| Superseded versions | 1 |
| Published revenue | USD 3,779.50 |
| Smartphones | 3,426.00 |
| Electronics Accessories | 211.00 |
| Home Appliances | 89.00 |
| Personal Care | 53.50 |
| If model-backed categories are removed | Smartphones 3,426.00 and Unclassified 353.50 |
| Second full rebuild | The same 11 lines and the same revenue |
| HTTP calls | 0 |

`OL-1001-1` is published at 749.00. The earlier 799.00 stays in Bronze and is marked superseded. Canceled and returned lines are not in the fact. C100 and C107 both display as John Smith and remain two customers. P103 is published as Smartphones / Flagship Phones with method `manual`. P110 is `Unclassified`.

## Troubleshooting

**`FileNotFoundError` or "Open this notebook from the data-engineering-training project."** The kernel's working directory is outside the project. Reopen the notebook from this repo and run from the top.

**`ModuleNotFoundError: duckdb`.** The kernel is not the virtual environment where `pip install -r requirements.txt` was run.

**`session03.duckdb` is locked.** Restart the kernel. The setup cell closes an existing connection and recreates the file. Then run from the top.

**The revenue assertion fails.** The Bronze files or the fixture no longer match the certified extract baked into the last code cell. Restore the checked-in files. Regenerating with `generate_sample_data.py` rewrites that same extract; it does not invent a new one.

**A date such as `05/10/2026` is quarantined.** That is the lesson. The contract parses a day-first date only when the day cannot be a month.

**The first cell mentions a Matplotlib font cache.** Harmless on a new machine. Run the cell again if you want a quiet setup cell before the room arrives.

**A live call fails.** Put `LIVE_LLM_ENABLED` back to `False` and run from the top. The class path does not need the network.
