"""Validate bulk-download inputs under data/raw and print pointers for optional enrichments."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

REQUIRED = (
    "g_patent.tsv",
    "g_inventor_disambiguated.tsv",
    "g_persistent_assignee.tsv",
    "g_location_disambiguated.tsv",
)

OPTIONAL_HINTS = (
    ("g_patent_abstract.tsv", "Adds abstracts on patents."),
    ("g_assignee_disambiguated.tsv", "Maps persistent assignee IDs to readable organization names."),
    ("g_application.tsv", "Lets filing_date reflect application filing instead of grant date."),
    ("g_cpc_current.tsv", "Populates CPC classification codes."),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check PatentsView bulk files under data/raw.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if required files are missing.")
    args = parser.parse_args()

    missing = [fn for fn in REQUIRED if not (RAW / fn).exists()]
    print(f"Checking {RAW.resolve()} ...")

    if missing:
        print("MISSING required files:")
        for fn in missing:
            print(f"  - {fn}")
        print("\nDownload from PatentsView bulk exports:")
        print("  https://data.uspto.gov/bulkdata/datasets/pvgpatdis")
        if args.strict:
            raise SystemExit(1)
    else:
        print("All required PatentsView slices are present.")

    print("\nOptional enrichments (copy into data/raw/):")
    for fn, hint in OPTIONAL_HINTS:
        status = "present" if (RAW / fn).exists() else "missing"
        print(f"  - {fn} [{status}] - {hint}")

    print("\nNext steps:")
    print("  python scripts/clean.py --sample 25000")
    print("  python scripts/load.py")
    print("  python scripts/analyze.py")


if __name__ == "__main__":
    main()
