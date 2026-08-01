"""Static contracts for stable calculator metric layout."""

from pathlib import Path

STYLE = Path("static/style.css").read_text(encoding="utf-8")


def test_metric_values_reserve_space_and_use_tabular_numbers():
    metric_span = STYLE.split(".metrics span {", 1)[1].split("}", 1)[0]

    assert "display: inline-block" in metric_span
    assert "font-variant-numeric: tabular-nums" in metric_span
    assert "text-align: end" in metric_span
    assert "white-space: nowrap" in metric_span

    expected_widths = {
        "crf-text": "8ch",
        "mp-text": "3ch",
        "fm-text": "5ch",
        "avd-text": "5ch",
    }
    for element_id, width in expected_widths.items():
        rule = STYLE.split(f"#{element_id} {{", 1)[1].split("}", 1)[0]
        assert f"min-width: {width}" in rule


def test_small_screens_recover_space_with_compact_metric_padding():
    mobile = STYLE.split("@media (max-width: 576px)", 1)[1]

    assert ".metrics > div.metric" in mobile
    assert "padding-right: 6px" in mobile
    assert "padding-left: 6px" in mobile
