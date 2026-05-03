"""Load cleaned CSVs produced by clean.py into SQLite using sql/schema.sql."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "database" / "patents.db"
DEFAULT_SCHEMA = ROOT / "sql" / "schema.sql"
PROCESSED = ROOT / "data" / "processed"


def load_table(con: sqlite3.Connection, csv_path: Path, table: str, chunksize: int, empty_na_cols: tuple[str, ...] = ()) -> None:
    first = True
    for chunk in pd.read_csv(csv_path, chunksize=chunksize):
        for col in empty_na_cols:
            if col in chunk.columns:
                chunk[col] = chunk[col].replace("", pd.NA)
        chunk.to_sql(table, con, if_exists="replace" if first else "append", index=False)
        first = False


def run_load(db_path: Path, schema_path: Path, chunksize: int) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    patents_csv = PROCESSED / "clean_patents.csv"
    inventors_csv = PROCESSED / "clean_inventors.csv"
    companies_csv = PROCESSED / "clean_companies.csv"
    relationships_csv = PROCESSED / "clean_relationships.csv"

    for path in (patents_csv, inventors_csv, companies_csv, relationships_csv):
        if not path.exists():
            raise FileNotFoundError(f"Missing processed file {path}; run scripts/clean.py first.")

    ddl = schema_path.read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as con:
        con.executescript(ddl)
        load_table(con, patents_csv, "patents", chunksize)
        load_table(con, inventors_csv, "inventors", chunksize)
        load_table(con, companies_csv, "companies", chunksize)
        load_table(con, relationships_csv, "relationships", chunksize, empty_na_cols=("company_id",))
        con.execute(
            """
            DELETE FROM relationships
            WHERE rowid NOT IN (
              SELECT MIN(rowid) FROM relationships GROUP BY patent_id, inventor_id
            );
            """
        )

    print(f"Loaded SQLite database at {db_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Load cleaned CSVs into SQLite.")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path.")
    p.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="DDL schema path.")
    p.add_argument("--chunk-size", type=int, default=50_000)
    args = p.parse_args()
    run_load(db_path=args.db, schema_path=args.schema, chunksize=args.chunk_size)


if __name__ == "__main__":
    main()
