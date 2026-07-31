"""Static contracts for calculator request-state integrity."""

from pathlib import Path

SCRIPT = Path("static/scripts.js").read_text(encoding="utf-8")
HTML = Path("web/index.html").read_text(encoding="utf-8")


def test_profile_add_starts_disabled_and_metrics_are_live():
    add_button = HTML.split('id="btn-log-data"', 1)[1].split(">", 1)[0]

    assert "disabled" in add_button
    assert 'aria-disabled="true"' in add_button
    assert 'aria-live="polite"' in HTML


def test_each_calculation_invalidates_previous_data_before_fetch():
    calculate = SCRIPT.split("const calculate = (antigenList) => {", 1)[1].split("// Toggle all antigens", 1)[0]

    assert "const requestGeneration = ++calculationGeneration" in calculate
    assert calculate.index("setCalculationPending()") < calculate.index("fetch(")
    assert "currentApiData = null" in SCRIPT.split("const setCalculationPending = () => {", 1)[1].split("};", 1)[0]


def test_stale_successes_and_failures_cannot_replace_current_state():
    calculate = SCRIPT.split("const calculate = (antigenList) => {", 1)[1].split("// Toggle all antigens", 1)[0]

    guards = [
        index
        for index in range(len(calculate))
        if calculate.startswith("if (requestGeneration !== calculationGeneration) return;", index)
    ]

    assert len(guards) == 2
    assert guards[0] < calculate.index("renderCalculation(data)") < calculate.index("currentApiData = data")
    assert guards[1] < calculate.index("setCalculationFailed()")


def test_each_calculation_cancels_the_previous_request():
    calculate = SCRIPT.split("const calculate = (antigenList) => {", 1)[1].split("// Toggle all antigens", 1)[0]

    assert "calculationController?.abort()" in calculate
    assert "const requestController = new AbortController()" in calculate
    assert "signal: requestController.signal" in calculate
    assert 'error.name === "AbortError"' in calculate


def test_match_counts_are_cleared_when_response_has_none():
    render = SCRIPT.split("const renderCalculation = (data) => {", 1)[1].split("const calculate", 1)[0]

    assert render.index("clearMatchCounts()") < render.index("if (data.results.match_counts)")


def test_pending_state_clears_the_previous_donor_total_tooltip():
    pending = SCRIPT.split("const setCalculationPending = () => {", 1)[1].split("};", 1)[0]

    assert "clearDonorTotalTooltip()" in pending
    assert 'bootstrap.Tooltip.getInstance(dpToggle)?.dispose()' in SCRIPT
