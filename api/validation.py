"""cohort validation: representativeness and replication

Two questions this module answers, kept apart because they are different claims:

* **Representativeness** (§3.2) -- is the DP-typed subset of set 3 distinguishable
  from the rest of set 3 on everything the two share? If it is not, relying on it
  for DP-antibody patients is defensible with evidence rather than by assumption.

* **Replication** (§3.3) -- is a donor's position a property of the patient, or an
  artefact of which cohort was used? Verification asks whether the code computes
  what it claims; replication asks whether the answer means anything. A donor
  top-decile in one set and mid-pack in another is a real problem.

Chi-square is implemented here rather than pulled from scipy: the project does not
otherwise depend on it, and a 2xN test on large contingency tables is a few lines.
"""

from math import erfc, sqrt
from typing import Dict, List, Optional, Sequence

import numpy as np
from pandas import DataFrame
from pydantic import BaseModel

from .burden import AntibodyProfile, Metric, MFIBasis, assess_offer, build_distribution
from .cohort import Cohort, dp_typed_mask, select

# Expected-count floor below which a chi-square approximation is not trusted.
MIN_EXPECTED_COUNT = 5


class FrequencyComparison(BaseModel):
    """one antigen's frequency in two groups"""

    antigen: str
    freq_a: float
    freq_b: float
    chi2: Optional[float]
    p: Optional[float]
    significant: bool
    skipped_reason: Optional[str] = None

    @property
    def difference(self) -> float:
        return self.freq_a - self.freq_b


class RepresentativenessReport(BaseModel):
    """whether a subset is distinguishable from its complement"""

    subset_size: int
    complement_size: int
    abo_p: Optional[float]
    abo_freqs_subset: Dict[str, float]
    abo_freqs_complement: Dict[str, float]
    comparisons: List[FrequencyComparison]
    n_tested: int
    n_significant: int
    bonferroni_threshold: float

    @property
    def representative(self) -> bool:
        """no evidence of a difference in ABO or any antigen frequency

        Absence of evidence, stated as such: this tests marginal frequencies, not
        haplotypes, and does not establish that the typing mechanism was random.
        """
        abo_ok = self.abo_p is None or self.abo_p > 0.05
        return abo_ok and self.n_significant == 0

    def summary(self) -> str:
        verdict = "no detectable difference" if self.representative else "DIFFERENCES DETECTED"
        abo = f"{self.abo_p:.3g}" if self.abo_p is not None else "n/a"
        return (
            f"{verdict}: subset n={self.subset_size}, complement n={self.complement_size}; "
            f"ABO p={abo}; {self.n_significant} of {self.n_tested} antigens significant "
            f"at Bonferroni threshold {self.bonferroni_threshold:.2g}"
        )


class PositionalStatement(BaseModel):
    """where a donor sits on one cohort's distribution, in terms comparable across cohorts"""

    donor_set: str
    reference_size: int
    value: float
    n_lower: int
    percentile: Optional[float]
    decile: Optional[int]


class ReplicationReport(BaseModel):
    """one profile-donor pair assessed across several cohorts"""

    label: str
    metric: Metric
    basis: MFIBasis
    statements: List[PositionalStatement]
    max_decile_spread: Optional[int]
    max_percentile_spread: Optional[float]
    replicates: bool

    def summary(self) -> str:
        verdict = "consistent" if self.replicates else "INCONSISTENT"
        deciles = ", ".join(f"{s.donor_set.replace('donors_', '')}=D{s.decile}" for s in self.statements)
        return f"{self.label} [{self.metric.value}/{self.basis.value}]: {verdict} ({deciles})"


def chi2_2xn(table: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """chi-square statistic and p-value for a 2xN contingency table

    Returns (None, None) when any expected count falls below the floor, rather
    than reporting a p-value the approximation does not support.
    """
    table = np.asarray(table, dtype=float)
    n = table.sum()
    if n == 0:
        return None, None
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / n
    if (expected < MIN_EXPECTED_COUNT).any():
        return None, None
    chi2 = float(((table - expected) ** 2 / expected).sum())
    df = (table.shape[0] - 1) * (table.shape[1] - 1)
    return chi2, chi2_sf(chi2, df)


def chi2_sf(chi2: float, df: int) -> float:
    """upper tail probability of the chi-square distribution

    Exact for df=1 via the error function; Wilson-Hilferty cube-root
    approximation otherwise, which is accurate to about three decimal places in
    the tail region that matters here.
    """
    if chi2 <= 0:
        return 1.0
    if df == 1:
        return erfc(sqrt(chi2 / 2))
    z = ((chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))) / sqrt(2 / (9 * df))
    return 0.5 * erfc(z / sqrt(2))


def compare_frequencies(
    group_a: DataFrame,
    group_b: DataFrame,
    columns: Sequence[str],
    alpha: float = 0.05,
) -> List[FrequencyComparison]:
    """test each column's frequency between two groups"""
    testable = []
    for column in columns:
        if column not in group_a.columns or column not in group_b.columns:
            continue
        a_pos, b_pos = int(group_a[column].sum()), int(group_b[column].sum())
        table = np.array([[a_pos, len(group_a) - a_pos], [b_pos, len(group_b) - b_pos]])
        chi2, p = chi2_2xn(table)
        testable.append(
            FrequencyComparison(
                antigen=column,
                freq_a=a_pos / len(group_a) if len(group_a) else 0.0,
                freq_b=b_pos / len(group_b) if len(group_b) else 0.0,
                chi2=chi2,
                p=p,
                significant=False,
                skipped_reason=None if p is not None else "expected count below 5",
            )
        )

    tested = [c for c in testable if c.p is not None]
    threshold = alpha / len(tested) if tested else alpha
    for comparison in tested:
        comparison.significant = comparison.p < threshold
    return testable


def check_representativeness(
    donors: DataFrame,
    antigens: Sequence[str],
    alpha: float = 0.05,
) -> RepresentativenessReport:
    """compare the DP-typed subset against the rest of the set

    Compares on everything the two groups share -- ABO and every non-DP antigen.
    DP columns are excluded by construction: they are what defines the split.
    """
    typed_mask = dp_typed_mask(donors)
    subset, complement = donors[typed_mask], donors[~typed_mask]

    non_dp = [a for a in antigens if not a.startswith("DPB") and a in donors.columns]
    comparisons = compare_frequencies(subset, complement, non_dp, alpha=alpha)

    groups = sorted(donors.bg.unique())
    table = np.array(
        [
            [int((subset.bg == g).sum()) for g in groups],
            [int((complement.bg == g).sum()) for g in groups],
        ]
    )
    _, abo_p = chi2_2xn(table)

    tested = [c for c in comparisons if c.p is not None]
    return RepresentativenessReport(
        subset_size=len(subset),
        complement_size=len(complement),
        abo_p=abo_p,
        abo_freqs_subset={g: float((subset.bg == g).mean()) for g in groups},
        abo_freqs_complement={g: float((complement.bg == g).mean()) for g in groups},
        comparisons=sorted(comparisons, key=lambda c: (c.p is None, c.p or 1.0)),
        n_tested=len(tested),
        n_significant=sum(1 for c in tested if c.significant),
        bonferroni_threshold=alpha / len(tested) if tested else alpha,
    )


def positional_statement(
    cohort: Cohort,
    profile: AntibodyProfile,
    donor,
    metric: Metric,
    basis: MFIBasis,
    donor_set: str,
    percentile_floor: int = 0,
) -> PositionalStatement:
    """where one donor sits on one cohort's distribution"""
    distribution = build_distribution(cohort, profile, basis, percentile_floor=percentile_floor)
    result = assess_offer(cohort, profile, donor, percentile_floor=percentile_floor)
    placement = result.placements[f"{basis.value}:{metric.value}"]
    decile = None
    if placement.percentile is not None:
        decile = min(10, int(placement.percentile // 10) + 1)
    return PositionalStatement(
        donor_set=donor_set,
        reference_size=distribution.reference_size,
        value=placement.value,
        n_lower=placement.n_lower,
        percentile=placement.percentile,
        decile=decile,
    )


def replicate_across_sets(
    donor_frames: Dict[str, DataFrame],
    recipient_bg: str,
    profile: AntibodyProfile,
    donor,
    label: str,
    metric: Metric = Metric.CUMULATIVE,
    basis: MFIBasis = MFIBasis.CURRENT,
    max_decile_spread: int = 1,
) -> ReplicationReport:
    """assess one profile-donor pair against several cohorts and compare positions

    Compares the *positional* statement, not the raw value: the sets differ in
    composition, so identical burden values are not expected, but a donor's
    standing relative to the population should be stable if it is a property of
    the patient rather than of the cohort.

    Only sets that can score the whole profile take part. A profile with DP
    specificities can only be assessed on set 3, so replication is unavailable --
    which is the DP debt showing up exactly where it should.
    """
    specs = [s.spec for s in profile.specs]
    statements: List[PositionalStatement] = []

    for set_name, frame in donor_frames.items():
        missing = [s for s in specs if s not in frame.columns]
        if missing:
            continue
        cohort = select(frame, recipient_bg=recipient_bg, specs=specs, donor_set=set_name, stats_floor=0)
        statements.append(positional_statement(cohort, profile, donor, metric, basis, donor_set=set_name))

    deciles = [s.decile for s in statements if s.decile is not None]
    percentiles = [s.percentile for s in statements if s.percentile is not None]
    decile_spread = (max(deciles) - min(deciles)) if len(deciles) > 1 else None
    percentile_spread = (max(percentiles) - min(percentiles)) if len(percentiles) > 1 else None

    replicates = decile_spread is not None and decile_spread <= max_decile_spread
    return ReplicationReport(
        label=label,
        metric=metric,
        basis=basis,
        statements=statements,
        max_decile_spread=decile_spread,
        max_percentile_spread=percentile_spread,
        replicates=replicates,
    )
