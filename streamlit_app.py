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
DATA_SOURCE_URL = "https://data.uspto.gov/bulkdata/datasets/pvgpatdis"


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


def _pivot_year_category(
    long_df: pd.DataFrame,
    year_col: str,
    cat_col: str,
    value_col: str,
) -> pd.DataFrame:
    """Wide table: index = year, columns = category (for multi-series line charts)."""
    if long_df.empty:
        return pd.DataFrame()
    out = long_df.pivot_table(
        index=year_col,
        columns=cat_col,
        values=value_col,
        aggfunc="sum",
    )
    # Ensure numeric columns; gaps → 0 for charting
    return out.fillna(0).sort_index()


def _search_patents(db_path: str, q: str, limit: int) -> pd.DataFrame:
    """Case-insensitive substring match on id, title, abstract, or CPC."""
    pattern = f"%{q.strip()}%"
    sql = """
    SELECT
      patent_id,
      title,
      year,
      cpc_primary,
      filing_date,
      CASE
        WHEN abstract IS NOT NULL AND length(abstract) > 400
          THEN substr(abstract, 1, 400) || '…'
        ELSE abstract
      END AS abstract_preview
    FROM patents
    WHERE patent_id LIKE ? COLLATE NOCASE
       OR title LIKE ? COLLATE NOCASE
       OR abstract LIKE ? COLLATE NOCASE
       OR IFNULL(cpc_primary, '') LIKE ? COLLATE NOCASE
    ORDER BY year DESC
    LIMIT ?
    """
    params = (pattern, pattern, pattern, pattern, limit)
    with sqlite3.connect(db_path) as con:
        return pd.read_sql_query(sql, con, params=params)


def main() -> None:
    st.set_page_config(
        page_title="Patent Intelligence Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
        <style>
        div[data-testid="stMetricValue"] { font-size: 1.85rem; }
        .big-font { font-size: 1.15rem; color: #424242; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Global Patent Intelligence")
    st.markdown(
        '<p class="big-font">Chunked ETL from USPTO PatentsView → SQLite analytics · Built for exploration and demos.</p>',
        unsafe_allow_html=True,
    )

    if not DB_PATH.exists():
        st.error(f"Database not found at `{DB_PATH}`. Run `python run_pipeline.py --sample 25000` first.")
        return

    queries = _parse_named_queries(QUERIES_PATH.read_text(encoding="utf-8"))

    with st.sidebar:
        st.header("About")
        st.markdown(
            f"This dashboard reads **`database/patents.db`** (same logic as `analyze.py` / `queries.sql`). "
            f"Official bulk data: [PatentsView granted disambiguated]({DATA_SOURCE_URL})."
        )
        st.divider()
        st.header("Controls")
        if st.button("Clear cached queries"):
            st.cache_data.clear()
            st.success("Cache refreshed on next interaction.")
        if REPORT_JSON.exists():
            try:
                meta = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
                tp = meta.get("total_patents")
                if isinstance(tp, int):
                    st.caption(f"Last `report.json`: **{tp:,}** patents recorded.")
            except OSError:
                pass

    db_str = str(DB_PATH)

    total = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM patents")["n"].iloc[0])
    inv_n = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM inventors")["n"].iloc[0])
    co_n = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM companies")["n"].iloc[0])
    rel_n = int(_read_sql(db_str, "SELECT COUNT(*) AS n FROM relationships")["n"].iloc[0])
    abs_n = int(
        _read_sql(
            db_str,
            "SELECT COUNT(*) AS n FROM patents WHERE abstract IS NOT NULL AND TRIM(abstract) != ''",
        )["n"].iloc[0]
    )
    cpc_n = int(
        _read_sql(
            db_str,
            "SELECT COUNT(*) AS n FROM patents WHERE cpc_primary IS NOT NULL AND TRIM(cpc_primary) != ''",
        )["n"].iloc[0]
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Patents", f"{total:,}")
    m2.metric("Inventors", f"{inv_n:,}")
    m3.metric("Companies", f"{co_n:,}")
    m4.metric("Links", f"{rel_n:,}")
    m5.metric("With abstract", f"{abs_n:,}")
    m6.metric("With CPC", f"{cpc_n:,}")

    tab_ov, tab_search, tab_inv, tab_co, tab_geo, tab_tr, tab_join = st.tabs(
        [
            "Overview",
            "Patent search",
            "Top inventors",
            "Top companies",
            "Countries",
            "Trends",
            "SQL demos (Q5–Q7)",
        ]
    )

    with tab_ov:
        c_left, c_right = st.columns((1, 1))
        with c_left:
            st.subheader("What you are looking at")
            st.markdown(
                """
                - **Inventors / countries** come from disambiguated inventor + location tables.
                - **Companies** are assignees linked per patent (primary assignee on the relationship row).
                - **Year** reflects grant year in the warehouse (or filing-derived year when loaded that way).
                - Tabs to the right drill into ranked lists, **trends** (volume, YoY, country & CPC slices), and SQL demos (Q1–Q7).
                """
            )
        with c_right:
            st.subheader("Quick trend preview")
            df_q4 = _read_sql(db_str, queries["Q4_YEARLY_TRENDS"])
            if not df_q4.empty:
                st.line_chart(df_q4.set_index("year")["patents_in_year"], height=260)
                st.caption("Patents per grant year in the current database subset.")
            else:
                st.info("No year breakdown available.")

        st.divider()
        st.subheader("Top 5 snapshot")
        s1, s2, s3 = st.columns(3)
        df1 = _read_sql(db_str, queries["Q1_TOP_INVENTORS"]).head(5)
        df2 = _read_sql(db_str, queries["Q2_TOP_COMPANIES"]).head(5)
        df3 = _read_sql(db_str, queries["Q3_TOP_COUNTRIES"]).head(5)
        with s1:
            st.markdown("**Inventors**")
            st.dataframe(df1, hide_index=True, width="stretch")
        with s2:
            st.markdown("**Assignees**")
            st.dataframe(df2, hide_index=True, width="stretch")
        with s3:
            st.markdown("**Countries**")
            st.dataframe(df3, hide_index=True, width="stretch")

    with tab_search:
        st.subheader("Search patents")
        st.caption(
            "Matches **patent ID**, **title**, **abstract**, or **CPC** (case-insensitive). "
            "Use % and _ as SQL wildcards if you need pattern matching."
        )
        with st.form("patent_search_form", clear_on_submit=False):
            q_col, lim_col = st.columns((3, 1))
            with q_col:
                search_q = st.text_input(
                    "Keywords or patent number",
                    placeholder="e.g. semiconductor, CPC code, or US12345678",
                )
            with lim_col:
                row_limit = st.number_input(
                    "Max rows",
                    min_value=5,
                    max_value=500,
                    value=50,
                    step=5,
                    help="Maximum number of patents to show.",
                )
            submitted = st.form_submit_button("Search", type="primary")

        if submitted:
            trimmed = search_q.strip() if search_q else ""
            if not trimmed:
                st.warning("Enter a search term or click Search after typing.")
            else:
                with st.spinner("Searching…"):
                    sdf = _search_patents(db_str, trimmed, int(row_limit))
                if sdf.empty:
                    st.info("No patents matched that query.")
                else:
                    st.success(f"{len(sdf)} patent(s) (showing up to {int(row_limit):,}).")
                    st.dataframe(sdf, hide_index=True, width="stretch", height=420)

    with tab_inv:
        df = _read_sql(db_str, queries["Q1_TOP_INVENTORS"]).head(25)
        st.subheader("Q1 — Top inventors by distinct patents")
        st.caption("SQL: ranked patent counts per disambiguated inventor.")
        ch, tb = st.columns((3, 2))
        with ch:
            st.bar_chart(df.set_index("name")["patent_count"].head(18), height=360)
        with tb:
            st.dataframe(df, hide_index=True, height=360, width="stretch")

    with tab_co:
        df = _read_sql(db_str, queries["Q2_TOP_COMPANIES"]).head(25)
        st.subheader("Q2 — Top assignee organizations")
        st.caption("SQL: patents linked via primary assignee on relationship rows.")
        plot_df = df.copy()
        nm = plot_df["name"].fillna("")
        plot_df["label"] = nm.where(
            nm.ne("Unknown organization"),
            plot_df["company_id"].astype(str).str.slice(0, 28) + "...",
        )
        ch, tb = st.columns((3, 2))
        with ch:
            st.bar_chart(plot_df.set_index("label")["patent_count"].head(18), height=360)
        with tb:
            st.dataframe(df, hide_index=True, height=360, width="stretch")

    with tab_geo:
        df = _read_sql(db_str, queries["Q3_TOP_COUNTRIES"]).head(25)
        st.subheader("Q3 — Inventor location (country)")
        st.caption("SQL: patent volume attributed to inventor country (not assignee HQ).")
        ch, tb = st.columns((3, 2))
        with ch:
            st.bar_chart(df.set_index("country")["patent_count"].head(18), height=360)
        with tb:
            st.dataframe(df, hide_index=True, height=360, width="stretch")

    with tab_tr:
        st.subheader("Patent volume by grant year (Q4)")
        st.caption("SQL: `COUNT(*)` grouped by grant year on the patents table.")
        df_vol = _read_sql(db_str, queries["Q4_YEARLY_TRENDS"])
        if df_vol.empty:
            st.info("No year breakdown available.")
        else:
            c1, c2 = st.columns((3, 2))
            with c1:
                st.line_chart(df_vol.set_index("year")["patents_in_year"], height=280)
            with c2:
                st.dataframe(df_vol, hide_index=True, height=280, width="stretch")

            st.divider()
            st.subheader("Year-over-year change")
            st.caption("Δ patents vs the previous grant year in the database (pandas `diff`).")
            yoy = df_vol.sort_values("year").copy()
            yoy["delta_prior_year"] = yoy["patents_in_year"].diff()
            bar_df = yoy.dropna(subset=["delta_prior_year"]).set_index("year")["delta_prior_year"]
            if bar_df.empty:
                st.info("Need at least two years with counts to compute YoY change.")
            else:
                st.bar_chart(bar_df, height=260)

            st.divider()
            st.subheader("Top inventor countries over time")
            st.caption("SQL: **Q8** — for the eight busiest inventor countries, distinct patents linked per grant year.")
            df_cy = _read_sql(db_str, queries["Q8_TOP_COUNTRIES_YEAR_TREND"])
            if df_cy.empty:
                st.info("No country–year series (relationships may be empty).")
            else:
                wide_c = _pivot_year_category(df_cy, "year", "country", "patents_in_year")
                if not wide_c.empty:
                    st.line_chart(wide_c, height=320)
                    with st.expander("Country × year table"):
                        st.dataframe(
                            df_cy.sort_values(["year", "country"]),
                            hide_index=True,
                            width="stretch",
                            height=260,
                        )

            st.divider()
            st.subheader("Leading CPC prefixes over time")
            st.caption(
                "SQL: **Q9** — first four characters of **primary CPC** (coarse bucket), "
                "top ten prefixes overall, patents per grant year."
            )
            df_pc = _read_sql(db_str, queries["Q9_TOP_CPC_PREFIX_YEAR_TREND"])
            if df_pc.empty:
                st.info("No CPC-labelled patents in range for prefix trends.")
            else:
                wide_p = _pivot_year_category(df_pc, "year", "cpc_prefix", "patents_in_year")
                if not wide_p.empty:
                    st.line_chart(wide_p, height=320)
                    with st.expander("CPC prefix × year table"):
                        st.dataframe(
                            df_pc.sort_values(["year", "cpc_prefix"]),
                            hide_index=True,
                            width="stretch",
                            height=260,
                        )

    with tab_join:
        st.subheader("Q5 — Join patents, inventors, companies")
        st.caption("Sample of joined rows (same query as `queries.sql`).")
        st.dataframe(_read_sql(db_str, queries["Q5_JOIN_SAMPLE"]).head(40), hide_index=True, width="stretch")
        st.divider()
        st.subheader("Q6 — CTE: inventors on patents since 2000")
        st.dataframe(
            _read_sql(db_str, queries["Q6_CTE_RECENT_INVENTORS"]).head(25),
            hide_index=True,
            width="stretch",
        )
        st.divider()
        st.subheader("Q7 — Window rank (DENSE_RANK)")
        st.dataframe(
            _read_sql(db_str, queries["Q7_RANKED_INVENTORS"]).head(25),
            hide_index=True,
            width="stretch",
        )

    st.divider()
    st.caption(
        f"PatentsView bulk data (USPTO) · Pipeline: `clean.py` → `load.py` · Queries: `sql/queries.sql` · "
        f"[Dataset portal]({DATA_SOURCE_URL})"
    )


if __name__ == "__main__":
    main()
