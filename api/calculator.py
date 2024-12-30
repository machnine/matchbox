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
    match_counts: Optional[Dict[str, int]] = None


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
        match_counts = self._get_matching_level_count()
        fav_matched = match_counts["fav"] if match_counts else None
        matchability = self._calculate_matchability(fav_matched) if fav_matched is not None else None
        return Results(
            crf=crf,
            available=len(self.compatible_donors),
            favourable=fav_matched,
            matchability=matchability,
            match_counts=match_counts,
        )

    def _get_donors(self) -> List[DataFrame]:
        """get compatible/incompatible donors from those blood group identical"""
        has_dsa = self.donors[self.specs].eq(1).any(axis=1)
        return self.donors[~has_dsa], self.donors[has_dsa]

    def _get_donor_types(self) -> DataFrame:
        """get the HLA compatible donors' HLA types (no dsa): return the column name if the value is 1"""
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

    def _get_matching_level_count(self) -> Optional[Dict[str, int]]:
        """calculate matching level count"""
        if self.recipient_bdr:
            donor_types = self._get_donor_types()
            b_match = self._get_matching(donor_types, "B")
            dr_match = self._get_matching(donor_types, "DR")
            # work out the matching grades
            matchings = DataFrame({"B": b_match, "DR": dr_match})

            def count_matches(dr_val, b_cond):
                # helper function to count matches
                if callable(b_cond):
                    return matchings.apply(lambda row: row.DR == dr_val and b_cond(row.B), axis=1).sum()
                return matchings.apply(lambda row: row.DR == dr_val and row.B == b_cond, axis=1).sum()

            # 'favorable' matchings:
            m12a = count_matches(0, lambda x: x < 2)  # 000 or 0DR, 0/1B
            m2b = count_matches(1, 0)  # 1DR, 0B
            m3a = count_matches(0, 2)  # 0DR, 2B
            m3b = count_matches(1, 1)  # 1DR, 1B
            m4a = count_matches(1, 2)  # 1DR, 2B
            m4b = count_matches(2, lambda x: True)  # 2DR

            return {"fav": m12a + m2b, "m12a": m12a, "m2b": m2b, "m3a": m3a, "m3b": m3b, "m4a": m4a, "m4b": m4b}
        return None

    def _calculate_matchability(self, fav_matched: int) -> int:
        """calculate matchability"""
        return next((b for b, v in sorted(self.matchability_bands[self.abo].items()) if fav_matched >= v))
