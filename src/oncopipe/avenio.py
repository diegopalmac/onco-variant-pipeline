"""Map an AVENIO ``.Variants.json`` export onto the standard JSON.

This platform already exports structured data, so no LLM is needed: the
mapping is deterministic.
"""
import re

TIER_BY_STATUS = {"known": "I", "likely": "II", "ambiguous": "II"}


def map_status(status: str) -> str:
    """known -> I, likely/ambiguous -> II, anything else -> III."""
    return TIER_BY_STATUS.get(status.lower(), "III")


def report_date_from_filename(filename: str) -> str:
    """The export name carries the date, e.g. '..._2025-01-10T22_46_49...json'."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    return match.group(1) if match else ""


def primary_annotation(annotations: list):
    """Prefer the annotation flagged as primary; fall back to the first one."""
    for annotation in annotations:
        if annotation.get("primary", False):
            return annotation
    return annotations[0] if annotations else None


def transform(record: dict, filename: str = "") -> dict:
    biomarkers = record.get("biomarkers", {})
    msi = biomarkers.get("microsatellite-instability", {}).get("status", "")
    tmb = biomarkers.get("tumor-mutation-burden", {})

    variants = []
    for variant in record.get("short-variants", []):
        annotation = primary_annotation(variant.get("short-variant-intragenic-annotation", []))
        if not annotation:
            continue
        transcripts = annotation.get("transcript", [])
        exon = annotation.get("start-affected-component-number")
        variants.append({
            "tier": map_status(variant.get("status", "")),
            "gen": annotation.get("gene", {}).get("symbol", ""),
            "resultado_test": (
                f"{annotation.get('hgvs-protein-effect', '')} "
                f"{annotation.get('hgvs-transcript-effect', '')}"
            ).strip(),
            "abundancia": f"{variant['percent-reads']}%" if variant.get("percent-reads") is not None else "",
            "subregion": f"EX{exon}" if exon is not None else "",
            "transcript": transcripts[0].get("transcript-refseq-id", "") if transcripts else "",
            "terapias_sensibles": "",
            "terapias_resistentes": "",
        })

    return {
        "paciente_id": record.get("specimen", ""),
        "edad": "",  # not present in this export
        "sexo": {"female": "Female", "male": "Male"}.get(record.get("sex", "").lower(), ""),
        "tipo_cancer": record.get("disease-ontology", ""),
        "tipo_muestra": "Tejido",
        "fecha de reporte": report_date_from_filename(filename),
        "Blood_Microsatellite_Status": "MSI-L/MSS" if msi.upper() == "MSS" else msi,
        "Blood_Tumor_Mutation_Burden": f"{tmb['score']} Muts/Mb" if "score" in tmb else "",
        "variantes": variants,
    }
