"""Run analytical SQL (Q1–Q7), print a console report, and export CSV/JSON summaries."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "database" / "patents.db"
QUERIES_PATH = ROOT / "sql" / "queries.sql"
REPORTS_DIR = ROOT / "reports"


def parse_named_queries(sql_text: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-- QUERY:"):
            current = stripped.split(":", 1)[1].strip()
            blocks[current] = []
            continue
        if current is None:
            continue
        blocks[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in blocks.items() if lines}


def banner(title: str, width: int = 54) -> str:
    pad = max(0, width - len(title) - 2)
    left = pad // 2
    right = pad - left
    return f"{'=' * left} {title} {'=' * right}"


def run_analysis(db_path: Path, queries_path: Path, top_n_console: int) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}; run scripts/load.py first.")

    queries = parse_named_queries(queries_path.read_text(encoding="utf-8"))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as con:
        total_patents = int(pd.read_sql_query("SELECT COUNT(*) AS n FROM patents", con)["n"].iloc[0])

        df_inv = pd.read_sql_query(queries["Q1_TOP_INVENTORS"], con)
        df_co = pd.read_sql_query(queries["Q2_TOP_COMPANIES"], con)
        df_ctry = pd.read_sql_query(queries["Q3_TOP_COUNTRIES"], con)
        df_trend = pd.read_sql_query(queries["Q4_YEARLY_TRENDS"], con)
        df_join = pd.read_sql_query(queries["Q5_JOIN_SAMPLE"], con)
        df_cte = pd.read_sql_query(queries["Q6_CTE_RECENT_INVENTORS"], con)
        df_rank = pd.read_sql_query(queries["Q7_RANKED_INVENTORS"], con)

    # CSV exports (assignment-required filenames)
    df_inv.rename(columns={"patent_count": "patents"}).assign(name=lambda d: d["name"].fillna("(unknown)"))[
        ["name", "patents"]
    ].to_csv(REPORTS_DIR / "top_inventors.csv", index=False)

    df_co.rename(columns={"patent_count": "patents"}).assign(name=lambda d: d["name"].fillna("(unknown)"))[
        ["name", "patents"]
    ].to_csv(REPORTS_DIR / "top_companies.csv", index=False)

    # Filename from the brief: year-level patent volumes (Q4). See also JSON `top_countries` for geography.
    df_trend.rename(columns={"patents_in_year": "patents"}).to_csv(REPORTS_DIR / "country_trends.csv", index=False)

    country_patent_volume = int(df_ctry["patent_count"].sum()) if not df_ctry.empty else 0
    shares = []
    for _, row in df_ctry.head(25).iterrows():
        denom = country_patent_volume if country_patent_volume > 0 else 1
        shares.append({"country": row["country"], "share": round(row["patent_count"] / denom, 6)})

    report = {
        "total_patents": total_patents,
        "top_inventors": [
            {"name": row["name"] or "(unknown)", "patents": int(row["patent_count"])}
            for _, row in df_inv.head(25).iterrows()
        ],
        "top_companies": [
            {"name": row["name"] or "(unknown)", "patents": int(row["patent_count"])}
            for _, row in df_co.head(25).iterrows()
        ],
        "top_countries": shares,
        "patents_by_year": [
            {"year": int(row["year"]), "patents": int(row["patents_in_year"])} for _, row in df_trend.iterrows()
        ],
        "notes": {
            "country_share_denominator": "Sum of patent counts from inventor-country linkage (can exceed distinct patents).",
            "filing_date": "Uses patent grant date when application-level filing dates are not loaded.",
            "country_trends_csv": "Rows are patents per grant year (Q4); the filename mirrors the coursework handout.",
        },
    }

    (REPORTS_DIR / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Console report
    print(banner("PATENT REPORT"))
    print(f"Total Patents: {total_patents:,}")

    inv_lines = []
    for idx, (_, row) in enumerate(df_inv.head(top_n_console).iterrows(), start=1):
        inv_lines.append(f"{idx}. {row['name'] or '(unknown)'} - {int(row['patent_count'])} patents")
    print("Top Inventors:", "; ".join(inv_lines) if inv_lines else "(none)")

    co_lines = []
    for idx, (_, row) in enumerate(df_co.head(top_n_console).iterrows(), start=1):
        nm = row["name"] or "(unknown)"
        if nm == "Unknown organization":
            cid = str(row["company_id"])
            nm = cid if len(cid) <= 44 else cid[:41] + "..."
        co_lines.append(f"{idx}. {nm} - {int(row['patent_count'])} patents")
    print("Top Companies:", "; ".join(co_lines) if co_lines else "(none)")

    c_lines = []
    for idx, (_, row) in enumerate(df_ctry.head(top_n_console).iterrows(), start=1):
        c_lines.append(f"{idx}. {row['country']} - {int(row['patent_count'])} patents")
    print("Top Countries:", "; ".join(c_lines) if c_lines else "(none)")

    if not df_trend.empty:
        recent = df_trend.tail(5)
        trend_bits = [f"{int(r.year)}: {int(r.patents_in_year):,}" for _, r in recent.iterrows()]
        print("Recent yearly patent counts:", "; ".join(trend_bits))

    print()
    print(banner("SQL QUERY DEMOS"))
    print("\n[Q5 sample JOIN - first 10 rows]")
    print(df_join.head(10).to_string(index=False))
    print("\n[Q6 CTE - inventors on patents since 2000 (top 10)]")
    print(df_cte.head(10).to_string(index=False))
    print("\n[Q7 WINDOW rank - top 10 inventors]")
    print(df_rank.head(10).to_string(index=False))

    print()
    print(f"Wrote {REPORTS_DIR / 'top_inventors.csv'}")
    print(f"Wrote {REPORTS_DIR / 'top_companies.csv'}")
    print(f"Wrote {REPORTS_DIR / 'country_trends.csv'}")
    print(f"Wrote {REPORTS_DIR / 'report.json'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Run patent analytics and export reports.")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--queries", type=Path, default=QUERIES_PATH)
    p.add_argument("--top-n", type=int, default=10, help="How many rows to summarize on console.")
    args = p.parse_args()
    run_analysis(db_path=args.db, queries_path=args.queries, top_n_console=args.top_n)


if __name__ == "__main__":
    main()
