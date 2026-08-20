"""offer assessment API

Mounted as a separate app from the cRF calculator, sharing only the data layer
and the cohort selection in api/cohort.py -- the two tools must never disagree
about which donors a patient is eligible for.

Two calls, not one (§5.2):

1. POST /offer/distribution -- profile to distributions. Cacheable per resolved
   selection; a lab assessing one patient over a week pays for it once, and a UI
   can mark several offers on one backdrop.
2. POST /offer/placement -- donor to placement against a distribution.

Every response carries the provenance of the selection that produced it. A stored
result should be interpretable years later, and two runs made under different
toggles must not look comparable when they are not.
"""

import re
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator, model_validator

from .assets import asset_version
from .burden import (
    DEFAULT_DSA_THRESHOLD,
    AntibodyProfile,
    Metric,
    MFIBasis,
    OfferStatus,
    SpecMFI,
    assess_offer,
    build_distribution,
    reference_population,
    resolve_profile_mfi,
)
from .cohort import (
    ABOPolicyUnavailable,
    ABORule,
    CohortTooSmall,
    DPMode,
    Provenance,
    Tier,
    select,
)
from .data import DataProvenance, load_data
from .input_validation import AntigenValidationError, validate_recipient_hla
from .mismatch import build_joint_view, parse_recipient_bdr
from .parser import ColumnRole, parse, parse_donor_type
from .ratelimiter import limiter
from .recipient import canonicalise_recipient_hla

router = APIRouter(prefix="/offer", tags=["offer assessment"])
templates = Jinja2Templates(directory="web")
templates.env.globals["asset_version"] = asset_version

# Bumped when a change alters any number a stored result could contain.
POLICY_VERSION = "2026-08-01.1"
VOCABULARY_VERSION = "donors_v3.broad-split"


class SpecInput(BaseModel):
    """one specificity as submitted"""

    spec: str = Field(min_length=1)
    current: float = Field(ge=0, allow_inf_nan=False)
    peak: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("spec", mode="before")
    @classmethod
    def normalise_spec(cls, value):
        return str(value).strip().upper()

    @model_validator(mode="after")
    def peak_cannot_be_below_current(self):
        if self.peak is not None and self.peak < self.current:
            raise ValueError("peak MFI cannot be below current MFI")
        return self


class ProfileRequest(BaseModel):
    """a patient profile and the selection toggles"""

    bg: str = Field(..., pattern=r"^(A|B|AB|O)$")
    specs: List[SpecInput] = Field(min_length=1, max_length=500)
    donor_set: Literal["donors_v3"] = "donors_v3"
    dp_mode: DPMode = DPMode.AUTO
    abo_rule: ABORule = ABORule.IDENTICAL
    organ: Optional[str] = Field(default=None, max_length=32)
    tier: Optional[Tier] = None
    threshold: float = Field(default=DEFAULT_DSA_THRESHOLD, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def reject_duplicate_specificities(self):
        names = [spec.spec for spec in self.specs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate specificities: {', '.join(duplicates)}")
        return self


class PlacementRequest(ProfileRequest):
    """a profile plus the offered donor's HLA type"""

    donor_hla: List[str] = Field(min_length=1, max_length=100)
    donor_bg: Optional[str] = Field(default=None, pattern=r"^(A|B|AB|O)$")
    recip_hla: Optional[str] = Field(default=None, min_length=1, max_length=256)  # B/DR broads, mismatch axis

    @field_validator("donor_hla", mode="before")
    @classmethod
    def normalise_donor_hla(cls, value):
        if not isinstance(value, list):
            return value
        normalised = [str(antigen).strip().upper() for antigen in value]
        if any(not antigen for antigen in normalised):
            raise ValueError("donor HLA contains an empty value")
        if len(normalised) != len(set(normalised)):
            raise ValueError("donor HLA contains duplicate values")
        return normalised


class ParseRequest(BaseModel):
    """a pasted block awaiting preview"""

    text: str = Field(min_length=1, max_length=250_000)
    roles: Optional[List[ColumnRole]] = Field(default=None, max_length=100)


class DonorTypeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class ResponseMeta(BaseModel):
    """what every response carries so it stays interpretable (§5.3)"""

    provenance: Provenance
    data_provenance: DataProvenance
    threshold: float
    policy_version: str = POLICY_VERSION
    vocabulary_version: str = VOCABULARY_VERSION
    notes: List[str] = Field(default_factory=list)


def _vocabulary(data) -> List[str]:
    return [ag for ags in data.antigens.values() for ag in ags]


def _locus(antigen: str) -> Optional[str]:
    match = re.match(r"^([A-Z]+)\d", antigen)
    return match.group(1) if match else None


def _active_specs_by_basis(cohort, profile) -> Dict[str, List[str]]:
    """Specificities that actually enter each basis after threshold and DP policy."""
    active: Dict[str, List[str]] = {}
    for basis in profile.available_bases:
        _, present, _, _ = resolve_profile_mfi(cohort, profile, basis)
        active[basis.value] = present
    return active


def _validate_donor_typing(cohort, profile, donor_hla: List[str]) -> None:
    """Fail closed when an antibody locus is absent from the offered donor type.

    An omitted locus is unknown, not negative. Treating it as a row of zeroes can
    turn an incompletely typed offer into an apparently low-burden offer.
    """
    required_loci = {
        locus
        for specs in _active_specs_by_basis(cohort, profile).values()
        for spec in specs
        if (locus := _locus(spec))
    }
    donor_loci = {locus for antigen in donor_hla if (locus := _locus(antigen))}
    missing = sorted(required_loci - donor_loci)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "offered donor HLA is missing typing at antibody locus/loci: "
                f"{', '.join(missing)}; omitted typing cannot be treated as negative"
            ),
        )


def _canonical_bdr(
    antigens: List[str],
    data,
    field: str,
    require_only_bdr: bool = False,
) -> tuple[List[str], Dict[str, str], Dict[str, set]]:
    """Canonicalise B/DR splits and require a usable two-locus mismatch type."""
    bdr_input = [
        antigen
        for antigen in antigens
        if antigen.startswith("DR") or (antigen.startswith("B") and not antigen.startswith("BW"))
    ]
    if require_only_bdr and len(bdr_input) != len(antigens):
        invalid = [antigen for antigen in antigens if antigen not in bdr_input]
        raise HTTPException(status_code=422, detail=f"{field} accepts HLA-B/DR only: {', '.join(invalid)}")

    canonical, conversions = canonicalise_recipient_hla(
        bdr_input,
        data.mantigens,
        data.broad_split.get("split_to_broad", {}),
    )
    try:
        validate_recipient_hla(canonical, data.mantigens)
    except AntigenValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field}: {', '.join(exc.invalid)}") from exc

    parsed = parse_recipient_bdr(canonical)
    missing = [locus for locus in ("B", "DR") if not parsed[locus]]
    excessive = [locus for locus in ("B", "DR") if len(parsed[locus]) > 2]
    if missing or excessive:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if excessive:
            details.append(f"more than two values at {', '.join(excessive)}")
        raise HTTPException(status_code=422, detail=f"{field} is not a usable B/DR type: {'; '.join(details)}")
    return canonical, conversions, parsed


def _frame_for(data, donor_set: str):
    """the donor frame for a named set

    The loader exposes (all, dp_typed) for the live set; selection re-derives the
    DP subset from the full frame, so the full frame is what is wanted here.
    """
    if donor_set == "donors_v3":
        return data.donors[0]
    raise HTTPException(
        status_code=400,
        detail=(
            f"donor set {donor_set!r} is not loaded for offer assessment; "
            "only donors_v3 carries DP typing and is the live set"
        ),
    )


def _build(request: ProfileRequest, data):
    """resolve a request into a cohort and profile, or fail with a clear reason"""
    profile = AntibodyProfile(
        specs=[SpecMFI(spec=s.spec, current=s.current, peak=s.peak) for s in request.specs],
        threshold=request.threshold,
    )
    frame = _frame_for(data, request.donor_set)
    spec_names = [s.spec for s in request.specs]

    unknown = [s for s in spec_names if s not in frame.columns]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"specificities not in the antigen vocabulary: {', '.join(unknown)}",
        )

    try:
        cohort = select(
            frame,
            recipient_bg=request.bg,
            specs=spec_names,
            donor_set=request.donor_set,
            abo_rule=request.abo_rule,
            dp_mode=request.dp_mode,
            organ=request.organ,
            tier=request.tier,
        )
    except ABOPolicyUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except CohortTooSmall as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return cohort, profile


def _notes(cohort, profile) -> List[str]:
    """caveats that must travel with the numbers rather than sit in documentation"""
    notes: List[str] = []
    provenance = cohort.provenance

    if provenance.dp_typed_only:
        notes.append(
            f"Assessed against the {provenance.cohort_size} DP-typed donors of "
            f"{provenance.donor_set}, not the full {provenance.set_size_before_dp}. "
            "This cannot be corroborated by the other donor sets."
        )
    if provenance.dp_specs_dropped:
        notes.append(
            f"DP mode 'exclude' discarded {len(provenance.dp_specs_dropped)} "
            f"specificities: {', '.join(provenance.dp_specs_dropped)}. "
            "The result is not comparable with a DP-included assessment."
        )
    if provenance.below_stats_floor:
        notes.append(
            f"Selected donor cohort of {provenance.cohort_size} is too small to characterise "
            "with percentiles; use the observed counts only."
        )
    if provenance.abo_rule is ABORule.IDENTICAL:
        notes.append(
            "Reference restricted to blood-group-identical donors because the "
            "offerable allocation-policy mapping is not yet encoded. Counts may "
            "understate the pool for a compatible non-identical offer."
        )
    if not profile.has_peak and profile.specs:
        notes.append("Peak MFI unavailable for at least one specificity; current basis only.")

    n_specs = len(_active_specs_by_basis(cohort, profile).get(MFIBasis.CURRENT.value, []))
    if not n_specs:
        notes.append("No current-MFI specificities remain above threshold after cohort policy was applied.")
    if n_specs == 1:
        notes.append(
            "A single specificity above threshold gives every incompatible donor "
            "the same burden. The ranking cannot discriminate; read the counts only."
        )
    elif n_specs and n_specs <= 3:
        notes.append(
            f"With {n_specs} specificities the distribution takes at most "
            f"{2**n_specs - 1} distinct values, so percentiles are coarse and "
            "many donors tie. Counts are the reliable reading."
        )
    return notes


def _response_meta(cohort, profile, data, notes: Optional[List[str]] = None) -> ResponseMeta:
    return ResponseMeta(
        provenance=cohort.provenance,
        data_provenance=data.provenance,
        threshold=profile.threshold,
        notes=notes if notes is not None else _notes(cohort, profile),
    )


@router.post("/parse")
@limiter.limit("60/minute", error_message="Too many requests, slow down!")
async def parse_paste(request: Request, body: ParseRequest, data=Depends(load_data)):
    """preview a pasted block before committing it

    Returns the detected delimiter, column roles, normalised rows and every
    problem found. Nothing is discarded silently -- unrecognised tokens come back
    with suggestions for the user to resolve.
    """
    result = parse(body.text, _vocabulary(data), roles=body.roles)
    return {
        "delimiter": result.delimiter,
        "header_detected": result.header_detected,
        "columns": result.columns,
        "roles": result.roles,
        "rows": result.rows,
        "problems": result.problems,
        "ok": result.ok,
        "recognised": len(result.recognised_rows),
        "total": len(result.rows),
    }


@router.post("/parse-donor")
@limiter.limit("60/minute", error_message="Too many requests, slow down!")
async def parse_donor(request: Request, body: DonorTypeRequest, data=Depends(load_data)):
    """normalise a pasted donor HLA type -- the same parser, second entry point"""
    found, problems = parse_donor_type(body.text, _vocabulary(data))
    return {"antigens": found, "problems": problems, "ok": not problems}


@router.post("/distribution")
@limiter.limit("30/minute", error_message="Too many requests, slow down!")
def distribution(request: Request, body: ProfileRequest, data=Depends(load_data)):
    """profile to burden distributions over the reference population

    Cacheable on the returned provenance plus threshold -- not on the profile
    alone, since the same profile under a different DP mode or ABO rule produces
    a different and non-comparable distribution.
    """
    cohort, profile = _build(body, data)

    distributions: Dict[str, dict] = {}
    notes = _notes(cohort, profile)
    for basis in profile.available_bases:
        dist = build_distribution(cohort, profile, basis)
        distributions[basis.value] = {
            "reference_size": dist.reference_size,
            "specs_used": dist.specs_used,
            "specs_below_threshold": dist.specs_below_threshold,
            "specs_excluded_by_cohort": dist.specs_excluded_by_cohort,
            "specs_not_in_cohort": dist.specs_not_in_cohort,
            "percentiles_suppressed": dist.percentiles_suppressed,
            "summary": {metric.value: _summarise(dist.values[metric]) for metric in Metric},
        }
        if dist.percentiles_suppressed:
            notes.append(
                f"{basis.value.title()} reference population has {dist.reference_size} incompatible donors; "
                "percentiles are suppressed and raw counts should be used."
            )

    return {
        "meta": _response_meta(cohort, profile, data, notes),
        "cohort_size": cohort.provenance.cohort_size,
        "distributions": distributions,
        "bases_available": [b.value for b in profile.available_bases],
    }


def _summarise(values: List[float]) -> dict:
    """quantiles and tie structure of one metric's distribution

    Distinct-value count is reported because it bounds what a percentile can
    mean: with few specificities the distribution takes few values and most
    donors tie.
    """
    if not values:
        return {"n": 0, "distinct": 0}
    n = len(values)
    ordered = sorted(values)

    def q(fraction: float) -> float:
        return ordered[min(n - 1, int(fraction * n))]

    return {
        "n": n,
        "distinct": len(set(ordered)),
        "min": ordered[0],
        "p25": q(0.25),
        "median": q(0.5),
        "p75": q(0.75),
        "max": ordered[-1],
    }


@router.post("/placement")
@limiter.limit("30/minute", error_message="Too many requests, slow down!")
def placement(request: Request, body: PlacementRequest, data=Depends(load_data)):
    """place an offered donor on the reference distributions

    The donor is scored by the same function that scores the cohort, so a
    difference in position can never come from a difference in scoring.
    """
    cohort, profile = _build(body, data)
    frame = _frame_for(data, body.donor_set)

    unknown = [ag for ag in body.donor_hla if ag not in frame.columns]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"donor antigens not in the vocabulary: {', '.join(unknown)}",
        )

    donor_bg = body.donor_bg or body.bg
    if donor_bg not in cohort.provenance.donor_bgs:
        raise HTTPException(
            status_code=422,
            detail=(
                f"offered donor blood group {donor_bg} is outside the selected "
                f"{cohort.provenance.abo_rule.value} reference ({', '.join(cohort.provenance.donor_bgs)}); "
                "the offer and reference population must use the same ABO rule"
            ),
        )
    _validate_donor_typing(cohort, profile, body.donor_hla)

    # represent the offered donor as a row in the cohort's own vocabulary
    donor = frame.iloc[0].copy()
    for column in frame.columns:
        if column not in ("id", "bg"):
            donor[column] = 0
    for antigen in body.donor_hla:
        donor[antigen] = 1
    donor["id"] = -1
    donor["bg"] = donor_bg

    result = assess_offer(cohort, profile, donor)
    notes = _notes(cohort, profile)

    summaries = result.basis_summaries
    for basis, summary in summaries.items():
        if summary.status is OfferStatus.COMPATIBLE:
            notes.append(
                f"No {basis} DSA was detected against the offered donor at this threshold; "
                "burden ranking is not applicable for that basis."
            )
        elif summary.status is OfferStatus.NO_ACTIVE_SPECIFICITIES:
            notes.append(f"No {basis} specificities remain active, so no burden distribution can be formed.")
        elif summary.status is OfferStatus.EMPTY_REFERENCE:
            notes.append(f"The {basis} incompatible reference population is empty; placement is unavailable.")

    reference_sizes = {summary.reference_size for summary in summaries.values()}
    if len(reference_sizes) > 1:
        notes.append(
            "Current and peak MFI activate different specificity sets and therefore use different "
            "incompatible reference populations. Compare each basis only with its own denominator."
        )

    # Mismatch level, where the recipient's B/DR type was supplied. Presented as
    # a joint view rather than a fifth distribution: it is a different kind of
    # quantity from burden and must not be read on the same axis.
    joint = None
    recip_hla_used = None
    recip_hla_conversions: Dict[str, str] = {}
    if body.recip_hla and result.offer_status is OfferStatus.RANKED:
        parsed_recipient, problems = parse_donor_type(body.recip_hla, _vocabulary(data))
        if problems:
            raise HTTPException(
                status_code=422,
                detail="invalid recipient HLA: " + "; ".join(problem.message for problem in problems),
            )
        recip_hla_used, recip_hla_conversions, recipient_bdr = _canonical_bdr(
            parsed_recipient,
            data,
            "recipient HLA",
            require_only_bdr=True,
        )
        donor_bdr_used, _, _ = _canonical_bdr(body.donor_hla, data, "offered donor HLA")
        mismatch_donor = donor.copy()
        for antigen in donor_bdr_used:
            mismatch_donor[antigen] = 1

        _, current_specs, _, _ = resolve_profile_mfi(cohort, profile, MFIBasis.CURRENT)
        reference = reference_population(cohort, current_specs)
        view = build_joint_view(
            cohort,
            profile,
            reference,
            recipient_bdr,
            data.mantigens,
            data.antigen_defaults,
            offered_donor=mismatch_donor,
        )
        joint = view.model_dump(mode="json")
        if view.n_better_on_both == 0 and view.reference_size:
            notes.append(
                "No reference donor was strictly lower on both current cumulative burden and "
                "mismatch level. Ties and trade-offs between the two axes may still remain."
            )

    return {
        "meta": _response_meta(cohort, profile, data, notes),
        "dsa_specs": result.dsa_specs,
        "dsa_count": result.dsa_count,
        "reference_size": result.reference_size,
        "identical_dsa_set_count": result.identical_dsa_set_count,
        "offer_status": result.offer_status,
        "basis_summaries": result.basis_summaries,
        "placements": result.placements,
        # primary view: the offer against every donor the patient could be
        # offered, compatible ones included at zero load
        "cohort_placements": result.cohort_placements,
        "bases_available": [b.value for b in result.bases_available],
        "peak_unavailable_reason": result.peak_unavailable_reason,
        "recip_hla_used": recip_hla_used,
        "recip_hla_conversions": recip_hla_conversions,
        "joint": joint,
    }


@router.get("/", response_class=HTMLResponse)
async def offer_page(request: Request):
    """the offer assessment page"""
    return templates.TemplateResponse(request, "offer.html")
