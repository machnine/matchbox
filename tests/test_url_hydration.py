"""URL URL-contract tests for shared-link state.

Clinical workflows share calculator state via query string, e.g.
    /?bg=O&specs=A1,B7&recip_hla=B44,DR7&donor_set=0

These tests do not execute browser JavaScript. They verify static and API
contracts that shared URLs rely on:

1. HTML contract -- the rendered index page exposes the DOM selectors that
   restoreFromQueryParams() in static/scripts.js depends on. A template
   rename that drops any of them would cause shared URLs to silently no-op.
2. JS contract -- static/scripts.js reads the exact four query-param names
   the /calc/ endpoint exposes. A rename on either side would break the
   shared-URL contract and must fail this test.
3. API contract -- /calc/ returns stable golden results for the URL shapes
   a hydrated UI produces, covering the clinical combinations.
"""

import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import api
from api.route import load_data

mock_donors = pd.read_csv("tests/mock_donors.csv")
mock_donors_dp = mock_donors.iloc[:10].copy()
mock_data = MagicMock()
mock_data.donors = (mock_donors, mock_donors_dp)
mock_data.antigens = {
    "A": ["A1", "A43"],
    "B": ["B7", "B8", "B12", "B42", "B46"],
    "DR": ["DR3", "DR9", "DR17"],
}
mock_data.mantigens = {"B": ["B7", "B8", "B12", "B42", "B46"], "DR": ["DR3", "DR9"]}
mock_data.mbands = {
    "A": {1: 35, 2: 30, 3: 25, 4: 20, 5: 15, 6: 10, 7: 5, 8: 2, 9: 1, 10: 0},
    "O": {1: 45, 2: 35, 3: 30, 4: 25, 5: 20, 6: 15, 7: 10, 8: 5, 9: 2, 10: 1},
}
mock_data.antigen_defaults = {"B42": "B7", "DR9": "DR4"}
mock_data.broad_split = {"broad_to_splits": {}, "split_to_broad": {}}

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    client = TestClient(api)


@pytest.fixture(autouse=True)
def _override_load_data():
    api.dependency_overrides[load_data] = lambda: mock_data
    yield
    api.dependency_overrides.clear()


def test_html_exposes_selectors_used_by_shared_url_contract():
    """restoreFromQueryParams() depends on these IDs and classes."""
    html = client.get("/").text
    for bg in ("A", "B", "O", "AB"):
        assert f'id="id_{bg}"' in html, f"blood group radio id_{bg} missing"
    assert "antigen-checkbox" in html
    assert html.count("recip-hla-select") == 4
    assert 'id="id_dp-toggle"' in html
    assert '>A</small>' in html
    assert 'id="id_B7"' in html  # representative antigen checkbox from mock


def test_scripts_js_declares_shared_url_contract():
    """scripts.js must read the four param names /calc/ exposes:
    bg, specs, recip_hla, donor_set. And the DOM selectors it relies on."""
    src = Path("static/scripts.js").read_text(encoding="utf-8")
    restore_block = src.split("const restoreFromQueryParams = () => {", 1)[1].split(
        "document.addEventListener", 1
    )[0]
    # query-param names must match api/route.py:calc() signature
    assert "params.get('bg')" in restore_block
    assert "params.getAll('specs')" in restore_block
    assert "params.getAll('recip_hla')" in restore_block
    assert "params.get('donor_set')" in restore_block
    # DOM selectors restoreFromQueryParams() depends on
    assert "id_dp-toggle" in restore_block
    assert "recip-hla-select" in restore_block
    assert "processInputAntigens(specs)" in restore_block


@pytest.mark.parametrize(
    "params,expected",
    [
        # default UI state after loading "/"
        ({"bg": "A"}, {"crf": 0, "available": 39}),
        # shared URL: bg + specs
        (
            {"bg": "B", "specs": "A43,B7,B8,DR17,DR3"},
            {"crf": pytest.approx(0.42857142857142855), "available": 4},
        ),
        # full clinical shape: bg + specs + recip_hla
        (
            {"bg": "O", "specs": "DR17,B42,B46,DR9", "recip_hla": "B7"},
            {
                "crf": pytest.approx(0.2857142857142857),
                "available": 35,
                "favourable": 35,
                "matchability": 2,
            },
        ),
    ],
    ids=["default", "bg+specs", "bg+specs+recip_hla"],
)
def test_calc_returns_expected_results_for_hydrated_url_shapes(params, expected):
    """/calc/ produces stable golden results for URLs the hydrated UI generates."""
    response = client.get("/calc/", params=params)
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    for key, val in expected.items():
        assert results[key] == val, f"{key}: got {results[key]}, expected {val}"


def test_calc_donor_set_changes_results_when_dp_pool_differs():
    """donor_set must affect /calc/ output when the configured donor pools differ."""
    params = {"bg": "A", "specs": "A1"}
    response_all = client.get("/calc/", params={**params, "donor_set": 0})
    response_dp = client.get("/calc/", params={**params, "donor_set": 1})

    assert response_all.status_code == 200, response_all.text
    assert response_dp.status_code == 200, response_dp.text

    body_all = response_all.json()
    body_dp = response_dp.json()

    assert body_all["total"] != body_dp["total"]
    assert body_all["results"] != body_dp["results"]
