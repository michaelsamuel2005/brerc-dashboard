"""Small regressions for the standalone run-history table markup."""

from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2] / "run-dashboard" / "static" / "index.html"
)


def test_run_history_table_keeps_date_fallback_and_column_alignment():
    html = HTML_PATH.read_text(encoding="utf-8")
    row_template = html.split("tr.innerHTML = `", maxsplit=1)[1].split(
        "`;", maxsplit=1
    )[0]

    assert html.count("<th>") == 7
    assert row_template.count("<td") == 7
    assert "escapeHtml(run.load_no || run.date)" in html
    assert 'colspan="7"' in html
