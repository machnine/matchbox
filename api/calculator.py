"""the calculator"""

from typing import Dict, List, Optional, Set

from pandas import DataFrame, Series
from pydantic import BaseModel

# NHSBT B/DR mismatch grades. Defined here because this is the lowest-level
# module that owns matching; api/mismatch.py collapses these to the levels the
# offer assessment ranks on, so the two surfaces cannot disagree about what a
# given B/DR mismatch pair means.
GRADE_ORDER = ("m12a", "m2b", "m3a", "m3b", "m4a", "m4b")
GRADE_LEVELS = {"m12a": 1, "m2b": 2, "m3a": 3, "m3b": 3, "m4a": 4, "m4b": 4}
FAVOURABLE_LEVELS = (1, 2)


def parse_recipient_bdr(antigens: List[str]) -> Dict[str, Set[str]]:
    """split a recipient's HLA list into the B and DR sets the matcher expects

    BW antigens are excluded: they are not in the matchability antigen list, so
    they would be dropped downstream anyway, and routing them into B invites the
    reader to think they count.
    """
    result: Dict[str, Set[str]] = {"B": set(), "DR": set()}
    for antigen in antigens:
        if antigen.startswith("DR"):
            result["DR"].add(antigen)
        elif antigen.startswith("B") and not antigen.startswith("BW"):
            result["B"].add(antigen)
    return result


def split_by_dsa(donors: DataFrame, specs: List[str]) -> tuple:
    """split donors into (compatible, incompatible) on the recipient's specs

    The single definition of what counts as a DSA against a donor. The cRF
    denominator and the offer assessment's reference population are the two
    halves of this split, so they must come from the same predicate.
    """
    if not specs:
        return donors, donors.iloc[0:0]
    has_dsa = donors[specs].eq(1).any(axis=1)
    return donors[~has_dsa], donors[has_dsa]


def mismatch_counts(
    donors: DataFrame,
    recipient_bdr: Dict[str, Set[str]],
    hla_bdr: Dict[str, List[str]],
    ag_defaults: Dict[str, str],
) -> DataFrame:
    """B and DR broad mismatch counts for every donor in a frame

    The single definition of the count. The recipient's antigen set is widened by
    the rare-antigen defaults before differencing, so a rare antigen does not read
    as a mismatch against its common equivalent.

    Takes the frame as a parameter because the two callers score different
    populations: the cRF calculation counts over compatible donors, the offer
    assessment over the incompatible reference set. The population differs; the
    arithmetic must not.
    """
    result = {}
    for locus in ("B", "DR"):
        columns = [c for c in hla_bdr.get(locus, []) if c in donors.columns]
        recipient = set(recipient_bdr.get(locus, set()))
        recipient.update({ag_defaults[ag] for ag in list(recipient) if ag in ag_defaults})

        if not columns or donors.empty:
            result[locus] = Series(0, index=donors.index, dtype=int)
            continue

        mask = donors[columns].eq(1)
        result[locus] = mask.apply(lambda row: len(set(row.index[row]).difference(recipient)), axis=1)

    return DataFrame(result, index=donors.index)


def mismatch_grade(b_mm: int, dr_mm: int) -> str:
    """NHSBT mismatch grade from B and DR broad mismatch counts"""
    if b_mm not in range(3) or dr_mm not in range(3):
        raise ValueError(f"invalid B/DR mismatch counts: B={b_mm}, DR={dr_mm}")
    if dr_mm == 0 and b_mm < 2:
        return "m12a"  # 000 or 0DR, 0/1B
    if dr_mm == 1 and b_mm == 0:
        return "m2b"  # 1DR, 0B
    if dr_mm == 0 and b_mm == 2:
        return "m3a"  # 0DR, 2B
    if dr_mm == 1 and b_mm == 1:
        return "m3b"  # 1DR, 1B
    if dr_mm == 1 and b_mm == 2:
        return "m4a"  # 1DR, 2B
    if dr_mm == 2:
        return "m4b"  # 2DR
    raise ValueError(f"invalid B/DR mismatch counts: B={b_mm}, DR={dr_mm}")


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
        return split_by_dsa(self.donors, self.specs)

    def _get_matching_level_count(self) -> Optional[Dict[str, int]]:
        """calculate matching level count

        Counts and grades both come from the module-level helpers above, which
        api/mismatch.py also uses -- so the cRF page and the offer assessment
        cannot disagree about what a given B/DR mismatch pair means.
        """
        if self.recipient_bdr:
            matchings = mismatch_counts(self.compatible_donors, self.recipient_bdr, self.hla_bdr, self.ag_defaults)
            if matchings.empty:
                return {"fav": 0, **{grade: 0 for grade in GRADE_ORDER}}

            grades = matchings.apply(lambda row: mismatch_grade(int(row.B), int(row.DR)), axis=1)
            counts = {grade: int((grades == grade).sum()) for grade in GRADE_ORDER}

            # 'favourable' is levels 1 and 2
            fav = sum(n for grade, n in counts.items() if GRADE_LEVELS[grade] in FAVOURABLE_LEVELS)
            return {"fav": fav, **counts}
        return None

    def _calculate_matchability(self, fav_matched: int) -> int:
        """calculate matchability"""
        return next((b for b, v in sorted(self.matchability_bands[self.abo].items()) if fav_matched >= v))
