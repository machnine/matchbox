"""mismatch level and the joint burden/mismatch view

Mismatch level is a different kind of quantity from antibody burden: it relates
to long-term outcome and allocation, not to how hard the incompatibility is to
strip now. The two can point opposite ways, and a donor low on both is the
genuinely rare offer.

So this is presented as a joint view over the reference population -- a small
contingency of burden band against mismatch level -- rather than as a fifth
parallel distribution that would invite reading it on the same axis as the four
burden metrics.

Both the per-donor B/DR mismatch counting and the grade cutpoints come from
api/calculator.py, so a mismatch level here means what it means on the cRF page
by construction rather than by coincidence. The two surfaces differ only in the
population they score: the cRF calculation counts over compatible donors, this
counts over the incompatible reference set.
"""

from typing import Dict, List, Optional, Set

from pandas import DataFrame, Series
from pydantic import BaseModel

from .burden import Metric, MFIBasis, score
from .calculator import (
    FAVOURABLE_LEVELS,
    GRADE_LEVELS,
    mismatch_counts,
    mismatch_grade,
    parse_recipient_bdr,
)
from .cohort import Cohort

__all__ = [
    "FAVOURABLE_LEVELS",
    "MISMATCH_LEVELS",
    "JointCell",
    "JointView",
    "build_joint_view",
    "burden_bands",
    "mismatch_counts",
    "mismatch_level",
    "mismatch_levels",
    "parse_recipient_bdr",
]

# Human-readable descriptions of the levels. The cutpoints themselves live in
# api/calculator.py -- see mismatch_level below.
MISMATCH_LEVELS = {
    1: "000 or 0DR, 0/1B",
    2: "1DR, 0B",
    3: "0DR 2B, or 1DR 1B",
    4: "1DR 2B, or 2DR",
}


class JointCell(BaseModel):
    """one cell of the burden-by-mismatch contingency"""

    burden_band: int  # 1 = lowest burden quartile
    mismatch_level: int
    count: int


class JointView(BaseModel):
    """burden against mismatch level over the reference population"""

    cells: List[JointCell]
    burden_band_edges: List[float]
    metric: Metric
    basis: MFIBasis
    reference_size: int
    offered_burden_band: Optional[int] = None
    offered_mismatch_level: Optional[int] = None
    n_better_on_both: Optional[int] = None
    n_worse_on_both: Optional[int] = None

    def count_at(self, band: int, level: int) -> int:
        return sum(c.count for c in self.cells if c.burden_band == band and c.mismatch_level == level)


def mismatch_level(b_mm: int, dr_mm: int) -> int:
    """NHSBT mismatch level from B and DR broad mismatch counts

    Derived from the grade cutpoints in api/calculator.py, which are the single
    definition -- the cRF page reports grades, the offer page ranks on levels,
    and neither can drift from the other.
    """
    return GRADE_LEVELS[mismatch_grade(b_mm, dr_mm)]


def mismatch_levels(
    donors: DataFrame,
    recipient_bdr: Dict[str, Set[str]],
    hla_bdr: Dict[str, List[str]],
    ag_defaults: Dict[str, str],
) -> Series:
    """mismatch level for every donor in a frame"""
    counts = mismatch_counts(donors, recipient_bdr, hla_bdr, ag_defaults)
    return counts.apply(lambda row: mismatch_level(int(row.B), int(row.DR)), axis=1)


def burden_bands(values: Series, n_bands: int = 4) -> tuple[Series, List[float]]:
    """assign donors to burden bands by quantile

    Quantile banding rather than equal-width, because the MFI distribution is
    heavily right-skewed and equal-width bands would put almost every donor in
    the first. Heavy ties mean the bands will rarely be equal in size -- with few
    specificities several bands may collapse -- so the edges are returned for
    display alongside the counts.
    """
    if values.empty:
        return Series(dtype=int), []

    edges = [float(values.quantile(i / n_bands)) for i in range(1, n_bands)]

    def band_of(value: float) -> int:
        for i, edge in enumerate(edges, start=1):
            if value <= edge:
                return i
        return n_bands

    return values.map(band_of), edges


def build_joint_view(
    cohort: Cohort,
    profile,
    reference: DataFrame,
    recipient_bdr: Dict[str, Set[str]],
    hla_bdr: Dict[str, List[str]],
    ag_defaults: Dict[str, str],
    metric: Metric = Metric.CUMULATIVE,
    basis: MFIBasis = MFIBasis.CURRENT,
    offered_donor: Optional[Series] = None,
) -> JointView:
    """cross burden band with mismatch level over the reference population

    Where the offered donor is supplied, its own cell is marked and the count of
    donors better on *both* axes is reported -- the number that answers "is this
    offer unusually good", which neither axis answers alone.
    """
    mfi = profile.series_for(basis)
    usable = [s for s in mfi.index if s in reference.columns]
    mfi = mfi[usable]

    scored = score(reference, mfi)
    values = scored[metric.value]
    bands, edges = burden_bands(values)
    levels = mismatch_levels(reference, recipient_bdr, hla_bdr, ag_defaults)

    cells: List[JointCell] = []
    for band in sorted(set(bands)) if len(bands) else []:
        for level in sorted(MISMATCH_LEVELS):
            count = int(((bands == band) & (levels == level)).sum())
            if count:
                cells.append(JointCell(burden_band=int(band), mismatch_level=level, count=count))

    offered_band = offered_level = None
    better_both = worse_both = None
    if offered_donor is not None and not reference.empty:
        donor_frame = offered_donor.to_frame().T
        donor_value = float(score(donor_frame, mfi)[metric.value].iloc[0])
        donor_levels = mismatch_levels(donor_frame, recipient_bdr, hla_bdr, ag_defaults)
        offered_level = int(donor_levels.iloc[0])

        offered_band = 1
        for i, edge in enumerate(edges, start=1):
            if donor_value <= edge:
                offered_band = i
                break
        else:
            offered_band = len(edges) + 1

        better_both = int(((values < donor_value) & (levels < offered_level)).sum())
        worse_both = int(((values > donor_value) & (levels > offered_level)).sum())

    return JointView(
        cells=cells,
        burden_band_edges=edges,
        metric=metric,
        basis=basis,
        reference_size=len(reference),
        offered_burden_band=offered_band,
        offered_mismatch_level=offered_level,
        n_better_on_both=better_both,
        n_worse_on_both=worse_both,
    )
