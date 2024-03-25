"""database handling"""

import re
import sqlite3
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from pydantic import BaseModel

from .logger import log_manager

logger = log_manager.get_logger("error.log", log_source="data.py")


class DataLoader:
    """load data into memory"""

    def __init__(self, db_path: str = None, table_name: str = None, matchability_ver: int = None):
        self.db_path = db_path or "data/donors.db"
        if not self._database_exists(self.db_path):
            logger.error("Database file %s not found", db_path)
            raise FileNotFoundError(f"Database file {self.db_path} not found")
        self.conn = sqlite3.connect(self.db_path)
        self.table_name = table_name or "donors_v3"
        self.matchability_ver = matchability_ver or 4
        self.donors = self._load_donors()

    def _database_exists(self, db_file: str) -> bool:
        """check if database exists"""
        return True if Path(db_file).is_file() else False

    def _load_table(self, table_name: str, conditions: str = "") -> pd.DataFrame:
        """load a table from sqlite database"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table_name} {conditions}", self.conn)
                # convert numeric columns to int (i.e. for matchability bands)
                rename_dict = {col: int(col) if col.isdigit() else col for col in df.columns}
                df.rename(columns=rename_dict, inplace=True)
                df.flags.writeable = False  # Make the DataFrame immutable
            except (sqlite3.Error, ValueError) as e:
                logger.error("Error loading table %s: %s", table_name, e)
                df = pd.DataFrame()
        return df

    def _get_locus(self, antigen: str) -> str:
        """get locus from antigen"""
        if match := re.match(r"^([ABCDRQPW]{1,3})\d+", antigen):
            return match.group(1)

    def _load_donors(self) -> Tuple[pd.DataFrame]:
        """load data into memory"""
        data = self._load_table(self.table_name)
        # filter out donors with no dpb
        dpb_cols = [col for col in data.columns if "DPB" in col]
        donor_data = (data.copy(deep=False), data[data[dpb_cols].sum(axis=1) > 0].copy(deep=False))
        # empty the donors variable
        data = None
        return donor_data

    def antigens(self) -> Dict[str, List[str]]:
        """HLA antigens represented"""
        antigen_dict = defaultdict(list)
        cols = self.donors[0].columns
        for col in cols:
            if col not in ["A19_S"]:
                if locus := self._get_locus(col):
                    antigen_dict[locus].append(col)
        return antigen_dict

    def matchability_bands(self) -> Dict[str, Dict[int, int]]:
        """load matchability bands"""
        m_bands = self._load_table("matchability_bands", f"where ver={self.matchability_ver}")
        bands_dict = (
            m_bands.set_index("bg")
            .drop(columns=["ver", "sizes"])
            .apply(lambda row: row.dropna().to_dict(), axis=1)
            .to_dict()
        )
        return bands_dict

    def matchability_antigens(self) -> Dict[str, List[str]]:
        """load antigens used for matchability calculations"""
        data = self._load_table("matchability_antigens")
        return data.groupby("locus").agg(list)["antigen"].to_dict()

    def antigen_defaults(self) -> Dict[str, str]:
        """load default antigens for matchability calculations"""
        data = self._load_table("antigen_defaults", "where locus in ('B', 'DR')")
        return data.reset_index().set_index("rare")["default"].to_dict()

    @property
    def base_data(self):
        """get data"""
        return LoadedData(
            donors=self.donors,
            antigens=self.antigens(),
            mbands=self.matchability_bands(),
            mantigens=self.matchability_antigens(),
            antigen_defaults=self.antigen_defaults(),
        )


class LoadedData(BaseModel):
    """loaded data"""

    donors: Any
    antigens: Dict[str, List[str]]
    mbands: Dict[str, Dict[int, int]]
    mantigens: Dict[str, List[str]]
    antigen_defaults: Dict[str, str]


BaseData = DataLoader().base_data


# dependency function
def load_data():
    """get data"""
    return BaseData
