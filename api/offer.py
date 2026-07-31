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

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .burden import (
    DEFAULT_DSA_THRESHOLD,
    AntibodyProfile,
    Metric,
    MFIBasis,
    SpecMFI,
    assess_offer,
    build_distribution,
    reference_population,
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
from .data import load_data
from .mismatch import build_joint_view, parse_recipient_bdr
from .parser import ColumnRole, parse, parse_donor_type
from .ratelimiter import limiter

router = APIRouter(prefix="/offer", tags=["offer assessment"])
templates = Jinja2Templates(directory="web")

# Bumped when a change alters any number a stored result could contain.
POLICY_VERSION = "2026-07-29.1"
VOCABULARY_VERSION = "donors_v3.broad-split"


class SpecInput(BaseModel):
    """one specificity as submitted"""

    spec: str
    current: float
    peak: Optional[float] = None


class ProfileRequest(BaseModel):
    """a patient profile and the selection toggles"""

    bg: str = Field(..., pattern=r"^(A|B|AB|O)$")
    specs: List[SpecInput]
    donor_set: str = "donors_v3"
    dp_mode: DPMode = DPMode.AUTO
    abo_rule: ABORule = ABORule.IDENTICAL
    organ: Optional[str] = None
    tier: Optional[Tier] = None
    threshold: float = DEFAULT_DSA_THRESHOLD


class PlacementRequest(ProfileRequest):
    """a profile plus the offered donor's HLA type"""

    donor_hla: List[str]
    donor_bg: Optional[str] = None
    recip_hla: Optional[str] = None  # B/DR broads, for the mismatch axis


class ParseRequest(BaseModel):
    """a pasted block awaiting preview"""

    text: str
    roles: Optional[List[ColumnRole]] = None


class DonorTypeRequest(BaseModel):
    text: str


class ResponseMeta(BaseModel):
    """what every response carries so it stays interpretable (§5.3)"""

    provenance: Provenance
    threshold: float
    policy_version: str = POLICY_VERSION
    vocabulary_version: str = VOCABULARY_VERSION
    notes: List[str] = []


def _vocabulary(data) -> List[str]:
    return [ag for ags in data.antigens.values() for ag in ags]


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
            f"Reference population of {provenance.cohort_size} is too small to "
            "characterise; counts are reported without percentiles."
        )
    if provenance.abo_rule is ABORule.IDENTICAL:
        notes.append(
            "Blood-group-identical donors only. Under allocation policy this "
            "recipient may be offered compatible non-identical donors, so the "
            "counts here understate the pool."
        )
    if not profile.has_peak and profile.specs:
        notes.append("Peak MFI unavailable for at least one specificity; current basis only.")

    n_specs = len(profile.series_for(MFIBasis.CURRENT))
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
async def distribution(request: Request, body: ProfileRequest, data=Depends(load_data)):
    """profile to burden distributions over the reference population

    Cacheable on the returned provenance plus threshold -- not on the profile
    alone, since the same profile under a different DP mode or ABO rule produces
    a different and non-comparable distribution.
    """
    cohort, profile = _build(body, data)

    distributions: Dict[str, dict] = {}
    for basis in profile.available_bases:
        dist = build_distribution(cohort, profile, basis)
        distributions[basis.value] = {
            "reference_size": dist.reference_size,
            "specs_used": dist.specs_used,
            "specs_below_threshold": dist.specs_below_threshold,
            "specs_not_in_cohort": dist.specs_not_in_cohort,
            "percentiles_suppressed": dist.percentiles_suppressed,
            "summary": {metric.value: _summarise(dist.values[metric]) for metric in Metric},
        }

    return {
        "meta": ResponseMeta(
            provenance=cohort.provenance,
            threshold=profile.threshold,
            notes=_notes(cohort, profile),
        ),
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
async def placement(request: Request, body: PlacementRequest, data=Depends(load_data)):
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

    # represent the offered donor as a row in the cohort's own vocabulary
    donor = frame.iloc[0].copy()
    for column in frame.columns:
        if column not in ("id", "bg"):
            donor[column] = 0
    for antigen in body.donor_hla:
        donor[antigen] = 1
    donor["id"] = -1
    donor["bg"] = body.donor_bg or body.bg

    result = assess_offer(cohort, profile, donor)
    notes = _notes(cohort, profile)

    if body.donor_bg and body.donor_bg != body.bg:
        notes.append(
            f"The offered donor is blood group {body.donor_bg} against a "
            f"{body.bg} recipient, but the reference set is "
            f"{cohort.provenance.abo_rule.value}. The offer's ABO relationship "
            "and the reference set's must match for the comparison to hold."
        )

    # Mismatch level, where the recipient's B/DR type was supplied. Presented as
    # a joint view rather than a fifth distribution: it is a different kind of
    # quantity from burden and must not be read on the same axis.
    joint = None
    if body.recip_hla:
        recipient_bdr = parse_recipient_bdr([ag.strip().upper() for ag in body.recip_hla.replace(",", " ").split()])
        reference = reference_population(cohort, cohort.specs)
        view = build_joint_view(
            cohort,
            profile,
            reference,
            recipient_bdr,
            data.mantigens,
            data.antigen_defaults,
            offered_donor=donor,
        )
        joint = view.model_dump(mode="json")
        if view.n_better_on_both == 0 and view.reference_size:
            notes.append(
                "No donor in the reference population is better on both burden and "
                "mismatch level. On these two axes together this offer is the best "
                "available in the cohort as it stands."
            )

    return {
        "meta": ResponseMeta(
            provenance=cohort.provenance,
            threshold=profile.threshold,
            notes=notes,
        ),
        "dsa_specs": result.dsa_specs,
        "dsa_count": result.dsa_count,
        "reference_size": result.reference_size,
        "identical_dsa_set_count": result.identical_dsa_set_count,
        "placements": result.placements,
        "bases_available": [b.value for b in result.bases_available],
        "peak_unavailable_reason": result.peak_unavailable_reason,
        "joint": joint,
    }


@router.get("/", response_class=HTMLResponse)
async def offer_page(request: Request):
    """the offer assessment page"""
    return templates.TemplateResponse("offer.html", {"request": request})
