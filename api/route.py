"""routes"""

import os
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .calculator import Calculator
from .data import load_data
from .ratelimiter import limiter

router = APIRouter()
templates = Jinja2Templates(directory="web")


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
    recip_hla_dict = defaultdict(set)
    for hla in recip_hla_list:
        recip_hla_dict["B" if hla.startswith("B") else "DR"].add(hla)
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
