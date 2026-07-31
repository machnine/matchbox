"""routes"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .calculator import Calculator, parse_recipient_bdr
from .data import load_data
from .parser import parse_donor_type
from .ratelimiter import limiter

router = APIRouter()
templates = Jinja2Templates(directory="web")


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
        "tracking_id": tracking_id,
    }
    return templates.TemplateResponse("index.html", context)


@router.get("/crf-explainer", response_class=HTMLResponse)
async def crf_explainer(request: Request):
    """cRF explainer page"""
    return templates.TemplateResponse("crf-explainer.html", {"request": request})


@router.get("/calc/")
@limiter.limit("60/minute", error_message="Too many requests, slow down!")
async def calc(
    request: Request,
    bg: str = Query(..., max_length=2, pattern=r"^[ABO]$|^AB$", description="Blood group"),
    specs: Optional[str] = Query(None, pattern=r"^$|^([ABCD][QRPW]?[AB]?\d{1,4},?)+$", description="Recipient specs"),
    data=Depends(load_data, use_cache=True),
    donor_set: Optional[int] = Query(0, ge=0, le=1, description="Donor set [ALL=0, DPB=1]"),
    recip_hla: Optional[str] = Query(None, pattern=r"^$|^([ABCD][QRPW]?\d{1,3},?)+$", description="Recipient HLA-B/DR"),
):
    """calculate matchability"""
    donors = data.donors[donor_set]
    total = len(donors)
    recip_hla_list = recip_hla.split(",") if recip_hla else []
    # an empty mapping must stay falsy: Calculator skips matchability entirely
    # when no recipient type was supplied
    recip_hla_dict = parse_recipient_bdr(recip_hla_list) if recip_hla_list else {}
    specs = [] if not specs else specs.split(",")

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
    return {"bg": bg, "specs": specs, "results": results, "total": total, "recip_hla": recip_hla}


@router.get("/broad-split/")
async def broad_split(data=Depends(load_data)):
    """get broad/split antigen mappings"""
    return data.broad_split


@router.post("/normalise/")
@limiter.limit("60/minute", error_message="Too many requests, slow down!")
async def normalise(request: Request, body: NormaliseRequest, data=Depends(load_data)):
    """normalise a list of pasted antigens against the cohort vocabulary

    One normalisation for both pages. The rules (allele forms, C/CW, DP/DPB,
    leading zeros, HLA- prefixes) live in api/parser.py; without this the cRF
    page and the offer page would disagree about what a pasted token means.

    Unmatched tokens come back with suggestions rather than being discarded.
    """
    vocabulary = [ag for ags in data.antigens.values() for ag in ags]
    found, problems = parse_donor_type(body.text, vocabulary)
    return {"antigens": found, "problems": problems, "ok": not problems}
