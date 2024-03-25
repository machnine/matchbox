"""the calculator"""

from typing import Dict, List, Optional, Set

from pandas import DataFrame, Series
from pydantic import BaseModel


class Results(BaseModel):
    """Calculator spec"""

    crf: float
    available: Optional[int] = None
    favourable: Optional[int] = None
    matchability: Optional[int] = None


class Calculator:
    """Calculator class"""

    def __init__(
        self,
        donors: DataFrame = None,
        specs: List[str] = None,
        abo: str = None,
        recipient_bdr: Optional[Dict[str, Set]] = None,
        hla_bdr: Dict[str, List[str]] = None,
        ag_defaults: Dict[str, List[str]] = None,
        matchability_bands: Dict[str, Dict[int, int]] = None,
    ):
        self.abo = abo  # recipient blood group
        self.donors = donors[donors.bg == self.abo]  # blood group identical donor hla types
        self.specs = specs  # recipient antibody specs
        self.hla_bdr = hla_bdr  # broad hla B and DR antigens for matchability calculation
        self.recipient_bdr = recipient_bdr  # recipient broad hla B and DR antigens for matchability calculation
        self.compatible_donors, self.incompatible_donors = self._get_donors()
        self.ag_defaults = ag_defaults  # default antigens mapping rarer antigens to common ones
        self.matchability_bands = matchability_bands  # matchability bands for this blood group

    def calculate(self) -> Results:
        """calculcate crf and matachability"""
        # calculate crf
        crf = len(self.incompatible_donors) / len(self.donors)
        # calculate matchability
        fav_matched = self._get_favourable_count()
        matchability = self._calculate_matchability(fav_matched) if fav_matched is not None else None
        return Results(
            crf=crf, available=len(self.compatible_donors), favourable=fav_matched, matchability=matchability
        )

    def _get_donors(self) -> List[DataFrame]:
        """get compatible/incompatible donors from those blood group identical"""
        has_dsa = self.donors[self.specs].eq(1).any(axis=1)
        return self.donors[~has_dsa], self.donors[has_dsa]

    def _get_donor_types(self) -> DataFrame:
        """get the HLA compatibel donors' HLA types (no dsa): return the column name if the value is 1"""
        # if there is no compatible donor, return empty data frame
        if self.compatible_donors.empty:
            return DataFrame(columns=["B", "DR"])

        b_mask = self.compatible_donors[self.hla_bdr["B"]].eq(1)
        dr_mask = self.compatible_donors[self.hla_bdr["DR"]].eq(1)

        b_types = b_mask.apply(lambda x: set(x.index[x]), axis=1)
        dr_types = dr_mask.apply(lambda x: set(x.index[x]), axis=1)
        return DataFrame({"B": b_types, "DR": dr_types})

    def _get_matching(self, dtypes: Series, locus: str) -> int:
        """get the number of matching antigens for a given locus"""
        # recipient B or DR types
        recipient_bdr = self.recipient_bdr[locus].copy()
        # add the defaults for the rarer antigens the recipient for matching
        recipient_bdr.update({self.ag_defaults[ag] for ag in recipient_bdr if ag in self.ag_defaults})
        # return the number of antigen matched
        return dtypes[locus].apply(lambda d: len(d.difference(recipient_bdr)))

    def _get_favourable_count(self) -> Optional[int]:
        """calculate matchability"""
        if self.recipient_bdr:
            donor_types = self._get_donor_types()
            b_match = self._get_matching(donor_types, "B")
            dr_match = self._get_matching(donor_types, "DR")
            # work out the matching grades
            matchings = DataFrame({"B": b_match, "DR": dr_match})

            # calculate the matchability
            # 'favorable' matchings:
            # 0 DR mismatch and 0-1 B mismatch or 1 DR mismatch and 0 B mismatch
            fav_matched = matchings.apply(
                lambda row: (row.DR == 0 and row.B < 2) or (row.DR == 1 and row.B == 0), axis=1
            ).sum()

            return fav_matched
        return None

    def _calculate_matchability(self, fav_matched: int) -> int:
        """calculate matchability"""
        return next((b for b, v in sorted(self.matchability_bands[self.abo].items()) if fav_matched >= v))
