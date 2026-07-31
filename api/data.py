"""database handling"""

import hashlib
import re
import sqlite3
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .logger import log_manager

logger = log_manager.get_logger("error.log", log_source="data.py")

# TODO: update this list when the calculator excel file is updated
# antigens to exclude from calculations
# ["A19_S", "B0703", "B5102", "B5103", "CW13","DR1403", "DR1404" ...]
# The HLA-antigen assignments were wrong for some antigens - see
# https://nhsbtdbe.blob.core.windows.net/umbraco-assets-corp/35556/inf1766.pdf
# however, these are not yet updated in the donor database, they are not yet
# excluded, exclude them next time the calculator excel file is updated
EXCLUDED_ANTIGENS = ["A19_S", "CW13"]

DEFAULT_DATABASE_PATH = "data/donors.db"
DEFAULT_DONOR_TABLE = "donors_v3"
DEFAULT_MATCHABILITY_BAND_VERSION = 4
DEFAULT_DONOR_DATABASE_SHA256 = "b83b8255a23aaf48bce46b1cc2d14c7199bd1997fefff0b35f73e009d9d92076"
UPSTREAM_SOURCE_FILE = "hla-mm-and-crf_2024.xlsb"
UPSTREAM_SOURCE_FILE_SIZE_SIGNATURE = 24_099_579
KNOWN_DATA_RELEASE = "nhsbt_hla_mm_crf_2024"
EXPECTED_AB_BAND_KEYS = {
    1: {1, 2, 3, 4, 5, 6, 7, 9},
    2: {1, 2, 3, 4, 5, 6, 8},
    3: {1, 2, 3, 4, 5, 6, 7, 9},
    4: {1, 2, 3, 4, 5, 6, 8, 10},
}


class DataLoadError(RuntimeError):
    """Raised when calculator data cannot be identified or validated."""


class DataProvenance(BaseModel):
    """Identifiers for the source and derived data used by the calculator."""

    model_config = ConfigDict(frozen=True)

    upstream_source_file: Optional[str] = Field(default=None, min_length=1)
    upstream_source_file_size_signature: Optional[int] = Field(default=None, gt=0)
    donor_database: str = Field(min_length=1)
    donor_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    donor_table: str = Field(min_length=1)
    matchability_band_version: int = Field(gt=0)
    data_release: Optional[Literal["nhsbt_hla_mm_crf_2024"]] = None

    @model_validator(mode="after")
    def validate_upstream_source_pair(self):
        """A declared upstream artifact must include both available identifiers."""
        if (self.upstream_source_file is None) != (self.upstream_source_file_size_signature is None):
            raise ValueError("upstream source file and size signature must be supplied together")
        if self.data_release == KNOWN_DATA_RELEASE:
            verified_release = (
                self.upstream_source_file == UPSTREAM_SOURCE_FILE
                and self.upstream_source_file_size_signature == UPSTREAM_SOURCE_FILE_SIZE_SIGNATURE
                and self.donor_database_sha256 == DEFAULT_DONOR_DATABASE_SHA256
                and self.donor_table == DEFAULT_DONOR_TABLE
                and self.matchability_band_version == DEFAULT_MATCHABILITY_BAND_VERSION
            )
            if not verified_release:
                raise ValueError("data release does not match the verified calculator artifact")
        return self


class DataLoader:
    """load data into memory"""

    def __init__(
        self,
        db_path: str = None,
        table_name: str = None,
        matchability_ver: int = None,
        upstream_source_file: str = None,
        upstream_source_file_size_signature: int = None,
    ):
        self.db_path = db_path or DEFAULT_DATABASE_PATH
        self.table_name = table_name or DEFAULT_DONOR_TABLE
        self.matchability_ver = matchability_ver or DEFAULT_MATCHABILITY_BAND_VERSION
        self._reject_wal_artifacts()
        database_sha256 = self._file_sha256(self.db_path)
        source_file, source_size_signature, data_release = self._resolve_upstream_source(
            database_sha256,
            upstream_source_file,
            upstream_source_file_size_signature,
        )
        self.provenance = DataProvenance(
            upstream_source_file=source_file,
            upstream_source_file_size_signature=source_size_signature,
            donor_database=Path(self.db_path).name,
            donor_database_sha256=database_sha256,
            donor_table=self.table_name,
            matchability_band_version=self.matchability_ver,
            data_release=data_release,
        )
        database_uri = f"{Path(self.db_path).resolve().as_uri()}?mode=ro"
        self.conn = sqlite3.connect(database_uri, uri=True)
        journal_mode = self.conn.execute("PRAGMA journal_mode").fetchone()
        if journal_mode and str(journal_mode[0]).lower() == "wal":
            self.conn.close()
            raise DataLoadError("Donor database must be checkpointed out of WAL mode")
        self.donors = self._load_donors()

    @staticmethod
    def _file_sha256(file_path: str) -> str:
        """Fingerprint a local data artifact without exposing its full path."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Donor database not found: {path.name}")

        digest = hashlib.sha256()
        try:
            with path.open("rb") as file_handle:
                for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            logger.error("Error fingerprinting database %s: %s", path.name, exc)
            raise DataLoadError(f"Unable to fingerprint donor database: {path.name}") from exc
        return digest.hexdigest()

    def _resolve_upstream_source(
        self,
        database_sha256: str,
        source_file: Optional[str],
        source_size_signature: Optional[int],
    ) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """Bind the declared upstream artifact to the known derived database release."""
        if (source_file is None) != (source_size_signature is None):
            raise ValueError("upstream source file and size signature must be supplied together")

        is_known_release = (
            database_sha256 == DEFAULT_DONOR_DATABASE_SHA256
            and self.table_name == DEFAULT_DONOR_TABLE
            and self.matchability_ver == DEFAULT_MATCHABILITY_BAND_VERSION
        )
        if is_known_release:
            return UPSTREAM_SOURCE_FILE, UPSTREAM_SOURCE_FILE_SIZE_SIGNATURE, KNOWN_DATA_RELEASE
        if source_file is not None:
            return source_file, source_size_signature, None
        return None, None, None

    def _reject_wal_artifacts(self) -> None:
        """Require a single checkpointed SQLite artifact for reproducible hashing."""
        sidecars = [Path(f"{self.db_path}{suffix}") for suffix in ("-wal", "-shm")]
        if any(sidecar.exists() for sidecar in sidecars):
            raise DataLoadError("Donor database has WAL sidecar files and cannot be fingerprinted as one artifact")

    def _validate_matchability_bands(self, bands: Dict[str, Dict[int, int]]) -> None:
        """Reject missing or malformed requested band versions before serving data."""
        required_blood_groups = {"A", "B", "O", "AB"}
        common_keys = set(range(1, 11))
        valid = set(bands) == required_blood_groups
        for blood_group, thresholds in bands.items():
            expected_keys = EXPECTED_AB_BAND_KEYS.get(self.matchability_ver) if blood_group == "AB" else common_keys
            keys = set(thresholds)
            if not keys:
                valid = False
                continue
            valid = valid and keys <= common_keys
            if expected_keys is not None:
                valid = valid and keys == expected_keys

            try:
                ordered = [float(thresholds[band]) for band in sorted(thresholds)]
            except (TypeError, ValueError):
                valid = False
                continue
            valid = valid and all(value >= 0 and value.is_integer() for value in ordered)
            valid = valid and ordered[-1] == 0
            valid = valid and all(left >= right for left, right in zip(ordered, ordered[1:]))

        if not valid:
            raise DataLoadError(f"Invalid or missing matchability band version: {self.matchability_ver}")

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

    def _load_donors(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
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
            if col not in EXCLUDED_ANTIGENS:
                if locus := self._get_locus(col):
                    antigen_dict[locus].append(col)
        return antigen_dict

    def matchability_bands(self) -> Dict[str, Dict[int, int]]:
        """load matchability bands"""
        m_bands = self._load_table("matchability_bands", f"where ver={self.matchability_ver}")
        if (
            m_bands.empty
            or not {"bg", "ver", "sizes"} <= set(m_bands.columns)
            or m_bands["bg"].duplicated().any()
            or set(m_bands["bg"]) != {"A", "B", "O", "AB"}
        ):
            raise DataLoadError(f"Invalid matchability band rows for version: {self.matchability_ver}")
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

    def broad_split_mapping(self) -> Dict[str, Dict[str, Any]]:
        """load broad/split antigen mappings"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT Locus, Split, Broad FROM broad_split_mapping")
            rows = cursor.fetchall()
            
            # Build broad_to_splits and split_to_broad mappings
            broad_to_splits = defaultdict(list)
            split_to_broad = {}
            
            for _locus, split, broad in rows:
                broad_to_splits[broad].append(split)
                split_to_broad[split] = broad
            
            return {
                "broad_to_splits": dict(broad_to_splits),
                "split_to_broad": split_to_broad
            }
        except sqlite3.Error as e:
            logger.error("Error loading broad/split mapping: %s", e)
            return {"broad_to_splits": {}, "split_to_broad": {}}

    @property
    def base_data(self):
        """get data"""
        antigens = self.antigens()
        matchability_bands = self.matchability_bands()
        self._validate_matchability_bands(matchability_bands)
        matchability_antigens = self.matchability_antigens()
        antigen_defaults = self.antigen_defaults()
        broad_split = self.broad_split_mapping()

        self._reject_wal_artifacts()
        final_sha256 = self._file_sha256(self.db_path)
        if final_sha256 != self.provenance.donor_database_sha256:
            raise DataLoadError("Donor database changed while calculator data was loading")

        return LoadedData(
            donors=self.donors,
            antigens=antigens,
            mbands=matchability_bands,
            mantigens=matchability_antigens,
            antigen_defaults=antigen_defaults,
            broad_split=broad_split,
            provenance=self.provenance,
        )


class LoadedData(BaseModel):
    """loaded data"""

    donors: Any
    antigens: Dict[str, List[str]]
    mbands: Dict[str, Dict[int, int]]
    mantigens: Dict[str, List[str]]
    antigen_defaults: Dict[str, str]
    broad_split: Dict[str, Dict[str, Any]]
    provenance: DataProvenance


BaseData = DataLoader().base_data


# dependency function
def load_data():
    """get data"""
    return BaseData
