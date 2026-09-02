"""Small regressions for the standalone run-history table markup."""

from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "run-dashboard" / "static" / "index.html"


def test_run_history_table_matches_atomic_loader_contract_and_column_alignment():
    html = HTML_PATH.read_text(encoding="utf-8")
    row_template = html.split("tr.innerHTML = `", maxsplit=1)[1].split("`;", maxsplit=1)[0]

    assert html.count("<th>") == 8
    assert row_template.count("<td") == 8
    assert "run.source_rows_seen" in html
    assert "run.candidate_rows" in html
    assert "run.rows_withheld" in html
    assert "run.failure_code" in html
    assert "run.inserts" not in html
    assert 'colspan="8"' in html


def test_run_history_table_rejects_non_successful_http_responses():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'if (!response.ok) throw new Error("Run history request failed")' in html
    assert "if (!Array.isArray(runs))" in html
