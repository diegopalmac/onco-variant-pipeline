"""PDF report -> de-identified text -> LLM -> standard JSON.

The LLM call is injected as a plain function (``generate(prompt) -> str``) so
the control flow can be tested without network access or an API key.
"""
import json
import os
import re
from datetime import date, datetime
from typing import Callable, List, Optional

from .json_repair import repair_truncated_json

Generate = Callable[[str], str]

SCHEMA = """{
    "paciente_id": "",
    "edad": "",
    "sexo": "",
    "tipo_cancer": "",
    "tipo_muestra": "ctDNA",
    "fecha de reporte": "",
    "Blood_Microsatellite_Status": "",
    "Blood_Tumor_Mutation_Burden": "",
    "variantes": [
        {
            "tier": "",
            "gen": "",
            "resultado_test": "",
            "abundancia": "",
            "subregion": "",
            "transcript": "",
            "terapias_sensibles": "",
            "terapias_resistentes": ""
        }
    ]
}"""


NAME_LINE = re.compile(
    r"(?im)^[ \t]*(Patient(?:'s)? Name|Nombre(?: del)? Paciente|Paciente|Name|Nombre)[ \t]*[:–\-][ \t]*.*\n?"
)
BIRTH_LINE = re.compile(
    r"(?im)^[ \t]*(Date of Birth|DOB|Birth ?date|Fecha de Nacimiento)[ \t]*[:–\-][ \t]*(.*)$"
)
NATIONAL_ID = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")  # Chilean RUT
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y")


def _parse_date(text: str) -> Optional[date]:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def redact_patient_name(text: str) -> str:
    """Drop any line that carries the patient's name."""
    return NAME_LINE.sub("", text) if text else text


def deidentify(text: str, today: Optional[date] = None) -> str:
    """Remove direct identifiers before the text leaves the machine.

    - name lines are dropped;
    - the date of birth is replaced by the age, computed locally, so the
      model never sees it;
    - national ID numbers (RUT) are masked.
    The sample code stays: it is the only key the database uses.
    """
    if not text:
        return text
    today = today or date.today()

    def birth_to_age(match):
        born = _parse_date(match.group(2))
        if born is None:
            return ""  # unreadable date: drop the line rather than leak it
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return f"Age: {age}"

    text = NAME_LINE.sub("", text)
    text = BIRTH_LINE.sub(birth_to_age, text)
    return NATIONAL_ID.sub("[ID]", text)


def extract_text_from_pdf(pdf_path: str, pages: Optional[List[int]] = None) -> str:
    """Extract text from a PDF. ``pages`` is 1-indexed; None means every page."""
    import pdfplumber  # imported here so the rest of the package works without it

    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for number in pages or range(1, total + 1):
            if 1 <= number <= total:
                page_text = pdf.pages[number - 1].extract_text(x_tolerance=1, y_tolerance=1)
                if page_text:
                    chunks.append(page_text.strip())
    return "\n\n".join(chunks)


def build_prompt(report_text: str, max_tier_iii: Optional[int] = 60) -> str:
    """Extraction prompt. Written in Spanish, the lab's working language."""
    if max_tier_iii is None:
        tier_iii_rule = '- Extrae todas las variantes "Tier III" que encuentres.'
    else:
        tier_iii_rule = (
            f'- Para las variantes "Tier III", extrae como máximo las primeras '
            f"{max_tier_iii}. Si hay más, omite las restantes."
        )
    return f"""
Extrae información de un reporte genético clínico. Devuelve solo JSON válido
con esta estructura exacta:

{SCHEMA}

Datos personales y biomarcadores (portada o sección inicial):
- Sample ID o Barcode -> paciente_id
- Edad
- Sexo ("Male" o "Female")
- Tipo de cáncer en inglés, ej: "Prostate Cancer"
- Fecha del reporte (YYYY-MM-DD)
- Blood Microsatellite Status, ej: "MSI-L/MSS"
- Blood Tumor Mutation Burden con unidad, ej: "1.25 Muts/Mb"

Variantes:
- "Tier I" y "Tier II" (clinically significant): extrae TODAS.
- "Tier III" (variants of uncertain significance).
{tier_iii_rule}
Para cada variante: tier (solo el número romano), gen, resultado del test
(ej: "p.G12D (c.35G>A)", "copy number loss"), abundancia, subregión,
transcript, terapias sensibles y terapias resistentes (separadas por comas,
con su nivel de evidencia entre paréntesis).

Criterios:
- Las tablas pueden estar cortadas entre páginas: reconstrúyelas.
- No incluyas dos veces una variante del resumen inicial si se detalla después.
- No inventes datos ni uses ejemplos: solo lo que está en el texto.

Texto del reporte:
{report_text}
"""


def build_continuation_prompt(report_text: str, partial_json: str) -> str:
    return f"""
Texto original del reporte:
{report_text}

Antes te pedí extraer este texto a JSON. Tu respuesta quedó incompleta:

{partial_json}

Continúa el JSON exactamente desde donde se interrumpió. Devuelve SOLO la
parte faltante, sin repetir lo anterior y sin explicaciones, de modo que al
concatenarla con la respuesta parcial se forme un único JSON válido.
"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```$", "", text)
    return text.strip()


def extract_report(
    report_text: str,
    generate: Generate,
    max_completion_retries: int = 1,
    max_tier_iii: Optional[int] = 60,
) -> Optional[dict]:
    """Turn report text into the standard JSON, surviving truncated responses.

    1. Ask for the full JSON.
    2. If it does not parse, ask the model to continue from the partial text
       and join both pieces (up to ``max_completion_retries`` times).
    3. If it still does not parse, keep every complete variant
       (see ``json_repair``).
    """
    partial = ""
    for attempt in range(max_completion_retries + 1):
        if attempt == 0:
            prompt = build_prompt(report_text, max_tier_iii)
        else:
            prompt = build_continuation_prompt(report_text, partial)
        candidate = partial + _strip_code_fence(generate(prompt))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            partial = candidate

    repaired = repair_truncated_json(partial)
    return json.loads(repaired) if repaired else None


def gemini_generate(model_name: Optional[str] = None, api_key: Optional[str] = None) -> Generate:
    """Build a ``generate`` function backed by the Gemini API.

    The key is read from the GOOGLE_API_KEY environment variable and is never
    stored in the code.
    """
    import google.generativeai as genai

    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set the GOOGLE_API_KEY environment variable first.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
    config = genai.types.GenerationConfig(temperature=0, response_mime_type="application/json")

    def generate(prompt: str) -> str:
        return model.generate_content(prompt, generation_config=config).text

    return generate
