"""cohort selection: which donors is a given patient assessed against

Selection for the offer-assessment tool. It lives here rather than in the app so
the ABO and DP rules are one mechanism rather than per-endpoint logic.

NOTE: Calculator does *not* yet call select(). It still does its own
blood-group-identical filter (calculator.py, `donors[donors.bg == abo]`), which
ABORule.IDENTICAL reproduces exactly -- so the two agree today, but by
duplication rather than by construction. Routing Calculator through select()
would make that structural; it needs calculator.py to import this module, and
this module currently sits above it in the import graph (data.py imports
cohort, mismatch imports calculator), so it is a module-graph change rather than
a one-line one. Worth doing before the ABO rules gain a second variant.

What *is* shared by construction: the DSA split (calculator.split_by_dsa), the
mismatch grades (calculator.mismatch_grade), the recipient B/DR parse
(calculator.parse_recipient_bdr) and the DP-typed predicate (dp_typed_mask
below, which data.py uses to build its DP-typed frame).

Two axes, independent:

* ABO   -- blood-group-identical (the cRF default, matching the published ODT
           figure) or the wider offerable set under allocation policy.
* DP    -- whether DPB-typed donors only, driven by whether the patient has DP
           antibodies. See DPMode.

Every selection returns a Provenance record alongside the frame. Nothing in this
module returns a bare DataFrame: a cohort that does not say how it was chosen is
not interpretable later, and two cohorts chosen under different rules must not
look comparable when they are not.
"""

from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

from pandas import DataFrame
from pydantic import BaseModel

# Donor sets available in the database. v1/v2 carry no DPB typing at all and are
# held for replication of the non-DP pathway only; v3 is the live set.
DONOR_SETS = ("donors_v1", "donors_v2", "donors_v3")
LIVE_DONOR_SET = "donors_v3"
DP_TYPED_SETS = frozenset({"donors_v3"})


class DPMode(str, Enum):
    """how DP antibodies affect cohort selection

    Three-state, not boolean -- AUTO is the intended default and resolves from
    whether the patient actually has DP specificities.
    """

    INCLUDE = "include"  # rank within DP-typed donors only
    EXCLUDE = "exclude"  # drop DP specificities, rank within the full set
    AUTO = "auto"  # INCLUDE if the patient has DP specs, else full set


class ABORule(str, Enum):
    """which donor blood groups this recipient may be assessed against"""

    IDENTICAL = "identical"  # cRF default; matches the published ODT figure
    OFFERABLE = "offerable"  # allocation-policy offerable set, keyed on organ+tier


class Tier(str, Enum):
    """allocation tier, which widens the offerable ABO set for some recipients"""

    A = "A"
    B = "B"


class CohortTooSmall(ValueError):
    """raised when a selected cohort is below the floor for characterisation

    Carries the count so a caller can report *n donors observed, too few to
    characterise* rather than a smooth-looking percentage over a handful of
    donors.
    """

    def __init__(self, n: int, floor: int, description: str):
        self.n = n
        self.floor = floor
        super().__init__(f"cohort has {n} donors ({description}), below the floor of {floor}")


class ABOPolicyUnavailable(NotImplementedError):
    """raised when an offerable-set selection is requested but not yet encoded

    The offerable donor groups are an allocation-policy question (POL186), not
    something to be inferred from cohort arithmetic. Until the authoritative
    mapping is supplied this raises rather than falling back to identical-only,
    which would silently understate the pool, or to plain ABO compatibility,
    which is not what the policy says.
    """


# Offerable ABO mapping, keyed organ -> tier -> recipient group -> donor groups.
#
# DELIBERATELY UNPOPULATED. The counts in the handoff specification (§4.1) are
# reproducible from several different donor-group mappings, and the one that
# fits is asymmetric in a way that needs confirming against POL186 Table A
# rather than reconstructing. Populate from the policy document, not from the
# cohort. Expected counts to pin the mapping against, for donors_v3 kidney:
#
#     recipient   identical   tier A   tier B
#     O               4,620    4,620    4,620
#     A               4,094    8,714    4,094
#     B                 962    5,582    5,582
#     AB                324    9,038    4,418
#
# Kidney and pancreas differ; a further scheme should be a new entry here rather
# than a change to any calling code.
OFFERABLE_ABO: Dict[str, Dict[Tier, Dict[str, FrozenSet[str]]]] = {}

# Below this, percentiles and breakdowns are not reported. See §6.4 -- the
# honest output for a handful of donors is the raw count, not a percentage.
MIN_COHORT_FOR_STATS = 200


class Provenance(BaseModel):
    """how a cohort was selected

    Travels with every result. A stored assessment should be interpretable years
    later, and where a choice was made by default rather than explicitly, that is
    recorded here so it can be surfaced.
    """

    donor_set: str
    abo_rule: ABORule
    recipient_bg: str
    donor_bgs: List[str]
    tier: Optional[Tier] = None
    organ: Optional[str] = None
    dp_mode_requested: DPMode
    dp_mode_applied: DPMode
    dp_typed_only: bool
    patient_has_dp_specs: bool
    dp_specs_dropped: List[str] = []
    cohort_size: int
    set_size_before_dp: int
    below_stats_floor: bool
    defaulted: List[str] = []

    @property
    def is_dp_corroborable(self) -> bool:
        """whether this selection can be checked against the other donor sets

        DP-typed selections exist only in v3, so a DP assessment cannot be
        corroborated by v1 or v2. Callers should state this as a limitation
        rather than letting the three-set design imply otherwise.
        """
        return not self.dp_typed_only


class Cohort(BaseModel):
    """a selected donor population and the record of how it was selected"""

    donors: object  # DataFrame; pydantic v2 arbitrary types not enabled here
    provenance: Provenance
    specs: List[str]

    model_config = {"arbitrary_types_allowed": True}

    def __len__(self) -> int:
        return len(self.donors)


def dp_columns(donors: DataFrame) -> List[str]:
    """DPB columns present in a donor frame; empty for the non-DP sets"""
    return [col for col in donors.columns if col.startswith("DPB")]


def dp_typed_mask(donors: DataFrame):
    """which donors carry any DP typing

    A donor with no DP typing has 0 in every DPB column, which is indistinguishable
    from genuinely carrying none of them. In donors_v3 no donor is DP-negative at
    every DPB specificity, so all-zero means untyped -- but that inference holds
    only for DP. Every other locus in this data has zero all-zero donors, so the
    untyped/negative ambiguity is a DP problem alone.
    """
    cols = dp_columns(donors)
    if not cols:
        return donors.index.to_series().map(lambda _: False)
    return donors[cols].sum(axis=1) > 0


def split_dp_specs(specs: List[str]) -> Tuple[List[str], List[str]]:
    """partition specificities into DP and non-DP"""
    dp = [s for s in specs if s.startswith("DPB")]
    non_dp = [s for s in specs if not s.startswith("DPB")]
    return dp, non_dp


def resolve_dp_mode(requested: DPMode, has_dp_specs: bool) -> DPMode:
    """resolve AUTO against whether the patient actually has DP antibodies"""
    if requested is not DPMode.AUTO:
        return requested
    return DPMode.INCLUDE if has_dp_specs else DPMode.EXCLUDE


def donor_bgs_for(
    recipient_bg: str,
    abo_rule: ABORule,
    organ: Optional[str] = None,
    tier: Optional[Tier] = None,
) -> FrozenSet[str]:
    """which donor blood groups this recipient is assessed against

    Raises ABOPolicyUnavailable for OFFERABLE until the policy mapping is
    populated -- see OFFERABLE_ABO.
    """
    if abo_rule is ABORule.IDENTICAL:
        return frozenset({recipient_bg})

    if organ is None or tier is None:
        raise ABOPolicyUnavailable("offerable ABO selection requires both organ and tier")

    by_organ = OFFERABLE_ABO.get(organ)
    if not by_organ:
        raise ABOPolicyUnavailable(
            f"no offerable ABO mapping encoded for organ {organ!r}; populate OFFERABLE_ABO from POL186 Table A"
        )
    by_tier = by_organ.get(tier)
    if not by_tier or recipient_bg not in by_tier:
        raise ABOPolicyUnavailable(
            f"no offerable ABO mapping encoded for organ {organ!r} tier {tier.value} recipient {recipient_bg!r}"
        )
    return by_tier[recipient_bg]


def select(
    donors: DataFrame,
    recipient_bg: str,
    specs: List[str],
    donor_set: str = LIVE_DONOR_SET,
    abo_rule: ABORule = ABORule.IDENTICAL,
    dp_mode: DPMode = DPMode.AUTO,
    organ: Optional[str] = None,
    tier: Optional[Tier] = None,
    stats_floor: int = MIN_COHORT_FOR_STATS,
    strict_floor: bool = False,
) -> Cohort:
    """select the donor population a patient is assessed against

    The single entry point for both tools. cRF calls it with the identical-only
    default and gets exactly its historical population back; the offer tool calls
    it with an explicit ABO rule and tier.

    DP handling follows the resolved mode:

    * INCLUDE -- the cohort is restricted to DP-typed donors and every DP
      specificity is retained. Only donors_v3 has DP typing, so this is not
      available on the other sets and is not corroborable by them.
    * EXCLUDE -- DP specificities are dropped from the antibody profile and the
      full set is used. The dropped specificities are recorded in provenance so
      a caller can state what was discarded rather than silently producing a
      lower number.

    Raises CohortTooSmall when strict_floor is set and the result is below the
    floor; otherwise the floor breach is flagged in provenance and left to the
    caller.
    """
    if recipient_bg not in set(donors.bg.unique()):
        raise ValueError(f"no donors of blood group {recipient_bg!r} in {donor_set}")

    defaulted: List[str] = []
    if abo_rule is ABORule.IDENTICAL and tier is None and organ is None:
        defaulted.append("abo_rule=identical")
    if dp_mode is DPMode.AUTO:
        defaulted.append("dp_mode=auto")

    dp_specs, non_dp_specs = split_dp_specs(specs)
    has_dp_specs = bool(dp_specs)
    applied = resolve_dp_mode(dp_mode, has_dp_specs)

    bgs = donor_bgs_for(recipient_bg, abo_rule, organ=organ, tier=tier)
    frame = donors[donors.bg.isin(bgs)]
    set_size_before_dp = len(frame)

    dropped: List[str] = []
    effective_specs = list(specs)
    dp_typed_only = False

    if applied is DPMode.INCLUDE:
        if donor_set not in DP_TYPED_SETS:
            raise ValueError(f"{donor_set} carries no DP typing; DP mode 'include' requires {sorted(DP_TYPED_SETS)}")
        frame = frame[dp_typed_mask(frame)]
        dp_typed_only = True
    else:
        # DP specificities cannot be scored against donors that may be untyped:
        # a 0 in a DPB column means "untyped or absent" and would read as no DSA,
        # placing untyped donors at the low-burden end -- exactly the end being
        # inspected. Drop them explicitly and say so.
        if has_dp_specs:
            dropped = dp_specs
            effective_specs = non_dp_specs

    n = len(frame)
    below_floor = n < stats_floor
    if below_floor and strict_floor:
        raise CohortTooSmall(
            n,
            stats_floor,
            f"{recipient_bg} recipient, {abo_rule.value} ABO, DP {applied.value}, {donor_set}",
        )

    provenance = Provenance(
        donor_set=donor_set,
        abo_rule=abo_rule,
        recipient_bg=recipient_bg,
        donor_bgs=sorted(bgs),
        tier=tier,
        organ=organ,
        dp_mode_requested=dp_mode,
        dp_mode_applied=applied,
        dp_typed_only=dp_typed_only,
        patient_has_dp_specs=has_dp_specs,
        dp_specs_dropped=dropped,
        cohort_size=n,
        set_size_before_dp=set_size_before_dp,
        below_stats_floor=below_floor,
        defaulted=defaulted,
    )
    return Cohort(donors=frame, provenance=provenance, specs=effective_specs)
