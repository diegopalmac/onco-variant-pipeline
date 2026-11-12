"""End-to-end demo on synthetic data: generate -> load -> analyse.

    python scripts/run_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncopipe import analysis, database, synthetic  # noqa: E402

DATA = ROOT / "data" / "synthetic"
DB = ROOT / "data" / "demo.db"
FIGURES = ROOT / "docs" / "figures"


def main():
    DB.unlink(missing_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    n = synthetic.write_reports(DATA)
    print(f"1. Generated {n} synthetic reports in {DATA.relative_to(ROOT)}")

    summary = database.load_folder(str(DB), str(DATA))
    print(f"2. Loaded {summary['files']} files, {summary['inserted']} variants "
          f"({summary['errors']} errors)")
    again = database.load_folder(str(DB), str(DATA))
    print(f"   Re-run inserted {again['inserted']} variants (duplicates are skipped)")

    patients, variants = analysis.load_tables(str(DB))
    largest = patients["cancer_group"].value_counts().index[0]
    print(f"3. {len(patients)} patients, {len(variants)} variants, "
          f"{patients['cancer_group'].nunique()} cancer groups")
    print(f"\nTop Tier III variants in {largest.lower()} (patients):")
    print(analysis.top_variants(variants, tier=3, cancer_group=largest, n=5).to_string(index=False))

    analysis.plot_cancer_types(patients, str(FIGURES / "cancer_types.png"))
    analysis.plot_age_by_cancer(patients, str(FIGURES / "age_by_cancer.png"))
    analysis.plot_cooccurrence(analysis.cooccurrence(variants, largest), largest,
                               str(FIGURES / "cooccurrence.png"))
    print(f"\n4. Figures saved in {FIGURES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
