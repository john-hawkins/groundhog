"""Best-result selection when several metrics share a results table (issue #12).

Most of these pass ``rows`` directly, which short-circuits the filesystem, so
they exercise the comparison logic on its own. The last test goes through
``parse_results()`` to confirm the real path behaves the same.
"""

from __future__ import annotations

from groundhog.lib import fs


def _row(metric: str, value: str, experiment: str = "run") -> dict:
    """One parsed RESULTS.md row, shaped as ``parse_results()`` returns them."""
    return {
        "experiment": experiment,
        "date": "2026-01-01",
        "metric": metric,
        "value": value,
        "notes": "",
    }


# --- the best result must come from the optimisation metric alone -----------

def test_a_second_metric_does_not_win_on_scale():
    """An RMSE of 12.5 is a larger number than an AUC of 0.91, but it is not a
    better AUC."""
    rows = [_row("AUC", "0.91"), _row("RMSE", "12.5")]
    assert fs.top_result("p", "AUC", rows) == "0.91 (AUC)"


def test_the_optimisation_metric_decides_the_direction_too():
    """Optimising RMSE must not report an AUC value just because it is smaller."""
    rows = [_row("AUC", "0.91"), _row("RMSE", "12.5")]
    assert fs.top_result("p", "RMSE", rows) == "12.5 (RMSE)"


def test_rows_match_the_metric_whatever_their_casing():
    """The agent writes the metric cell freely, so casing is not guaranteed."""
    rows = [_row("auc", "0.80"), _row("AUC", "0.85")]
    assert fs.top_result("p", "AUC", rows) == "0.85 (AUC)"


def test_lower_is_better_survives_the_agent_s_casing():
    """Without metadata the row's own spelling is used, and 'rmse' has to be
    recognised as the same metric as 'RMSE' or the comparison inverts."""
    rows = [_row("rmse", "99"), _row("rmse", "5")]
    assert fs.top_result("p", None, rows) == "5 (rmse)"


# --- nothing to report is said, not implied --------------------------------

def test_no_rows_for_the_chosen_metric_says_so():
    """Distinct from having no results at all: experiments have run, none of
    them reported the metric this project is optimising for."""
    rows = [_row("RMSE", "12.5"), _row("RMSE", "11.0")]
    assert fs.top_result("p", "AUC", rows) == "— (no AUC yet)"


def test_no_results_at_all_is_still_a_bare_dash():
    assert fs.top_result("p", "AUC", []) == "—"


# --- behaviour that must not change ----------------------------------------

def test_higher_is_better_for_a_single_metric():
    rows = [_row("AUC", "0.71"), _row("AUC", "0.86")]
    assert fs.top_result("p", "AUC", rows) == "0.86 (AUC)"


def test_lower_is_better_for_a_single_metric():
    rows = [_row("RMSE", "91000"), _row("RMSE", "64000")]
    assert fs.top_result("p", "RMSE", rows) == "64000 (RMSE)"


def test_an_empty_metric_cell_inherits_the_configured_metric():
    rows = [_row("", "0.71"), _row("", "0.86")]
    assert fs.top_result("p", "AUC", rows) == "0.86 (AUC)"


def test_without_metadata_the_first_row_names_the_metric():
    """Projects that predate metadata.json have no optimisation target."""
    rows = [_row("AUC", "0.71"), _row("AUC", "0.86")]
    assert fs.top_result("p", None, rows) == "0.86 (AUC)"


def test_an_unparseable_value_is_skipped_rather_than_raising():
    rows = [_row("AUC", "n/a"), _row("AUC", "0.86")]
    assert fs.top_result("p", "AUC", rows) == "0.86 (AUC)"


# --- and the same through the file it will actually read -------------------

def test_reads_the_metric_column_from_results_md(project):
    fs.results_path(project).write_text(
        fs.RESULTS_HEADER
        + "| logreg | 2026-01-01 | AUC | 0.83 | baseline |\n"
        + "| ridge | 2026-01-02 | RMSE | 12.5 | different metric |\n"
    )
    assert fs.top_result(project, "AUC") == "0.83 (AUC)"
