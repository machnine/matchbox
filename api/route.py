"""routes"""

import os
from collections import defaultdict
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .assets import asset_version
from .calculator import Calculator
from .data import load_data
from .input_validation import AntigenValidationError, validate_recipient_hla, validate_specificities
from .parser import parse_donor_type
from .ratelimiter import limiter
from .recipient import canonicalise_recipient_hla
from .schemas import CalculationResponse

router = APIRouter()
templates = Jinja2Templates(directory="web")
templates.env.globals["asset_version"] = asset_version

CALCULATION_CONTEXTS = {
    0: {
        "donor_cohort": "all_donors",
        "calculation_mode": "all_donors_reference",
    },
    1: {
        "donor_cohort": "dp_typed_only",
        "calculation_mode": "dp_typed_subset",
    },
}


class NormaliseRequest(BaseModel):
    """a block of pasted antigen tokens"""

    text: str


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, data=Depends(load_data)):
    """index page"""
    tracking_id = os.getenv("GOOGLE_ANALYTICS_TRACKING_ID")
    context = {
        "request": request,
        "antigens": data.antigens,
        "mantigens": data.mantigens,
        "mbands": data.mbands,
        "provenance": data.provenance,
        "tracking_id": tracking_id,
    }
    return templates.TemplateResponse("index.html", context)


@router.get("/crf-explainer", response_class=HTMLResponse)
async def crf_explainer(request: Request):
    """cRF explainer page"""
    return templates.TemplateResponse("crf-explainer.html", {"request": request})


@router.get("/calc/", response_model=CalculationResponse)
@limiter.limit("60/minute", error_message="Too many requests, slow down!")
async def calc(
    request: Request,
    bg: str = Query(..., max_length=2, pattern=r"^[ABO]$|^AB$", description="Blood group"),
    specs: Optional[str] = Query(None, pattern=r"^$|^([ABCD][QRPW]?[AB]?\d{1,4},?)+$", description="Recipient specs"),
    data=Depends(load_data, use_cache=True),
    donor_set: int = Query(0, ge=0, le=1, description="Donor set [ALL=0, DPB=1]"),
    recip_hla: Optional[str] = Query(None, pattern=r"^$|^([ABCD][QRPW]?\d{1,3},?)+$", description="Recipient HLA-B/DR"),
):
    """calculate matchability"""
    donors = data.donors[donor_set]
    total = len(donors)
    recip_hla_input = recip_hla.split(",") if recip_hla else []
    recip_hla_list, recip_hla_conversions = canonicalise_recipient_hla(
        recip_hla_input,
        data.mantigens,
        data.broad_split.get("split_to_broad", {}),
    )
    specs = [] if not specs else specs.split(",")
    try:
        validate_specificities(specs, data.antigens)
        validate_recipient_hla(recip_hla_list, data.mantigens)
    except AntigenValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail()) from exc

    recip_hla_dict = defaultdict(set)
    for hla in recip_hla_list:
        recip_hla_dict["B" if hla.startswith("B") else "DR"].add(hla)

    calculator = Calculator(
        donors=data.donors[donor_set],
        specs=specs,
        abo=bg,
        recipient_bdr=recip_hla_dict,
        hla_bdr=data.mantigens,
        ag_defaults=data.antigen_defaults,
        matchability_bands=data.mbands,
    )
    results = calculator.calculate()
    calculation_context = CALCULATION_CONTEXTS[donor_set]
    return {
        "bg": bg,
        "specs": specs,
        "results": results,
        "total": total,
        "donor_set": donor_set,
        **calculation_context,
        "calculated_at": datetime.now(UTC),
        "provenance": data.provenance,
        "recip_hla": recip_hla,
        "recip_hla_used": recip_hla_list or None,
        "recip_hla_conversions": recip_hla_conversions,
    }


@router.get("/broad-split/")
async def broad_split(data=Depends(load_data)):
    """get broad/split antigen mappings"""
    return data.broad_split


@router.post("/normalise/")
@limiter.limit("60/minute", error_message="Too many requests, slow down!")
async def normalise(request: Request, body: NormaliseRequest, data=Depends(load_data)):
    """normalise a list of pasted antigens against the cohort vocabulary

    The rules (allele forms, C/CW, DP/DPB, leading zeros, HLA- prefixes) live in
    api/parser.py and are applied server-side, so they are stated once and tested
    directly rather than duplicated as regexes in the browser.

    Unmatched tokens come back with suggestions rather than being discarded.
    """
    vocabulary = [ag for ags in data.antigens.values() for ag in ags]
    found, problems = parse_donor_type(body.text, vocabulary)
    return {"antigens": found, "problems": problems, "ok": not problems}
