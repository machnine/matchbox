"""Static contracts for the offer-assessment interpretation layer."""

from pathlib import Path

HTML = Path("web/offer.html").read_text(encoding="utf-8")
SCRIPT = Path("static/offer.js").read_text(encoding="utf-8")
STYLE = Path("static/offer.css").read_text(encoding="utf-8")


def test_primary_visual_names_ranking_direction_and_ties():
    assert "Lower burden" in HTML
    assert "potentially easier" in HTML
    assert "Higher burden" in HTML
    assert "potentially harder" in HTML
    assert 'id="summary-equal"' in HTML
    assert "empirical_percentile_range" in SCRIPT


def test_compatible_offer_is_presented_as_not_rankable():
    assert "compatible_no_dsa" in SCRIPT
    assert "Compatible at threshold" in SCRIPT
    assert "Burden ranking is not applicable" in SCRIPT


def test_current_and_peak_use_basis_specific_summaries():
    assert "result.basis_summaries.current" in SCRIPT
    assert "result.basis_summaries.peak" in SCRIPT
    assert "Compare each basis only with its own denominator" not in SCRIPT  # API note, not invented client-side


def test_offer_inputs_include_donor_blood_group_and_staleness_guards():
    assert 'id="donor-bg"' in HTML
    assert '<option value="O" selected>O</option>' in HTML
    assert "assessmentGeneration" in SCRIPT
    assert "parseGeneration" in SCRIPT
    assert "state.parseGeneration += 1" in SCRIPT
    assert "donor_bg: $('donor-bg').value" in SCRIPT


def test_zero_threshold_is_not_replaced_by_the_default():
    assert "Number.isFinite(threshold) ? threshold : 2000" in SCRIPT
    assert "parseFloat($('threshold').value) || 2000" not in SCRIPT


def test_visualisation_has_distinct_lower_tie_and_higher_segments():
    for class_name in ("rank-segment-lower", "rank-segment-equal", "rank-segment-higher"):
        assert f".{class_name}" in STYLE
    assert "['lower', placement.n_lower]" in SCRIPT
    assert "['equal', placement.n_equal]" in SCRIPT
    assert "['higher', placement.n_higher]" in SCRIPT


def test_server_messages_are_inserted_as_text_not_markup():
    assert "error.textContent = message" in SCRIPT
    assert "struck.textContent = row.raw_spec" in SCRIPT
    assert "error.detail}</div>" not in SCRIPT
