"""
Interactive dashboard over the SQLite warehouse and PatentsView extracts.

Run from the project root:

  pip install streamlit
  streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "patents.db"
QUERIES_PATH = ROOT / "sql" / "queries.sql"
REPORT_JSON = ROOT / "reports" / "report.json"


def _parse_named_queries(sql_text: str) -> dict[str, str]:
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


@st.cache_data(show_spinner=False)
def _read_sql(db_path: str, sql: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as con:
        return pd.read_sql_query(sql, con)


def main() -> None:
    st.set_page_config(page_title="Patent Intelligence", layout="wide")
    st.title("Global Patent Intelligence")

    if not DB_PATH.exists():
        st.error(f"Database not found at `{DB_PATH}`. Run `python run_pipeline.py --sample 25000` first.")
        return

    queries = _parse_named_queries(QUERIES_PATH.read_text(encoding="utf-8"))

    with st.sidebar:
        st.header("Controls")
        if st.button("Clear cached queries"):
            st.cache_data.clear()
            st.success("Cache cleared.")
        if REPORT_JSON.exists():
            with REPORT_JSON.open(encoding="utf-8") as fh:
                meta = json.load(fh)
            tp = meta.get("total_patents")
            if isinstance(tp, int):
                st.caption(f"report.json total_patents: {tp:,}")

    db_str = str(DB_PATH)

    total = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM patents")["n"].iloc[0])
    inv_n = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM inventors")["n"].iloc[0])
    co_n = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM companies")["n"].iloc[0])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patents", f"{total:,}")
    c2.metric("Inventors", f"{inv_n:,}")
    c3.metric("Companies (IDs)", f"{co_n:,}")
    c4.metric("Relationships", f"{int(_read_sql(db_str, 'SELECT COUNT(*) AS n FROM relationships')['n'].iloc[0]):,}")

    tab_inv, tab_co, tab_geo, tab_year, tab_join = st.tabs(
        ["Top inventors", "Top companies", "Countries", "Trends by year", "Join sample"]
    )

    with tab_inv:
        df = _read_sql(db_str, queries["Q1_TOP_INVENTORS"]).head(20)
        st.subheader("Q1 - top inventors")
        st.bar_chart(df.set_index("name")["patent_count"].head(15))
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_co:
        df = _read_sql(db_str, queries["Q2_TOP_COMPANIES"]).head(20)
        st.subheader("Q2 - top assignees")
        plot_df = df.copy()
        nm = plot_df["name"].fillna("")
        plot_df["label"] = nm.where(
            nm.ne("Unknown organization"),
            plot_df["company_id"].astype(str).str.slice(0, 24) + "...",
        )
        st.bar_chart(plot_df.set_index("label")["patent_count"].head(15))
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_geo:
        df = _read_sql(db_str, queries["Q3_TOP_COUNTRIES"]).head(20)
        st.subheader("Q3 - inventor countries")
        st.bar_chart(df.set_index("country")["patent_count"].head(15))
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_year:
        df = _read_sql(db_str, queries["Q4_YEARLY_TRENDS"])
        st.subheader("Q4 - patents per grant year")
        st.line_chart(df.set_index("year")["patents_in_year"])
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_join:
        st.subheader("Q5 - joined sample")
        st.dataframe(_read_sql(db_str, queries["Q5_JOIN_SAMPLE"]), use_container_width=True, hide_index=True)
        st.subheader("Q6 - CTE (post-2000 inventors)")
        st.dataframe(_read_sql(db_str, queries["Q6_CTE_RECENT_INVENTORS"]).head(20), use_container_width=True, hide_index=True)
        st.subheader("Q7 - ranked inventors (window)")
        st.dataframe(_read_sql(db_str, queries["Q7_RANKED_INVENTORS"]).head(20), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
