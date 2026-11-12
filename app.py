"""Demo app: from a preliminary sequencing report to a queryable variant database.

    streamlit run app.py

Runs entirely on fictional data. The model call is simulated unless you
provide your own Gemini API key in the sidebar.
"""
import html
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from oncopipe import analysis, database, export, extract, samples, synthetic  # noqa: E402

BLUE, ORANGE = "#2a78d6", "#eb6834"
st.set_page_config(page_title="Onco variant pipeline", page_icon="🧬", layout="wide")


# ---------------------------------------------------------------- state
def init_state():
    if "db" in st.session_state:
        return
    data = ROOT / "data" / "synthetic"
    if not any(data.glob("*.json")):
        synthetic.write_reports(str(data))
    db = str(Path(tempfile.mkdtemp()) / "demo.db")
    database.load_folder(db, str(data))
    st.session_state.update(db=db, raw=None, clean=None, data=None, log=[], saved=[], source=None)


def reset_report():
    st.session_state.update(raw=None, clean=None, data=None, log=[])


@st.cache_data
def sample_index():
    cases = samples.sample_cases()
    folder = ROOT / "samples"
    if not any(folder.glob("*.pdf")):
        samples.write_samples(str(folder))
    return {
        c["report"]["paciente_id"]: {
            "path": str(folder / f"{c['report']['paciente_id']}_preliminary_report.pdf"),
            "label": f"{c['report']['paciente_id']} · {c['report']['tipo_cancer']} · "
                     f"{len(c['report']['variantes'])} variants",
        }
        for c in cases
    }


# ---------------------------------------------------------------- helpers
def highlighted(text: str, clean: bool) -> str:
    """Report text as HTML, marking what de-identification removes or rewrites."""
    rows = []
    for line in text.splitlines()[:16]:
        safe = html.escape(line)
        if not clean and (extract.NAME_LINE.match(line + "\n") or extract.BIRTH_LINE.match(line)
                          or extract.NATIONAL_ID.search(line)):
            safe = f"<span class='pii'>{safe}</span>"
        elif clean and (line.startswith("Age: ") or "[ID]" in line):
            safe = f"<span class='safe'>{safe}</span>"
        rows.append(safe)
    return "<div class='report'>" + "<br>".join(rows) + "<br>…</div>"


def stepper(current: int):
    names = ["Read the PDF", "Remove identifiers", "Extract with the LLM", "Review", "Save and export"]
    cells = []
    for i, name in enumerate(names):
        state = "done" if i < current else "now" if i == current else "todo"
        mark = "✓" if i < current else str(i + 1)
        cells.append(f"<div class='step {state}'><span class='dot'>{mark}</span>{name}</div>")
    st.markdown("<div class='steps'>" + "".join(cells) + "</div>", unsafe_allow_html=True)


st.markdown("""
<style>
.steps{display:flex;gap:8px;margin:4px 0 20px 0;flex-wrap:wrap}
.step{flex:1;min-width:150px;padding:10px 12px;border-radius:8px;border:1px solid rgba(128,128,128,.35);
      font-size:14px;opacity:.55}
.step.now{border:2px solid #2a78d6;background:rgba(42,120,214,.10);opacity:1;font-weight:600}
.step.done{opacity:1}
.dot{display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;border-radius:50%;
     margin-right:8px;font-size:12px;border:1px solid rgba(128,128,128,.6)}
.step.done .dot{background:#2a78d6;color:#fff;border-color:#2a78d6}
.report{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.6;padding:12px 14px;
        border-radius:8px;border:1px solid rgba(128,128,128,.35);min-height:300px;overflow-x:auto;white-space:nowrap}
.pii{background:rgba(208,59,59,.18);text-decoration:line-through;padding:1px 3px;border-radius:3px}
.safe{background:rgba(12,163,12,.18);padding:1px 3px;border-radius:3px}
</style>""", unsafe_allow_html=True)

init_state()
S = st.session_state

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Model")
    mode = st.radio("Extraction", ["Simulated (no key needed)", "Gemini with my own key"],
                    label_visibility="collapsed")
    live = mode.startswith("Gemini")
    api_key = st.text_input("Gemini API key", type="password",
                            help="Used only for this session. Never stored.") if live else None
    st.caption("In simulated mode the model call is replaced by a stand-in that knows the sample "
               "reports. PDF reading, de-identification, truncation handling, validation and the "
               "database all run for real.")
    st.divider()
    st.caption("All data here is fictional. Do not upload real patient reports to a public demo.")

st.title("From sequencing report to variant database")
st.caption("Demo of my thesis project at a clinical oncology genomics lab · synthetic data only")

tab_process, tab_db, tab_about = st.tabs(["Process a report", "Explore the database", "How it works"])

# ---------------------------------------------------------------- process
with tab_process:
    current = 0 if S.raw is None else 2 if S.data is None else 3
    if S.data is not None and S.data.get("paciente_id") in S.saved:
        current = 5
    stepper(current)

    index = sample_index()
    left, right = st.columns([2, 1])
    with left:
        choice = st.selectbox("Sample preliminary report", list(index), format_func=lambda k: index[k]["label"],
                              on_change=reset_report)
    with right:
        upload = st.file_uploader("…or your own PDF", type="pdf", on_change=reset_report,
                                  disabled=not live, help="Enabled with your own Gemini key.")
    source = upload if (live and upload) else index[choice]["path"]

    col_a, col_b = st.columns([1, 3])
    if col_a.button("1 · Read and de-identify", type="primary", width="stretch"):
        reset_report()
        with st.spinner("Reading the PDF…"):
            S.raw = extract.extract_text_from_pdf(source)
            S.clean = extract.deidentify(S.raw, today=date(*samples.DEMO_TODAY))
            S.source = getattr(source, "name", Path(str(source)).name)
        st.rerun()
    with open(index[choice]["path"], "rb") as handle:
        col_b.download_button("Download this sample PDF", handle.read(), Path(index[choice]["path"]).name,
                              mime="application/pdf")

    if S.raw is not None:
        st.subheader("What leaves the machine")
        before, after = st.columns(2)
        before.markdown("**Extracted from the PDF**")
        before.markdown(highlighted(S.raw, clean=False), unsafe_allow_html=True)
        after.markdown("**Sent to the model**")
        after.markdown(highlighted(S.clean, clean=True), unsafe_allow_html=True)
        st.caption(f"{len(S.raw):,} characters read from {S.source}. Name lines are dropped, the birth "
                   "date becomes an age computed locally, and ID numbers are masked.")

        if st.button("2 · Extract with the LLM", type="primary", disabled=live and not api_key):
            log = []
            try:
                backend = extract.gemini_generate(api_key=api_key) if live else samples.simulated_generate
            except Exception as error:
                st.error(f"Could not start the model: {error}")
                st.stop()

            with st.status("Extracting…", expanded=True) as status:
                def generate(prompt):
                    call = len(log) + 1
                    kind = "Asking for the full JSON" if call == 1 else "Asking the model to continue where it stopped"
                    st.write(f"**Call {call}.** {kind} ({len(prompt):,} characters sent).")
                    if not live:
                        time.sleep(0.9)
                    answer = backend(prompt)
                    log.append(len(answer))
                    st.write(f"Received {len(answer):,} characters.")
                    return answer

                try:
                    data = extract.extract_report(S.clean, generate)
                except Exception as error:
                    status.update(label="Extraction failed", state="error")
                    st.error(str(error))
                    st.stop()
                if data is None:
                    status.update(label="No valid JSON after retry and repair", state="error")
                    st.stop()
                if len(log) > 1:
                    st.write("The first answer was cut off before the JSON closed. "
                             "Both parts were joined and now parse as one valid object.")
                status.update(label=f"Valid JSON · {len(data.get('variantes', []))} variants · "
                                    f"{len(log)} model call{'s' if len(log) > 1 else ''}", state="complete")
            S.data, S.log = data, log
            st.rerun()
        if live and not api_key:
            st.caption("Enter your Gemini API key in the sidebar to run the live extraction.")

    if S.data is not None:
        st.subheader("Review before saving")
        st.caption(f"Valid JSON after {len(S.log)} model call{'s' if len(S.log) > 1 else ''}. "
                   "Nothing is stored until a person confirms it. Cells are editable.")
        d = S.data
        m = st.columns(6)
        for column, label, key in zip(m, ["Sample", "Age", "Sex", "Diagnosis", "MSI", "bTMB"],
                                      ["paciente_id", "edad", "sexo", "tipo_cancer",
                                       "Blood_Microsatellite_Status", "Blood_Tumor_Mutation_Burden"]):
            column.markdown(f"<small>{label}</small><br><b>{html.escape(str(d.get(key, '')))}</b>",
                            unsafe_allow_html=True)
        st.write("")
        table = pd.DataFrame(d.get("variantes", [])).reindex(columns=export.VARIANT_FIELDS).fillna("")
        edited = st.data_editor(table, width="stretch", hide_index=True, num_rows="dynamic",
                                height=min(420, 38 * (len(table) + 1) + 4), key=f"editor_{d.get('paciente_id')}")
        final = dict(d, variantes=edited.fillna("").to_dict("records"))

        save, excel, raw_json = st.columns([1, 1, 1])
        if save.button("3 · Confirm and save to the database", type="primary", width="stretch"):
            engine = database.make_engine(S.db)
            with sessionmaker(bind=engine)() as session:
                inserted, skipped = database.insert_report(session, final)
                session.commit()
            S.saved.append(final["paciente_id"])
            st.toast(f"Saved {inserted} new variants ({skipped} already stored or wild type).")
            st.rerun()
        excel.download_button("Excel for the final report", export.report_excel(final),
                              f"{final.get('paciente_id', 'report')}.xlsx", width="stretch")
        raw_json.download_button("Standard JSON", json.dumps(final, indent=2, ensure_ascii=False),
                                 f"{final.get('paciente_id', 'report')}.json", width="stretch")
        if final.get("paciente_id") in S.saved:
            st.success(f"{final['paciente_id']} is in the database. Open **Explore the database** "
                       "to see it counted. Saving again adds nothing: duplicates are skipped.")

# ---------------------------------------------------------------- database
with tab_db:
    patients, variants = analysis.load_tables(S.db)
    k = st.columns(4)
    k[0].metric("Patients", len(patients))
    k[1].metric("Variants", f"{len(variants):,}")
    k[2].metric("Cancer groups", patients["cancer_group"].nunique())
    k[3].metric("Added in this session", len(set(S.saved)))

    groups = patients["cancer_group"].value_counts()
    f1, f2 = st.columns([2, 1])
    group = f1.selectbox("Cancer type", ["All"] + groups.index.tolist())
    tier = f2.radio("Tier", [1, 2, 3], index=2, horizontal=True,
                    format_func=lambda t: {1: "I", 2: "II", 3: "III (uncertain)"}[t])
    scope = None if group == "All" else group

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Patients by cancer type**")
        counts = groups.rename_axis("cancer").reset_index(name="patients")
        st.altair_chart(
            alt.Chart(counts).mark_bar(color=BLUE, cornerRadiusEnd=4, height=18).encode(
                x=alt.X("patients:Q", title="Patients", axis=alt.Axis(grid=False, tickMinStep=1)),
                y=alt.Y("cancer:N", sort="-x", title=None),
                opacity=alt.condition(alt.datum.cancer == (scope or ""), alt.value(1.0),
                                      alt.value(1.0 if scope is None else 0.35)),
                tooltip=["cancer", "patients"],
            ).properties(height=300), width="stretch")
    with c2:
        st.markdown(f"**Most frequent Tier {'I' * tier} variants** · {group.lower()}")
        top = analysis.top_variants(variants, tier=tier, cancer_group=scope, n=10)
        if top.empty:
            st.info("No variants for this selection.")
        else:
            top["variant"] = top["gen"] + " " + top["resultado_test"].str.split(" ").str[0]
            st.altair_chart(
                alt.Chart(top).mark_bar(color=BLUE, cornerRadiusEnd=4, height=18).encode(
                    x=alt.X("pacientes:Q", title="Patients carrying it", axis=alt.Axis(grid=False, tickMinStep=1)),
                    y=alt.Y("variant:N", sort="-x", title=None),
                    tooltip=[alt.Tooltip("gen", title="Gene"), alt.Tooltip("resultado_test", title="Result"),
                             alt.Tooltip("pacientes", title="Patients")],
                ).properties(height=300), width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        target = scope or groups.index[0]
        st.markdown(f"**Co-occurrence of the top 5 Tier {'I' * tier} variants** · {target.lower()}")
        matrix = analysis.cooccurrence(variants, target, tier=tier)
        if matrix.empty:
            st.info("Not enough variants for this selection.")
        else:
            order = matrix.index.tolist()
            long = matrix.rename_axis("a").reset_index().melt("a", var_name="b", value_name="patients")
            base = alt.Chart(long).encode(
                x=alt.X("b:N", sort=order, title=None, axis=alt.Axis(labelAngle=-30, labelOverlap=False, labelLimit=140)),
                y=alt.Y("a:N", sort=order, title=None, axis=alt.Axis(labelLimit=140)))
            heat = base.mark_rect(stroke="white", strokeWidth=2).encode(
                color=alt.Color("patients:Q", scale=alt.Scale(range=["#cde2fb", "#2a78d6", "#0d366b"]),
                                legend=None),
                tooltip=[alt.Tooltip("a", title="Variant"), alt.Tooltip("b", title="With"),
                         alt.Tooltip("patients", title="Patients with both")])
            labels = base.mark_text(fontSize=13).encode(
                text="patients:Q",
                color=alt.condition(alt.datum.patients > long["patients"].max() * 0.55,
                                    alt.value("white"), alt.value("#0b0b0b")))
            st.altair_chart((heat + labels).properties(height=360), width="stretch")
            st.caption("Patients carrying both variants. The diagonal counts carriers of each one.")
    with c4:
        st.markdown("**Age at report by sex**")
        people = patients if scope is None else patients[patients["cancer_group"] == scope]
        st.altair_chart(
            alt.Chart(people.dropna(subset=["edad"])).mark_bar(opacity=0.85).encode(
                x=alt.X("edad:Q", bin=alt.Bin(step=5), title="Age (years)"),
                y=alt.Y("count():Q", title="Patients", axis=alt.Axis(tickMinStep=1)),
                color=alt.Color("sexo:N", title=None, scale=alt.Scale(domain=["Female", "Male"],
                                                                        range=[ORANGE, BLUE]),
                                legend=alt.Legend(orient="top")),
                xOffset="sexo:N",
                tooltip=[alt.Tooltip("sexo", title="Sex"), alt.Tooltip("count()", title="Patients")],
            ).properties(height=320), width="stretch")

    st.markdown("**Find patients by gene**")
    gene = st.text_input("Gene symbol", placeholder="KRAS, TP53, SYNG04…", label_visibility="collapsed")
    if gene:
        hits = variants[variants["gen"].str.upper() == gene.strip().upper()]
        if scope:
            hits = hits[hits["cancer_group"] == scope]
        st.caption(f"{hits['paciente_id'].nunique()} patients, {len(hits)} variants")
        st.dataframe(hits[["paciente_id", "cancer_group", "tier", "gen", "resultado_test", "abundancia",
                           "terapias_sensibles"]], width="stretch", hide_index=True)

# ---------------------------------------------------------------- about
with tab_about:
    st.markdown("""
**The problem.** A clinical lab received a 20 to 60 page preliminary report for every sequenced
sample and built each final report by hand: 1 to 2 hours per report, 3 to 5 reports a week,
in a team of three. Results were stored nowhere.

**What this does.**

1. Reads the PDF with `pdfplumber`.
2. Removes direct identifiers before any text leaves the machine.
3. Asks an LLM (Gemini 2.0 Flash in the lab) for a fixed JSON schema. Long reports overflow the
   model's output, so a truncated answer triggers a continuation call; if that fails, every
   complete variant is kept.
4. Shows the result to a person, who confirms it.
5. Saves it to SQLite without duplicates and exports the Excel used to build the final report.

**Results in the lab.** About 30 minutes saved per report (25% to 50%), an estimated 3.25 staff
hours freed per week at zero running cost, and the lab's first database of its own results:
153 patients and 3,811 variants.

**What is simulated here.** Only the model call, unless you add your own key. Every patient,
name, ID and variant frequency in this app is fictional.
""")
