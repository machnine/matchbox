"""Static contracts for profile export values."""

from pathlib import Path

SCRIPT = Path("static/scripts.js").read_text(encoding="utf-8")


def test_numeric_zero_values_are_not_replaced_with_blanks():
    export_mapping = SCRIPT.split("const tsvData = storedData.map(row => ({", 1)[1].split("}));", 1)[0]

    for field in ("crf", "matchability", "favourable", "available"):
        assert f"row.{field} ?? ' '" in export_mapping
        assert f"row.{field} || ' '" not in export_mapping
