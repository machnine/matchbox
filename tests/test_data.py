"""Tests for DataLoader class"""

from unittest.mock import MagicMock, patch

import pandas as pd

from api.data import DataLoader


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
    data_loader = DataLoader(db_path="mock_db.db")
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
        {"bg": ["A", "B", "O"], "1": [100, 200, 300], "2": [150, 250, 350], "ver": [4, 4, 4], "sizes": ["1", "2", "3"]}
    )
    mock_connect, mock_conn = setup_mock_db(mock_df)
    pd_read_sql_query_original = pd.read_sql_query

    def mock_read_sql_query(sql, con, *args, **kwargs):
        # Assuming sql contains the correct query, return the mock DataFrame directly
        if "matchability_bands" in sql:
            return mock_df
        return pd_read_sql_query_original(sql, con, *args, **kwargs)

    with patch("pandas.read_sql_query", side_effect=mock_read_sql_query):
        data_loader = DataLoader(db_path="mock_db.db")
        bands_dict = data_loader.matchability_bands()

    # Assertions to ensure matchability_bands method returns expected data structure and content
    assert isinstance(bands_dict, dict)
    assert set(bands_dict.keys()) == {"A", "B", "O"}
    assert bands_dict["A"] == {1: 100, 2: 150}
    assert bands_dict["B"] == {1: 200, 2: 250}
    assert bands_dict["O"] == {1: 300, 2: 350}


@patch("pandas.read_sql_query")
@patch("sqlite3.connect")
def test_matchability_antigens_mothod(mock_connect, mock_read_sql_query):
    mock_df = pd.DataFrame(
        {"locus": ["B", "B", "B", "DR", "DR", "DR"], "antigen": ["B44", "B27", "B5", "DR1", "DR15", "DR9"]}
    )

    mock_connect, mock_conn = setup_mock_db(mock_df)
    mock_read_sql_query.return_value = mock_df

    data_loader = DataLoader(db_path="mock_db.db")
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

    data_loader = DataLoader(db_path="mock_db.db")
    result = data_loader.antigen_defaults()

    # Assertions
    assert result == {"A36": "A1", "B42": "B7", "DR9": "DR4"}
