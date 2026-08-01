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

    match_count_guard = "if (data.donor_set === 0 && data.results.match_counts)"
    assert render.index("clearMatchCounts()") < render.index(match_count_guard)


def test_dp_typed_mode_cannot_show_extrapolated_match_counts():
    matches_link = HTML.split('data-bs-target="#offcanvasMatchCount"', 1)[1].split(">", 1)[0]

    assert "toggle-hide" in matches_link
    assert "data.donor_set === 0 && data.results.match_counts" in SCRIPT


def test_dp_typed_mode_does_not_render_raw_matchability_metrics():
    render = SCRIPT.split("const renderCalculation = (data) => {", 1)[1].split("const calculate", 1)[0]

    assert 'data.donor_set === 1 ? "—" : data.results.matchability' in render
    assert 'data.donor_set === 1 ? "—" : data.results.favourable' in render


def test_profile_contract_failure_disables_storing_and_surfaces_an_error():
    add_handler = SCRIPT.split("addProfileButton.addEventListener('click'", 1)[1].split(
        "// Export stored data", 1
    )[0]

    assert "try {" in add_handler
    assert "MatchboxProfileExport.buildProfileRecord" in add_handler
    assert "setCalculationFailed()" in add_handler


def test_pending_state_preserves_the_last_rendered_values_without_making_them_saveable():
    pending = SCRIPT.split("const setCalculationPending = () => {", 1)[1].split("};", 1)[0]

    assert "currentApiData = null" in pending
    assert "setAddProfileEnabled(false)" in pending
    assert 'calculationMetrics.setAttribute("aria-busy", "true")' in pending
    assert "textContent" not in pending
    assert "clearMatchCounts()" not in pending
    assert "clearDonorTotalTooltip()" not in pending


def test_failed_state_clears_the_previous_donor_total_tooltip():
    failed = SCRIPT.split("const setCalculationFailed = () => {", 1)[1].split("};", 1)[0]

    assert "clearDonorTotalTooltip()" in failed
    assert 'bootstrap.Tooltip.getInstance(dpToggle)?.dispose()' in SCRIPT
