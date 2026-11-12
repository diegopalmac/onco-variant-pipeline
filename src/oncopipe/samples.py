"""Fictional preliminary reports (PDF) and a simulated LLM for the demo app.

The public demo cannot ship an API key, so the model call is replaced by a
stand-in that answers with the known content of each sample report. It also
cuts long answers short on the first call, the way a real model does when it
hits its output limit, so the continuation logic runs for real.
"""
import json
import random
import re
from pathlib import Path

from . import synthetic

# Everything below is invented: names, IDs and dates belong to no one.
PEOPLE = [
    ("Ana Ejemplo", "1961-03-14", "11.111.111-1", 9),
    ("Pedro Muestra", "1954-11-02", "12.222.222-2", 14),
    ("Laura Ficticia", "1970-06-23", "13.333.333-3", 22),
    ("Carlos Prueba", "1949-01-30", "14.444.444-4", 58),   # long report: triggers truncation
]
OUTPUT_LIMIT = 6000  # characters the simulated model returns per call
DEMO_TODAY = (2025, 12, 31)  # fixed "today" so the demo always computes the same ages


def sample_cases() -> list:
    """Four deterministic cases: report content plus the identifiers printed on the PDF."""
    rng = random.Random(7)
    base = synthetic.generate_reports(4, seed=2025)
    cases = []
    for index, (report, (name, born, national_id, n_vus)) in enumerate(zip(base, PEOPLE), start=1):
        report = dict(report, paciente_id=f"SYN-9{index:03d}", edad=str(2025 - int(born[:4])))
        known = [v for v in report["variantes"] if v["tier"] != "III"][:3]
        vus = [synthetic._variant(synthetic._random_vus(rng), rng) for _ in range(n_vus)]
        report["variantes"] = known + vus
        cases.append({"name": name, "born": born, "national_id": national_id, "report": report})
    return cases


def write_pdf(case: dict, path: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    report, styles = case["report"], getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    story = [
        Paragraph("Comprehensive Genomic Profile: Preliminary Report", styles["Title"]),
        Paragraph("SYNTHETIC SAMPLE. Fictional patient, random data, no clinical meaning.", styles["Italic"]),
        Spacer(1, 10),
    ]
    for line in [
        f"Patient Name: {case['name']}",
        f"Date of Birth: {case['born']}",
        f"National ID: {case['national_id']}",
        f"Sample ID: {report['paciente_id']}",
        f"Sex: {report['sexo']}",
        f"Diagnosis: {report['tipo_cancer']}",
        "Specimen: Blood/DNA",
        f"Report Date: {report['fecha de reporte']}",
        f"Blood Microsatellite Status: {report['Blood_Microsatellite_Status']}",
        f"Blood Tumor Mutation Burden: {report['Blood_Tumor_Mutation_Burden']}",
    ]:
        story.append(Paragraph(line, styles["BodyText"]))

    def table(title, tiers):
        rows = [v for v in report["variantes"] if v["tier"] in tiers]
        story.extend([Spacer(1, 14), Paragraph(f"{title} ({len(rows)})", styles["Heading3"])])
        data = [["Tier", "Gene", "Test result", "Abundance", "Subregion", "Transcript", "Sensitive therapies"]]
        for v in rows:
            data.append([v["tier"], v["gen"], Paragraph(v["resultado_test"], small), v["abundancia"],
                         v["subregion"], v["transcript"], Paragraph(v["terapias_sensibles"], small)])
        grid = Table(data, repeatRows=1, colWidths=[28, 52, 130, 55, 52, 70, 110])
        grid.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef5")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8c8c8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(grid)

    table("Clinically significant variations: Tier I and Tier II", ("I", "II"))
    table("Variants of uncertain significance: Tier III", ("III",))
    SimpleDocTemplate(path, pagesize=A4, title="Synthetic preliminary report",
                      leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40).build(story)


def write_samples(folder: str) -> list:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for case in sample_cases():
        path = out / f"{case['report']['paciente_id']}_preliminary_report.pdf"
        write_pdf(case, str(path))
        paths.append(path)
    return paths


def simulated_generate(prompt: str) -> str:
    """Stand-in for the model call. Same contract as ``extract.gemini_generate()``."""
    truth = {case["report"]["paciente_id"]: case["report"] for case in sample_cases()}
    sample_id = re.search(r"Sample ID:\s*(SYN-\d+)", prompt)
    if not sample_id or sample_id.group(1) not in truth:
        raise ValueError("The simulated model only knows the bundled sample reports.")
    answer = json.dumps(truth[sample_id.group(1)], indent=2, ensure_ascii=False)

    partial = re.search(r"Tu respuesta quedó incompleta:\n\n(.*)\n\nContinúa el JSON", prompt, re.S)
    if partial:  # continuation call: return only what is missing
        return answer[len(partial.group(1)):]
    return answer[:OUTPUT_LIMIT]
