"""Create the fictional PDF reports used by the demo app (needs reportlab)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncopipe import samples  # noqa: E402

for path in samples.write_samples(str(ROOT / "samples")):
    print(path.relative_to(ROOT))
