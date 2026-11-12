import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oncopipe import avenio, database, synthetic  # noqa: E402
from datetime import date

from oncopipe.extract import deidentify, extract_report, redact_patient_name  # noqa: E402
from oncopipe.json_repair import repair_truncated_json  # noqa: E402

FULL = {
    "paciente_id": "SYN-0001", "edad": "61", "sexo": "Male", "tipo_cancer": "Prostate Cancer",
    "tipo_muestra": "ctDNA", "fecha de reporte": "2025-03-01",
    "Blood_Microsatellite_Status": "MSI-L/MSS", "Blood_Tumor_Mutation_Burden": "<1 Muts/Mb",
    "variantes": [
        {"tier": "I", "gen": "ERBB2", "resultado_test": "copy number gain", "abundancia": "N/A"},
        {"tier": "II-C", "gen": "AR", "resultado_test": "copy number gain", "abundancia": "N/A"},
        {"tier": "III", "gen": "ATM", "resultado_test": "p.A10V (c.29C>T)", "abundancia": "0.23%"},
        {"tier": "III", "gen": "TP53", "resultado_test": "wildtype", "abundancia": ""},
    ],
}


def test_patient_name_is_removed_before_the_api_call():
    text = "Report\nPatient Name: Jane Doe\nSample ID: SYN-0001\nNombre Paciente - Juan Pérez\n"
    cleaned = redact_patient_name(text)
    assert "Jane" not in cleaned and "Juan" not in cleaned
    assert "SYN-0001" in cleaned


def test_deidentify_replaces_birth_date_with_age_and_masks_ids():
    text = "Name: Jane Doe\nDate of Birth: 1960-07-15\nRUT 12.345.678-9\nSample ID: SYN-0001\nReport date: 2025-03-01\n"
    cleaned = deidentify(text, today=date(2025, 3, 1))
    assert "Jane" not in cleaned and "1960" not in cleaned and "12.345.678-9" not in cleaned
    assert "Age: 64" in cleaned and "SYN-0001" in cleaned and "2025-03-01" in cleaned


def test_unreadable_birth_date_is_dropped_not_leaked():
    assert "sometime" not in deidentify("DOB: sometime in 1960\nSample ID: X\n")


def test_repair_keeps_only_complete_variants():
    text = json.dumps(FULL)
    cut = text[: text.index('"TP53"') + 10]  # stops in the middle of the 4th variant
    repaired = json.loads(repair_truncated_json(cut))
    assert [v["gen"] for v in repaired["variantes"]] == ["ERBB2", "AR", "ATM"]


def test_repair_handles_braces_inside_strings():
    cut = '{"paciente_id": "X", "variantes": [{"gen": "A", "resultado_test": "p.{odd}"}, {"gen": "B'
    assert len(json.loads(repair_truncated_json(cut))["variantes"]) == 1


def test_truncated_response_is_completed_with_a_second_call():
    text = json.dumps(FULL)
    half = len(text) // 2
    replies = iter([text[:half], text[half:]])
    prompts = []

    def fake_llm(prompt):
        prompts.append(prompt)
        return next(replies)

    assert extract_report("report text", fake_llm) == FULL
    assert len(prompts) == 2 and text[:half] in prompts[1]


def test_falls_back_to_repair_when_the_model_never_finishes():
    text = json.dumps(FULL)
    cut = text[: text.index('"TP53"') + 10]
    replies = iter([cut, ""])
    data = extract_report("report text", lambda prompt: next(replies))
    assert len(data["variantes"]) == 3


def test_loader_parses_formats_and_is_idempotent(tmp_path):
    folder = tmp_path / "jsons"
    folder.mkdir()
    (folder / "a.json").write_text(json.dumps(FULL), encoding="utf-8")
    db = str(tmp_path / "test.db")

    first = database.load_folder(db, str(folder))
    second = database.load_folder(db, str(folder))
    assert first["inserted"] == 3      # wildtype is skipped
    assert second["inserted"] == 0     # nothing is duplicated on re-run

    import sqlite3
    with sqlite3.connect(db) as conn:
        tmb, = conn.execute("SELECT blood_tumor_mutation_burden FROM pacientes").fetchone()
        rows = conn.execute("SELECT gen, tier, abundancia FROM variantes ORDER BY gen").fetchall()
    assert tmb == 1.0
    # Two genes with the same result text are both kept.
    assert rows == [("AR", 2, None), ("ATM", 3, 0.23), ("ERBB2", 1, None)]


def test_bad_report_date_does_not_lose_the_patient(tmp_path):
    folder = tmp_path / "jsons"
    folder.mkdir()
    (folder / "a.json").write_text(json.dumps({**FULL, "fecha de reporte": "N/A"}), encoding="utf-8")
    summary = database.load_folder(str(tmp_path / "t.db"), str(folder))
    assert summary["errors"] == 0 and summary["inserted"] == 3


def test_avenio_mapping():
    record = {
        "specimen": "SYN-A1", "sex": "female", "disease-ontology": "Lung Cancer",
        "biomarkers": {"microsatellite-instability": {"status": "MSS"},
                       "tumor-mutation-burden": {"score": 4.2}},
        "short-variants": [{
            "status": "likely", "percent-reads": 1.5,
            "short-variant-intragenic-annotation": [
                {"gene": {"symbol": "X1"}, "hgvs-protein-effect": "p.A1B"},
                {"primary": True, "gene": {"symbol": "EGFR"}, "hgvs-protein-effect": "p.L858R",
                 "hgvs-transcript-effect": "c.2573T>G", "start-affected-component-number": 21,
                 "transcript": [{"transcript-refseq-id": "NM_005228"}]},
            ],
        }],
    }
    out = avenio.transform(record, "x_2025-01-10T22_46_49.Variants.json")
    assert out["fecha de reporte"] == "2025-01-10"
    assert out["Blood_Microsatellite_Status"] == "MSI-L/MSS"
    assert out["variantes"][0] == {
        "tier": "II", "gen": "EGFR", "resultado_test": "p.L858R c.2573T>G", "abundancia": "1.5%",
        "subregion": "EX21", "transcript": "NM_005228", "terapias_sensibles": "",
        "terapias_resistentes": "",
    }


def test_synthetic_data_is_reproducible():
    assert synthetic.generate_reports(5, seed=1) == synthetic.generate_reports(5, seed=1)
