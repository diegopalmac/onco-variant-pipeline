"""SQLite schema and loader for the standard JSON."""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import (Column, Date, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Paciente(Base):
    __tablename__ = "pacientes"
    paciente_id = Column(String, primary_key=True)  # sample code, never a name
    edad = Column(Integer)
    sexo = Column(String)
    tipo_cancer = Column(String)
    tipo_muestra = Column(String)
    fecha_reporte = Column(Date)
    blood_microsatellite_status = Column(String)
    blood_tumor_mutation_burden = Column(Float)


class Variante(Base):
    __tablename__ = "variantes"
    variante_id = Column(Integer, primary_key=True, autoincrement=True)
    paciente_id = Column(String, ForeignKey("pacientes.paciente_id"))
    tier = Column(Integer)
    gen = Column(String)
    resultado_test = Column(String)
    abundancia = Column(Float)
    subregion = Column(String)
    transcript = Column(String)
    terapias_sensibles = Column(Text)
    terapias_resistentes = Column(Text)

    # Re-running the loader must not duplicate variants.
    __table_args__ = (UniqueConstraint("paciente_id", "gen", "resultado_test", name="uix_variant"),)


def make_engine(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def parse_tier(value: str) -> Optional[int]:
    """'II', 'II-D', 'Tier III' -> 2, 2, 3."""
    match = re.search(r"\b(I{1,3})\b", str(value).upper())
    return len(match.group(1)) if match else None


def parse_number(value) -> Optional[float]:
    """'0.23%', '1.25 Muts/Mb', '<1 Muts/Mb', 'N/A' -> 0.23, 1.25, 1.0, None."""
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def parse_date(value):
    """ISO date, or None when the report date is missing or malformed.

    A bad date must not cost us the whole patient record.
    """
    try:
        return datetime.strptime(str(value or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalise_sex(value) -> str:
    text = str(value or "").strip().lower()
    return {"masculino": "Male", "male": "Male", "femenino": "Female", "female": "Female"}.get(text, "")


def insert_report(session, data: dict) -> Tuple[int, int]:
    """Upsert one patient and add their new variants. Returns (inserted, skipped)."""
    paciente = session.get(Paciente, data["paciente_id"])
    if paciente is None:
        paciente = Paciente(paciente_id=data["paciente_id"])
        session.add(paciente)

    age = parse_number(data.get("edad"))
    paciente.edad = int(age) if age is not None else None
    paciente.sexo = normalise_sex(data.get("sexo"))
    paciente.tipo_cancer = data.get("tipo_cancer", "")
    paciente.tipo_muestra = data.get("tipo_muestra", "")
    paciente.fecha_reporte = parse_date(data.get("fecha de reporte"))
    paciente.blood_microsatellite_status = str(data.get("Blood_Microsatellite_Status", "")).strip()
    paciente.blood_tumor_mutation_burden = parse_number(data.get("Blood_Tumor_Mutation_Burden"))

    known = {
        (v.gen, v.resultado_test)
        for v in session.query(Variante).filter_by(paciente_id=paciente.paciente_id)
    }
    inserted = skipped = 0
    for variant in data.get("variantes", []):
        result = str(variant.get("resultado_test", "")).strip()
        key = (variant.get("gen", ""), result)
        if result.lower() == "wildtype" or key in known:
            skipped += 1
            continue
        known.add(key)
        session.add(Variante(
            paciente_id=paciente.paciente_id,
            tier=parse_tier(variant.get("tier", "")),
            gen=variant.get("gen", ""),
            resultado_test=result,
            abundancia=parse_number(variant.get("abundancia")),
            subregion=variant.get("subregion", ""),
            transcript=variant.get("transcript", ""),
            terapias_sensibles=variant.get("terapias_sensibles", ""),
            terapias_resistentes=variant.get("terapias_resistentes", ""),
        ))
        inserted += 1
    return inserted, skipped


def load_folder(db_path: str, folder: str) -> dict:
    """Load every standard JSON under ``folder`` (recursively). Safe to re-run."""
    engine = make_engine(db_path)
    Session = sessionmaker(bind=engine)
    summary = {"files": 0, "inserted": 0, "skipped": 0, "errors": 0}
    for path in sorted(Path(folder).rglob("*.json")):
        with Session() as session:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for report in data if isinstance(data, list) else [data]:
                    inserted, skipped = insert_report(session, report)
                    summary["inserted"] += inserted
                    summary["skipped"] += skipped
                session.commit()
                summary["files"] += 1
            except Exception as error:  # one bad file must not stop the batch
                session.rollback()
                summary["errors"] += 1
                print(f"[error] {path.name}: {error}")
    return summary
