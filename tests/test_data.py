"""Tests for DataLoader class"""

import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from pydantic import ValidationError

from api.data import DataLoader, DataLoadError, DataProvenance

TEST_DATABASE_SHA256 = "c" * 64


def make_data_loader(**kwargs):
    """Construct a loader for method tests without requiring a real database file."""
    with patch.object(DataLoader, "_file_sha256", return_value=TEST_DATABASE_SHA256):
        return DataLoader(**kwargs)


def setup_mock_db(mock_df):
    """
    Setup and return a mock database connection and associated mock objects.

    Args:
        mock_df (pd.DataFrame): The mock DataFrame to return from database queries.

    Returns:
        tuple: (mock_connect, mock_conn) where mock_connect is the mock for sqlite3.connect
               and mock_conn is the mock connection object.
    """
    mock_conn = MagicMock()
    mock_connect = MagicMock(return_value=mock_conn)

    # Configure mock to simulate fetchall and column descriptions
    mock_conn.execute.return_value.fetchall.return_value = mock_df.values.tolist()
    mock_conn.execute.return_value.description = [(col,) for col in mock_df.columns]

    return mock_connect, mock_conn


# Mock database connection and query execution
@patch("sqlite3.connect")
def test_antigens_method(mock_connect):
    mock_df = pd.DataFrame({"A1": [], "B44": [], "CW3": [], "DR1": [], "DPB11": [], "BW4": [], "DQ5": [], "A19_S": []})
    mock_connect, mock_conn = setup_mock_db(mock_df)
    data_loader = make_data_loader(db_path="mock_db.db")
    data_loader.donors = (mock_df, mock_df)
    antigens = data_loader.antigens()
    assert antigens == {
        "A": ["A1"],
        "B": ["B44"],
        "CW": ["CW3"],
        "DR": ["DR1"],
        "DPB": ["DPB11"],
        "BW": ["BW4"],
        "DQ": ["DQ5"],
    }
    assert "A19_S" not in antigens["A"]


@patch("sqlite3.connect")
def test_matchability_bands_method(mock_connect):
    mock_df = pd.DataFrame(
        {
            "bg": ["A", "B", "O", "AB"],
            "1": [100, 200, 300, 10],
            "2": [90, 190, 290, 8],
            "ver": [4, 4, 4, 4],
            "sizes": ["1", "2", "3", "4"],
        }
    )
    mock_connect, mock_conn = setup_mock_db(mock_df)
    pd_read_sql_query_original = pd.read_sql_query

    def mock_read_sql_query(sql, con, *args, **kwargs):
        # Assuming sql contains the correct query, return the mock DataFrame directly
        if "matchability_bands" in sql:
            return mock_df
        return pd_read_sql_query_original(sql, con, *args, **kwargs)

    with patch("pandas.read_sql_query", side_effect=mock_read_sql_query):
        data_loader = make_data_loader(db_path="mock_db.db")
        bands_dict = data_loader.matchability_bands()

    # Assertions to ensure matchability_bands method returns expected data structure and content
    assert isinstance(bands_dict, dict)
    assert set(bands_dict.keys()) == {"A", "B", "O", "AB"}
    assert bands_dict["A"] == {1: 100, 2: 90}
    assert bands_dict["B"] == {1: 200, 2: 190}
    assert bands_dict["O"] == {1: 300, 2: 290}
    assert bands_dict["AB"] == {1: 10, 2: 8}


@patch("pandas.read_sql_query")
@patch("sqlite3.connect")
def test_matchability_antigens_mothod(mock_connect, mock_read_sql_query):
    mock_df = pd.DataFrame(
        {"locus": ["B", "B", "B", "DR", "DR", "DR"], "antigen": ["B44", "B27", "B5", "DR1", "DR15", "DR9"]}
    )

    mock_connect, mock_conn = setup_mock_db(mock_df)
    mock_read_sql_query.return_value = mock_df

    data_loader = make_data_loader(db_path="mock_db.db")
    result = data_loader.matchability_antigens()

    # Assertions
    assert set(result["B"]) == set(["B44", "B27", "B5"])
    assert set(result["DR"]) == set(["DR9", "DR15", "DR1"])


@patch("pandas.read_sql_query")
@patch("sqlite3.connect")
def test_antigen_defaults(mock_connect, mock_read_sql_query):
    mock_df = pd.DataFrame({"rare": ["A36", "B42", "DR9"], "default": ["A1", "B7", "DR4"], "locus": ["A", "B", "DR"]})

    mock_connect, mock_conn = setup_mock_db(mock_df)

    mock_connect.return_value = mock_conn
    mock_read_sql_query.return_value = mock_df

    data_loader = make_data_loader(db_path="mock_db.db")
    result = data_loader.antigen_defaults()

    # Assertions
    assert result == {"A36": "A1", "B42": "B7", "DR9": "DR4"}


def test_data_provenance_fingerprints_the_derived_database():
    database = Path("fixtures/test-donors.db")
    database_bytes = b"derived donor database fixture"
    expected_sha256 = hashlib.sha256(database_bytes).hexdigest()

    with (
        patch.object(Path, "is_file", return_value=True),
        patch.object(Path, "open", return_value=BytesIO(database_bytes)),
        patch("sqlite3.connect"),
        patch.object(DataLoader, "_load_donors", return_value=(pd.DataFrame(), pd.DataFrame())),
    ):
        loader = DataLoader(
            db_path=str(database),
            table_name="test_donors_v7",
            matchability_ver=7,
            upstream_source_file="source-release.xlsb",
            upstream_source_file_size_signature=123_456,
        )

    assert loader.provenance.model_dump() == {
        "upstream_source_file": "source-release.xlsb",
        "upstream_source_file_size_signature": 123_456,
        "donor_database": "test-donors.db",
        "donor_database_sha256": expected_sha256,
        "donor_table": "test_donors_v7",
        "matchability_band_version": 7,
        "data_release": None,
    }


def test_custom_database_does_not_inherit_default_upstream_lineage():
    with (
        patch.object(DataLoader, "_file_sha256", return_value="d" * 64),
        patch("sqlite3.connect"),
        patch.object(DataLoader, "_load_donors", return_value=(pd.DataFrame(), pd.DataFrame())),
    ):
        loader = DataLoader(db_path="custom.db")

    assert loader.provenance.upstream_source_file is None
    assert loader.provenance.upstream_source_file_size_signature is None


def test_verified_release_cannot_be_attached_to_a_different_artifact():
    with pytest.raises(ValidationError, match="verified calculator artifact"):
        DataProvenance(
            upstream_source_file="hla-mm-and-crf_2024.xlsb",
            upstream_source_file_size_signature=24_099_579,
            donor_database="custom.db",
            donor_database_sha256="d" * 64,
            donor_table="donors_v3",
            matchability_band_version=4,
            data_release="nhsbt_hla_mm_crf_2024",
        )


def test_missing_database_fingerprint_fails_closed():
    with patch.object(Path, "is_file", return_value=False):
        with pytest.raises(FileNotFoundError, match="missing.db"):
            DataLoader._file_sha256("some/private/path/missing.db")


def test_invalid_matchability_band_release_is_rejected():
    loader = object.__new__(DataLoader)
    loader.matchability_ver = 999

    with pytest.raises(DataLoadError, match="999"):
        loader._validate_matchability_bands({})


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_bundled_matchability_band_shapes_are_valid(version):
    loader = DataLoader(matchability_ver=version)
    bands = loader.matchability_bands()

    loader._validate_matchability_bands(bands)
    if version == 4:
        assert loader.provenance.data_release == "nhsbt_hla_mm_crf_2024"
    else:
        assert loader.provenance.data_release is None


def test_duplicate_matchability_band_rows_are_rejected():
    loader = object.__new__(DataLoader)
    loader.matchability_ver = 4
    loader._load_table = lambda *_args, **_kwargs: pd.DataFrame(
        {"bg": ["A", "A", "B", "O", "AB"], "ver": [4, 4, 4, 4, 4], "sizes": [1, 1, 1, 1, 1]}
    )

    with pytest.raises(DataLoadError, match="version: 4"):
        loader.matchability_bands()
