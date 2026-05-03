# Global Patent Intelligence Data Pipeline

End-to-end pipeline for USPTO **PatentsView** bulk grants (`pvgpatdis`): chunked pandas cleaning → SQLite warehouse → analytical SQL → CSV / JSON / console reporting.

Bulk landing page (dictionary PDF lives alongside the downloads):

https://data.uspto.gov/bulkdata/datasets/pvgpatdis

## Repository layout

| Path | Purpose |
|------|---------|
| `data/raw/` | PatentsView `.tsv` extracts you download locally |
| `data/processed/` | Normalized CSVs (`clean_*.csv`) emitted by `clean.py` |
| `database/patents.db` | SQLite warehouse produced by `load.py` |
| `sql/schema.sql` | Table definitions (`patents`, `inventors`, `companies`, `relationships`) |
| `sql/queries.sql` | Demonstrations for Q1–Q7 |
| `scripts/` | Python stages (`extract.py`, `clean.py`, `load.py`, `analyze.py`, optional `viz.py`) |
| `reports/` | Automated summaries (`top_inventors.csv`, `top_companies.csv`, `country_trends.csv`, `report.json`) |
| `run_pipeline.py` | Convenience runner chaining *clean → load → analyze* |
| `streamlit_app.py` | Optional dashboard (`streamlit run streamlit_app.py`) |

## Minimum inputs (`data/raw/`)

Required slices:

- `g_patent.tsv`
- `g_inventor_disambiguated.tsv`
- `g_persistent_assignee.tsv`
- `g_location_disambiguated.tsv`

Optional enrichments (drop into `data/raw/` when available):

| File | Benefit |
|------|---------|
| `g_patent_abstract.tsv` | Text abstracts |
| `g_assignee_disambiguated.tsv` | Human-readable assignee organization names |
| `g_application.tsv` | Application filing dates override grant dates |
| `g_cpc_current.tsv` | CPC classification codes |

Validate downloads:

```bash
python scripts/extract.py --strict
```

## Environment setup

```bash
python -m venv .venv
.\.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Running the pipeline

### Recommended first pass (subset)

Full scans over multi‑GB PatentsView extracts can take hours on a laptop. Start with the **first `N` patents listed in `g_patent.tsv`**:

```bash
python run_pipeline.py --sample 25000
```

Stages individually:

```bash
python scripts/clean.py --sample 25000
python scripts/load.py
python scripts/analyze.py
```

### Full corpus

Process everything referenced by your `g_patent.tsv` ordering:

```bash
python run_pipeline.py
```

> `filing_date` stores the **grant date** from `g_patent.tsv` unless you supply `g_application.tsv` with a recognized filing column. `year` is derived from that same date column for speed and consistency.

### Optional visualization (extra credit–style)

```bash
pip install matplotlib
python scripts/viz.py
```

`scripts/viz.py` reads `reports/report.json` and writes `reports/patents_per_year.png`.

### Streamlit dashboard (extra exploration)

Install optional UI dependencies:

```bash
pip install -r requirements-extras.txt
streamlit run streamlit_app.py
```

The app reads `database/patents.db` (same queries as `sql/queries.sql`) and shows charts for inventors, assignees, countries, and yearly trends. Use **Clear cached queries** in the sidebar after you rerun `load.py` / `analyze.py`.

## SQL coverage (Q1–Q7)

`sql/queries.sql` ships ready-to-run demonstrations:

| Tag | Concept |
|-----|---------|
| `Q1_TOP_INVENTORS` | Top inventors by distinct patent counts |
| `Q2_TOP_COMPANIES` | Top assignees |
| `Q3_TOP_COUNTRIES` | Inventor-country totals |
| `Q4_YEARLY_TRENDS` | Grants per year |
| `Q5_JOIN_SAMPLE` | Multi-table join preview |
| `Q6_CTE_RECENT_INVENTORS` | `WITH` clause for post-2000 activity |
| `Q7_RANKED_INVENTORS` | `DENSE_RANK()` window ranking |

`analyze.py` executes all of them, prints a console brief, and refreshes `reports/`.

## Artifacts checked into Git

- `clean_*.csv` under `data/processed/`
- `database/patents.db` (recreate anytime with `load.py`)
- `reports/*.csv`, `reports/report.json`

Regenerate locally to match your chosen `--sample` window or downloaded snapshot.

## Troubleshooting

- **Memory pressure with abstracts on the full corpus:** `clean.py` warns when `g_patent_abstract.tsv` is present without `--sample`. Prefer subset mode or omit abstracts for very large runs.
- **Company names show as `Unknown organization`:** add `g_assignee_disambiguated.tsv` so `clean.py` can map persistent assignee IDs.
- **UTF-8 issues in TSV rows:** cleaning uses `encoding_errors="replace"` to keep the pipeline running; inspect raw rows if you need lossless text.
