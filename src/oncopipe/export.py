"""Excel export used to build the final report."""
import io

import pandas as pd

PATIENT_FIELDS = ["paciente_id", "edad", "sexo", "tipo_cancer", "tipo_muestra", "fecha de reporte",
                  "Blood_Microsatellite_Status", "Blood_Tumor_Mutation_Burden"]
VARIANT_FIELDS = ["tier", "gen", "resultado_test", "abundancia", "subregion", "transcript",
                  "terapias_sensibles", "terapias_resistentes"]


def report_excel(data: dict) -> bytes:
    """Two sheets, patient and variants, ready to paste into the report template."""
    patient = pd.DataFrame([{field: data.get(field, "") for field in PATIENT_FIELDS}])
    variants = pd.DataFrame(data.get("variantes", [])).reindex(columns=VARIANT_FIELDS).fillna("")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        patient.to_excel(writer, sheet_name="Patient", index=False)
        variants.to_excel(writer, sheet_name="Variants", index=False)
    return buffer.getvalue()
