"""
Read PatentsView-style TSV exports, normalize with pandas (chunked), and write clean CSVs.

Optional: set --sample N to process only the first N patent_ids in g_patent.tsv (faster demos).
When g_application.tsv is missing, filing_date falls back to grant date from g_patent; year prefers filing_date when parseable.

Optional raw files (place in data/raw/) for richer outputs:
  g_patent_abstract.tsv, g_assignee_disambiguated.tsv, g_application.tsv, g_cpc_current.tsv
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

REQUIRED_FILES = ("g_patent.tsv", "g_inventor_disambiguated.tsv", "g_persistent_assignee.tsv", "g_location_disambiguated.tsv")


def _read_tsv_chunks(path: Path, chunksize: int, usecols=None):
    if not path.exists():
        return
    reader = pd.read_csv(
        path,
        sep="\t",
        dtype=str,
        chunksize=chunksize,
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="skip",
        usecols=usecols,
    )
    yield from reader


def _parse_year(patent_date: str | float | None) -> int | None:
    if patent_date is None or (isinstance(patent_date, float) and pd.isna(patent_date)):
        return None
    s = str(patent_date).strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def _resolve_assignee_columns(columns: list[str]) -> list[str]:
    cols = [c for c in columns if c.startswith("disamb_assignee_id_")]
    return sorted(cols)  # chronological suffix → reversed() picks newest snapshot


def _sample_patent_ids(patent_path: Path, n: int, chunksize: int) -> set[str]:
    ids: list[str] = []
    for chunk in _read_tsv_chunks(patent_path, chunksize, usecols=["patent_id"]):
        for pid in chunk["patent_id"].tolist():
            ids.append(pid)
            if len(ids) >= n:
                return set(ids)
    return set(ids)


def _load_locations(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        sep="\t",
        dtype=str,
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="skip",
        usecols=lambda c: c in {"location_id", "disambig_country"},
    )
    df["disambig_country"] = df["disambig_country"].fillna("")
    return df


def _infer_company_lookup_columns(columns: list[str]) -> tuple[str | None, str | None]:
    lower_map = {c.lower(): c for c in columns}
    id_col = None
    for key in ("assignee_id", "disambig_assignee_id", "persistent_assignee_id"):
        if key in lower_map:
            id_col = lower_map[key]
            break
    if id_col is None:
        candidates = [c for c in columns if "assignee_id" in c.lower()]
        id_col = candidates[-1] if candidates else None
    name_col = None
    for c in columns:
        cl = c.lower()
        if "organization" in cl or "assignee_name" in cl:
            name_col = c
            break
    return id_col, name_col


def _build_company_names(
    assignee_disambig_path: Path,
    chunksize: int,
    patent_allowlist: set[str] | None = None,
) -> dict[str, str]:
    id_col = name_col = None
    names: dict[str, str] = {}
    for chunk in _read_tsv_chunks(assignee_disambig_path, chunksize):
        if id_col is None:
            id_col, name_col = _infer_company_lookup_columns(list(chunk.columns))
            if id_col is None or name_col is None:
                print(
                    "Warning: could not infer columns from g_assignee_disambiguated.tsv; skipping names.",
                    file=sys.stderr,
                )
                return {}
        if patent_allowlist is not None and "patent_id" in chunk.columns:
            chunk = chunk[chunk["patent_id"].isin(patent_allowlist)]
            if chunk.empty:
                continue
        chunk = chunk.dropna(subset=[id_col])
        chunk[id_col] = chunk[id_col].astype(str).str.strip()
        chunk[name_col] = chunk[name_col].astype(str).str.strip()
        for cid, nm in zip(chunk[id_col], chunk[name_col]):
            if cid and nm and cid.lower() != "nan":
                names[cid] = nm
    return names


def _abstract_lookup_sql(con: sqlite3.Connection, patent_ids: list[str]) -> dict[str, str]:
    """Batch-fetch abstracts; keeps SQLite bind parameter lists small."""
    out: dict[str, str] = {}
    batch_size = 450
    for i in range(0, len(patent_ids), batch_size):
        batch = patent_ids[i : i + batch_size]
        placeholders = ",".join("?" * len(batch))
        cur = con.execute(f"SELECT patent_id, txt FROM abs WHERE patent_id IN ({placeholders})", batch)
        for pid, txt in cur:
            out[str(pid)] = str(txt)
    return out


def _build_abstract_sqlite(abstract_path: Path, chunksize: int) -> sqlite3.Connection:
    """Stream abstracts into a temp SQLite DB (full-corpus safe vs. RAM dict)."""
    fd, path_str = tempfile.mkstemp(prefix="pv_abs_", suffix=".sqlite")
    os.close(fd)
    db_path = Path(path_str)
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE abs(patent_id TEXT PRIMARY KEY, txt TEXT)")
        abs_pid_col = abs_txt_col = None
        for chunk in _read_tsv_chunks(abstract_path, chunksize):
            cols = list(chunk.columns)
            if abs_pid_col is None:
                abs_pid_col = next((c for c in cols if c.lower() == "patent_id"), cols[0])
                abs_txt_col = next(
                    (c for c in cols if "abstract" in c.lower()),
                    cols[1] if len(cols) > 1 else cols[0],
                )
            chunk = chunk[[abs_pid_col, abs_txt_col]].dropna(subset=[abs_pid_col])
            pid_series = chunk[abs_pid_col].astype(str).str.strip()
            txt_series = chunk[abs_txt_col].astype(str)
            rows = list(zip(pid_series, txt_series))
            con.executemany("INSERT OR REPLACE INTO abs(patent_id, txt) VALUES (?, ?)", rows)
        con.execute("CREATE INDEX IF NOT EXISTS idx_abs_patent ON abs(patent_id)")
        con.commit()
        setattr(con, "_pv_tmp_path", db_path)
        return con
    except Exception:
        con.close()
        db_path.unlink(missing_ok=True)
        raise


def _merge_optional_application_dates(application_path: Path, chunksize: int, patent_allowlist: set[str] | None) -> dict[str, str]:
    """Return patent_id -> filing date string when g_application.tsv is available."""
    out: dict[str, str] = {}
    pid_col = date_col = None
    for chunk in _read_tsv_chunks(application_path, chunksize):
        cols = list(chunk.columns)
        if pid_col is None:
            pid_col = next((c for c in cols if c.lower() == "patent_id"), None)
            date_col = None
            for cand in ("filing_date", "application_date", "app_date", "patent_application_date"):
                match = next((c for c in cols if c.lower() == cand), None)
                if match:
                    date_col = match
                    break
            if pid_col is None or date_col is None:
                print("Warning: g_application.tsv present but patent/date columns not recognized.", file=sys.stderr)
                return {}
        chunk = chunk[[pid_col, date_col]].dropna(subset=[pid_col])
        if patent_allowlist is not None:
            chunk = chunk[chunk[pid_col].isin(patent_allowlist)]
        for pid, d in zip(chunk[pid_col].astype(str), chunk[date_col].astype(str)):
            out[str(pid)] = str(d).strip()
    return out


def run_clean(sample: int | None, chunksize: int) -> None:
    for fn in REQUIRED_FILES:
        if not (RAW / fn).exists():
            raise FileNotFoundError(f"Missing required raw file: {RAW / fn}")

    PROCESSED.mkdir(parents=True, exist_ok=True)

    patent_path = RAW / "g_patent.tsv"
    patent_allowlist = _sample_patent_ids(patent_path, sample, chunksize) if sample else None
    if sample:
        print(f"Sample mode: {len(patent_allowlist)} patent_ids from start of g_patent.tsv")

    app_dates: dict[str, str] = {}
    application_path = RAW / "g_application.tsv"
    if application_path.exists():
        app_dates = _merge_optional_application_dates(application_path, chunksize, patent_allowlist)

    print("Loading locations ...")
    locations = _load_locations(RAW / "g_location_disambiguated.tsv")

    assignee_disambig_path = RAW / "g_assignee_disambiguated.tsv"
    company_names: dict[str, str] = {}
    if assignee_disambig_path.exists():
        print("Building company names from g_assignee_disambiguated.tsv ...")
        company_names = _build_company_names(assignee_disambig_path, chunksize, patent_allowlist)
    else:
        print("Note: add g_assignee_disambiguated.tsv to populate real company names.")

    print("Scanning assignees (primary per patent + company universe) ...")
    assignee_path = RAW / "g_persistent_assignee.tsv"
    patent_primary_company: dict[str, str] = {}
    company_ids: set[str] = set()
    assignee_cols: list[str] | None = None

    def _combine_assignee_series(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
        combined: pd.Series | None = None
        for c in reversed(cols):
            s = frame[c].astype(str).str.strip()
            s = s.mask(s.str.lower().isin(["", "nan", "none", "<na>"]))
            combined = s if combined is None else combined.fillna(s)
        return combined if combined is not None else pd.Series([pd.NA] * len(frame), index=frame.index)

    for chunk in _read_tsv_chunks(assignee_path, chunksize):
        if assignee_cols is None:
            assignee_cols = _resolve_assignee_columns(list(chunk.columns))
        if patent_allowlist is not None:
            chunk = chunk[chunk["patent_id"].isin(patent_allowlist)]
        if chunk.empty:
            continue
        seq = pd.to_numeric(chunk["assignee_sequence"], errors="coerce").fillna(0).astype(int)
        aids = _combine_assignee_series(chunk, assignee_cols)
        pid_series = chunk["patent_id"].astype(str).str.strip()
        valid = aids.notna() & aids.astype(str).str.strip().ne("")
        if valid.any():
            company_ids.update(aids[valid].astype(str).unique().tolist())
        zero_mask = seq == 0
        take = zero_mask & valid
        if take.any():
            z = pd.DataFrame({"patent_id": pid_series[take], "_aid": aids[take].astype(str).str.strip()})
            z = z[z["_aid"].ne("")]
            z = z.drop_duplicates(subset=["patent_id"], keep="first")
            for pid, aid in zip(z["patent_id"], z["_aid"]):
                patent_primary_company.setdefault(pid, aid)

    print("Scanning inventors + relationships ...")
    inventor_path = RAW / "g_inventor_disambiguated.tsv"
    inventor_profiles: dict[str, dict[str, str]] = {}

    relationships_path = PROCESSED / "clean_relationships.csv"
    header_written = False
    for chunk in _read_tsv_chunks(inventor_path, chunksize):
        if patent_allowlist is not None:
            chunk = chunk[chunk["patent_id"].isin(patent_allowlist)]
        if chunk.empty:
            continue
        merged = chunk.merge(locations, on="location_id", how="left")
        merged["disambig_country"] = merged["disambig_country"].fillna("")
        merged["fn"] = merged["disambig_inventor_name_first"].fillna("").astype(str).str.strip()
        merged["ln"] = merged["disambig_inventor_name_last"].fillna("").astype(str).str.strip()
        merged["name"] = (merged["fn"] + " " + merged["ln"]).str.replace(r"\s+", " ", regex=True).str.strip()

        pid_col = merged["patent_id"].astype(str).str.strip()
        iid_col = merged["inventor_id"].astype(str).str.strip()
        cid_col = pid_col.map(patent_primary_company).fillna("")

        rel_df = pd.DataFrame({"patent_id": pid_col, "inventor_id": iid_col, "company_id": cid_col}).drop_duplicates(
            subset=["patent_id", "inventor_id"]
        )
        rel_df.to_csv(
            relationships_path,
            mode="w" if not header_written else "a",
            header=not header_written,
            index=False,
        )
        header_written = True

        last_rows = merged.drop_duplicates(subset=["inventor_id"], keep="last")
        for iid, nm, ct in zip(last_rows["inventor_id"].astype(str).str.strip(), last_rows["name"], last_rows["disambig_country"]):
            profile = inventor_profiles.get(iid)
            if profile is None:
                inventor_profiles[iid] = {"name": nm, "country": ct}
            else:
                if not profile["name"] and nm:
                    profile["name"] = nm
                if ct and not profile["country"]:
                    profile["country"] = ct

    if not header_written:
        pd.DataFrame(columns=["patent_id", "inventor_id", "company_id"]).to_csv(relationships_path, index=False)

    print(f"Writing {PROCESSED / 'clean_inventors.csv'} ...")
    inv_rows = [{"inventor_id": iid, **vals} for iid, vals in sorted(inventor_profiles.items())]
    pd.DataFrame(inv_rows).to_csv(PROCESSED / "clean_inventors.csv", index=False)

    print(f"Writing {PROCESSED / 'clean_companies.csv'} ...")
    comp_rows = [
        {"company_id": cid, "name": company_names.get(cid, "Unknown organization")}
        for cid in sorted(company_ids)
    ]
    pd.DataFrame(comp_rows).to_csv(PROCESSED / "clean_companies.csv", index=False)

    abstract_map: dict[str, str] = {}
    abstract_sql_con: sqlite3.Connection | None = None
    abstract_path = RAW / "g_patent_abstract.tsv"
    if abstract_path.exists():
        print("Indexing abstracts ...")
        if patent_allowlist is not None:
            abs_pid_col = abs_txt_col = None
            for chunk in _read_tsv_chunks(abstract_path, chunksize):
                cols = list(chunk.columns)
                if abs_pid_col is None:
                    abs_pid_col = next((c for c in cols if c.lower() == "patent_id"), cols[0])
                    abs_txt_col = next(
                        (c for c in cols if "abstract" in c.lower()),
                        cols[1] if len(cols) > 1 else cols[0],
                    )
                chunk = chunk[[abs_pid_col, abs_txt_col]].dropna(subset=[abs_pid_col])
                chunk = chunk[chunk[abs_pid_col].isin(patent_allowlist)]
                if chunk.empty:
                    continue
                for pid, txt in zip(chunk[abs_pid_col].astype(str), chunk[abs_txt_col].astype(str)):
                    abstract_map[str(pid)] = txt
        else:
            print("Building disk-backed SQLite index for abstracts (full corpus) ...")
            abstract_sql_con = _build_abstract_sqlite(abstract_path, chunksize)

    cpc_best: dict[str, tuple[int, str]] = {}
    cpc_path = RAW / "g_cpc_current.tsv"
    if cpc_path.exists():
        print("Indexing primary CPC codes ...")
        for chunk in _read_tsv_chunks(cpc_path, chunksize):
            cols_lc = {c.lower(): c for c in chunk.columns}
            pid_col = cols_lc.get("patent_id")
            seq_col = cols_lc.get("cpc_sequence")
            sub_col = (
                cols_lc.get("cpc_subsection")
                or cols_lc.get("cpc_subclass")
                or cols_lc.get("cpc_group")
                or cols_lc.get("cpc_class")
            )
            if pid_col is None or sub_col is None:
                continue
            work = chunk[[pid_col, sub_col] + ([seq_col] if seq_col else [])].copy()
            work[pid_col] = work[pid_col].astype(str).str.strip()
            if seq_col:
                work["_seq"] = pd.to_numeric(work[seq_col], errors="coerce").fillna(0).astype(int)
                work = work.sort_values("_seq")
            first = work.groupby(pid_col, sort=False).first()
            for pid, row in first.iterrows():
                seq_val = int(row["_seq"]) if seq_col and "_seq" in first.columns else 0
                code = str(row[sub_col]).strip()
                prev = cpc_best.get(pid)
                if prev is None or seq_val < prev[0]:
                    cpc_best[pid] = (seq_val, code)
        cpc_map = {pid: val[1] for pid, val in cpc_best.items()}
    else:
        cpc_map = {}

    print(f"Writing {PROCESSED / 'clean_patents.csv'} ...")
    patent_parts: list[pd.DataFrame] = []
    try:
        for chunk in _read_tsv_chunks(patent_path, chunksize):
            if patent_allowlist is not None:
                chunk = chunk[chunk["patent_id"].isin(patent_allowlist)]
            if chunk.empty:
                continue
            pid_series = chunk["patent_id"].astype(str).str.strip()
            grant_dates = chunk["patent_date"].fillna("").astype(str).str.strip()
            if app_dates:
                mapped = pid_series.map(app_dates)
                filing_series = mapped.where(mapped.notna() & (mapped.astype(str).str.strip() != ""), grant_dates)
            else:
                filing_series = grant_dates

            if abstract_sql_con is not None:
                uids = pid_series.unique().tolist()
                loc_ab = _abstract_lookup_sql(abstract_sql_con, uids)
                abstract_series = pid_series.map(loc_ab).fillna("").astype(str)
            else:
                abstract_series = pid_series.map(lambda p: abstract_map.get(p, ""))

            filing_year = filing_series.astype(str).map(_parse_year)
            grant_year = chunk["patent_date"].map(_parse_year)
            year_series = filing_year.where(filing_year.notna(), grant_year)

            out = pd.DataFrame(
                {
                    "patent_id": pid_series,
                    "title": chunk["patent_title"].fillna("").astype(str),
                    "abstract": abstract_series,
                    "filing_date": filing_series.astype(str),
                    "year": year_series,
                    "cpc_primary": pid_series.map(lambda p: cpc_map.get(p, "")),
                }
            )

            patent_parts.append(out)

        if not patent_parts:
            raise RuntimeError("No patent rows written. Check filters and raw files.")
        pd.concat(patent_parts, ignore_index=True).to_csv(PROCESSED / "clean_patents.csv", index=False)
    finally:
        if abstract_sql_con is not None:
            tmp_path = getattr(abstract_sql_con, "_pv_tmp_path", None)
            abstract_sql_con.close()
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)

    print("Done.")
    print(f"  {PROCESSED / 'clean_patents.csv'}")
    print(f"  {PROCESSED / 'clean_inventors.csv'}")
    print(f"  {PROCESSED / 'clean_companies.csv'}")
    print(f"  {relationships_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Clean PatentsView TSV exports into data/processed CSVs.")
    p.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N patents in g_patent.tsv (by file order).",
    )
    p.add_argument("--chunk-size", type=int, default=50_000, help="Rows per pandas chunk.")
    args = p.parse_args()
    run_clean(sample=args.sample, chunksize=args.chunk_size)


if __name__ == "__main__":
    main()
