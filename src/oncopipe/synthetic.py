"""Generate fictional reports in the standard JSON format.

Nothing here is derived from real patients. Tier I/II entries reuse a few
textbook hotspot notations so the data looks familiar; Tier III variants
sit on fictional genes (SYNG01...), and all frequencies, ages and therapy
labels are random. The output has no clinical
meaning and exists only to exercise the pipeline.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

# (label written in the report, sex constraint, mean age). Several labels map
# to the same group on purpose: reports name the same cancer in different ways.
CANCERS = [
    ("Prostate Cancer", "Male", 68),
    ("Colorectal Cancer", None, 60),
    ("Colon Cancer", None, 61),
    ("Non-Small Cell Lung Cancer", None, 66),
    ("Lung Cancer", None, 67),
    ("Breast Cancer", "Female", 57),
    ("Pancreatic Cancer", None, 64),
    ("Gastric Cancer", None, 59),
    ("Ovarian Cancer", "Female", 58),
]
CANCER_WEIGHTS = [20, 12, 6, 12, 5, 18, 10, 9, 8]

# gene, result, exon, RefSeq transcript, tier
HOTSPOTS = [
    ("KRAS", "p.G12D (c.35G>A)", "EX2", "NM_004985", "I"),
    ("KRAS", "p.G12V (c.35G>T)", "EX2", "NM_004985", "I"),
    ("KRAS", "p.G12C (c.34G>T)", "EX2", "NM_004985", "I"),
    ("KRAS", "p.G13D (c.38G>A)", "EX2", "NM_004985", "II"),
    ("BRAF", "p.V600E (c.1799T>A)", "EX15", "NM_004333", "I"),
    ("EGFR", "p.L858R (c.2573T>G)", "EX21", "NM_005228", "I"),
    ("EGFR", "p.T790M (c.2369C>T)", "EX20", "NM_005228", "I"),
    ("PIK3CA", "p.H1047R (c.3140A>G)", "EX21", "NM_006218", "II"),
    ("PIK3CA", "p.E545K (c.1633G>A)", "EX10", "NM_006218", "II"),
    ("PIK3CA", "p.E542K (c.1624G>A)", "EX10", "NM_006218", "II"),
    ("TP53", "p.R175H (c.524G>A)", "EX5", "NM_000546", "II"),
    ("TP53", "p.R248Q (c.743G>A)", "EX7", "NM_000546", "II"),
    ("TP53", "p.R273H (c.818G>A)", "EX8", "NM_000546", "II"),
    ("NRAS", "p.Q61R (c.182A>G)", "EX3", "NM_002524", "II"),
    ("APC", "p.R1450* (c.4348C>T)", "EX16", "NM_000038", "II"),
    ("ERBB2", "copy number gain", "", "NM_004448", "I"),
    ("AR", "copy number gain", "", "NM_000044", "II"),
    ("PTEN", "copy number loss", "", "NM_000314", "II"),
]

VUS_GENES = [f"SYNG{i:02d}" for i in range(1, 17)]  # fictional gene names
AMINO = "ACDEFGHIKLMNPQRSTVWY"
BASES = "ACGT"


def _random_vus(rng: random.Random):
    """A made-up missense variant. Positions and changes are random."""
    gene = rng.choice(VUS_GENES)
    position = rng.randint(20, 1800)
    ref, alt = rng.sample(AMINO, 2)
    base_ref, base_alt = rng.sample(BASES, 2)
    cdna = position * 3 - rng.randint(0, 2)
    result = f"p.{ref}{position}{alt} (c.{cdna}{base_ref}>{base_alt})"
    return gene, result, f"EX{rng.randint(2, 30)}", "", "III"


def _variant(entry, rng: random.Random) -> dict:
    gene, result, exon, transcript, tier = entry
    copy_number = result.startswith("copy number")
    actionable = tier in ("I", "II") and rng.random() < 0.5
    return {
        "tier": tier,
        "gen": gene,
        "resultado_test": result,
        "abundancia": "N/A" if copy_number else f"{rng.uniform(0.1, 45):.2f}%",
        "subregion": exon,
        "transcript": transcript,
        "terapias_sensibles": f"Therapy-{rng.choice('ABCDEF')} (Level {rng.choice('AB')})" if actionable else "",
        "terapias_resistentes": "",
    }


def generate_reports(n: int = 120, seed: int = 42) -> list:
    rng = random.Random(seed)
    # A pool of recurring fictional VUS so that frequency and co-occurrence
    # analyses have something to find.
    recurring = [_random_vus(rng) for _ in range(40)]
    recurring_weights = [1 / (rank + 4) for rank in range(len(recurring))]

    reports = []
    for index in range(1, n + 1):
        cancer, sex, mean_age = rng.choices(CANCERS, weights=CANCER_WEIGHTS)[0]
        chosen = {}
        for entry in rng.sample(HOTSPOTS, rng.randint(0, 3)):
            chosen[(entry[0], entry[1])] = entry
        for entry in rng.choices(recurring, weights=recurring_weights, k=rng.randint(3, 9)):
            chosen[(entry[0], entry[1])] = entry
        for _ in range(rng.randint(2, 10)):
            entry = _random_vus(rng)
            chosen[(entry[0], entry[1])] = entry

        tmb = rng.lognormvariate(1.2, 0.8)
        reports.append({
            "paciente_id": f"SYN-{index:04d}",
            "edad": str(max(30, min(90, round(rng.gauss(mean_age, 9))))),
            "sexo": sex or rng.choice(["Male", "Female"]),
            "tipo_cancer": cancer,
            "tipo_muestra": "ctDNA",
            "fecha de reporte": (date(2025, 1, 6) + timedelta(days=rng.randint(0, 170))).isoformat(),
            "Blood_Microsatellite_Status": "MSI-H" if rng.random() < 0.05 else "MSI-L/MSS",
            "Blood_Tumor_Mutation_Burden": "<1 Muts/Mb" if tmb < 1 else f"{tmb:.2f} Muts/Mb",
            "variantes": [_variant(entry, rng) for entry in chosen.values()],
        })
    return reports


def write_reports(folder: str, n: int = 120, seed: int = 42) -> int:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for report in generate_reports(n, seed):
        path = out / f"{report['paciente_id']}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return n
