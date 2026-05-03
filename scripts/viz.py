"""Optional matplotlib chart for patents-per-year (reads reports/report.json)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot patents-by-year from report.json.")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "report.json")
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "patents_per_year.png")
    args = parser.parse_args()

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required for viz.py (`pip install matplotlib`).") from exc

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    rows = payload.get("patents_by_year") or []
    if not rows:
        raise SystemExit("No patents_by_year series found - run analyze.py first.")

    years = [r["year"] for r in rows]
    counts = [r["patents"] for r in rows]

    plt.figure(figsize=(10, 4))
    plt.plot(years, counts, linewidth=1.2)
    plt.title("Granted patents per year (subset reflects pipeline filters)")
    plt.xlabel("Year")
    plt.ylabel("Patents")
    plt.grid(True, alpha=0.25)
    plt.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.out, dpi=150)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
