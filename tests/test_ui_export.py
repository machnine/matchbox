"""Static integration contracts for browser profile export."""

from pathlib import Path

PROFILE_EXPORT = Path("static/profile-export.js").read_text(encoding="utf-8")
SCRIPT = Path("static/scripts.js").read_text(encoding="utf-8")
HTML = Path("web/index.html").read_text(encoding="utf-8")


def test_profile_export_helper_loads_before_the_main_script():
    assert HTML.index("profile-export.js") < HTML.index("scripts.js")
    assert "MatchboxProfileExport.buildProfileRecord" in SCRIPT
    assert "MatchboxProfileExport.profilesToTsv" in SCRIPT


def test_numeric_zero_values_use_nullish_tsv_fallbacks():
    for field in ("crf", "matchability", "favourable", "available"):
        assert f'row.{field} ?? ""' in PROFILE_EXPORT
        assert f'row.{field} || ""' not in PROFILE_EXPORT


def test_dp_typed_profiles_explicitly_null_matchability_fields():
    assert "matchability: isDpTypedSubset ? null : data.results.matchability" in PROFILE_EXPORT
    assert "favourable: isDpTypedSubset ? null : data.results.favourable" in PROFILE_EXPORT
    assert '"not_applicable_dp_typed_subset"' in PROFILE_EXPORT
