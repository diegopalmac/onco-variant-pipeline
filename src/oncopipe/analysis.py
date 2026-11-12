"""Queries and figures on top of the SQLite database."""
import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

# Reports name the same cancer in several ways; analyses need one label.
CANCER_GROUPS = {
    "Colon Cancer": "Colorectal cancer",
    "Colon cancer (NOS)": "Colorectal cancer",
    "Colorectal Cancer": "Colorectal cancer",
    "Non-Small Cell Lung Cancer": "Lung cancer",
    "Non Small Cell Lung Cancer": "Lung cancer",
    "Lung Cancer": "Lung cancer",
    "Pancreatic Cancer": "Pancreatic cancer",
    "Pancreatic Adenocarcinoma": "Pancreatic cancer",
    "Breast Cancer": "Breast cancer",
    "Gastric Cancer": "Gastrointestinal cancer",
    "GIST Cancer": "Gastrointestinal cancer",
    "Prostate Cancer": "Prostate cancer",
    "Ovarian Cancer": "Ovarian cancer",
}

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"
SEQUENTIAL = LinearSegmentedColormap.from_list("blue", ["#eaf2fd", "#86b6ef", "#2a78d6", "#0d366b"])


def load_tables(db_path: str):
    with sqlite3.connect(db_path) as conn:
        patients = pd.read_sql_query("SELECT * FROM pacientes", conn)
        variants = pd.read_sql_query("SELECT * FROM variantes", conn)
    patients["cancer_group"] = patients["tipo_cancer"].map(CANCER_GROUPS).fillna(patients["tipo_cancer"])
    variants = variants.merge(patients[["paciente_id", "cancer_group"]], on="paciente_id")
    variants["mutacion"] = variants["gen"] + " " + variants["resultado_test"].str.split(" ").str[0]
    return patients, variants


def top_variants(variants: pd.DataFrame, tier: int, cancer_group: str = None, n: int = 10) -> pd.DataFrame:
    """Most frequent variants of a tier, counted in distinct patients."""
    subset = variants[variants["tier"] == tier]
    if cancer_group:
        subset = subset[subset["cancer_group"] == cancer_group]
    return (subset.groupby(["gen", "resultado_test"])["paciente_id"].nunique()
            .sort_values(ascending=False).head(n).rename("pacientes").reset_index())


def cooccurrence(variants: pd.DataFrame, cancer_group: str, tier: int = 3, n: int = 5) -> pd.DataFrame:
    """Patients carrying each pair among the top-n variants (diagonal = carriers)."""
    subset = variants[(variants["cancer_group"] == cancer_group) & (variants["tier"] == tier)]
    top = subset.groupby("mutacion")["paciente_id"].nunique().nlargest(n).index
    presence = pd.crosstab(subset["paciente_id"], subset["mutacion"])[list(top)].clip(upper=1)
    return presence.T.dot(presence)


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)


def _title(fig, title, subtitle):
    fig.text(0.02, 0.965, title, fontsize=12, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.905, subtitle, fontsize=9, color=MUTED, va="top")


def plot_cancer_types(patients: pd.DataFrame, path: str):
    counts = patients["cancer_group"].value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(7, 3.8), facecolor=SURFACE)
    bars = ax.barh(counts.index, counts.values, color=BLUE, height=0.6)
    ax.bar_label(bars, padding=4, color=INK, fontsize=9)
    _style(ax)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", labelcolor=INK)
    _title(fig, "Patients by cancer type", f"Synthetic cohort, n = {len(patients)}")
    fig.subplots_adjust(left=0.27, right=0.94, top=0.82, bottom=0.05)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_age_by_cancer(patients: pd.DataFrame, path: str):
    order = patients.groupby("cancer_group")["edad"].median().sort_values().index.tolist()
    fig, ax = plt.subplots(figsize=(7, 4.2), facecolor=SURFACE)
    for sex, color, offset in (("Female", ORANGE, 0.14), ("Male", BLUE, -0.14)):
        subset = patients[patients["sexo"] == sex]
        y = subset["cancer_group"].map(order.index) + offset
        ax.scatter(subset["edad"], y, s=22, color=color, alpha=0.75, linewidths=0.6,
                   edgecolors=SURFACE, label=sex)
    ax.set_yticks(range(len(order)), order)
    ax.set_xlabel("Age at report (years)", color=MUTED, fontsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _style(ax)
    ax.tick_params(axis="y", labelcolor=INK)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower right",
              bbox_to_anchor=(1.0, 1.0), ncol=2, handletextpad=0.2)
    _title(fig, "Age at report by cancer type and sex", "Synthetic cohort, one dot per patient")
    fig.subplots_adjust(left=0.27, right=0.96, top=0.80, bottom=0.13)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_cooccurrence(matrix: pd.DataFrame, cancer_group: str, path: str):
    fig, ax = plt.subplots(figsize=(6.4, 5.2), facecolor=SURFACE)
    values = matrix.values
    ax.imshow(values, cmap=SEQUENTIAL, vmin=0)
    labels = matrix.index.tolist()
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    threshold = values.max() * 0.55
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(values[i, j]), ha="center", va="center", fontsize=10,
                    color="white" if values[i, j] > threshold else INK)
    # white gaps between cells
    ax.set_xticks([x - 0.5 for x in range(1, len(labels))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(labels))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=INK, length=0, labelsize=9)
    _title(fig, f"Co-occurrence of the top 5 Tier III variants: {cancer_group.lower()}",
           "Patients carrying both variants; the diagonal counts carriers of each one. Synthetic data.")
    fig.subplots_adjust(left=0.24, right=0.97, top=0.84, bottom=0.2)
    fig.savefig(path, dpi=160)
    plt.close(fig)
