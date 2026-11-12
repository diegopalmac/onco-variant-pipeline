"""Drive the Streamlit app end to end (simulated model)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def click(at, label):
    next(b for b in at.button if b.label.startswith(label)).click().run(timeout=60)


def test_long_report_goes_from_pdf_to_database():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    before = int(at.metric[0].value)

    at.selectbox[0].select("SYN-9004").run()
    click(at, "1 ·")
    assert "Carlos Prueba" in at.session_state.raw
    assert "Carlos Prueba" not in at.session_state.clean
    assert "1949" not in at.session_state.clean

    click(at, "2 ·")
    assert len(at.session_state.log) == 2          # truncated, then completed
    assert len(at.session_state.data["variantes"]) == 59

    click(at, "3 ·")
    assert not at.exception
    assert int(at.metric[0].value) == before + 1
