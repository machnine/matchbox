"""Public API response contracts."""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from .calculator import Results
from .data import DataProvenance


class CalculationResponse(BaseModel):
    """Additive response contract for calculator results and their provenance."""

    bg: str
    specs: List[str]
    results: Results
    total: int
    donor_set: Literal[0, 1]
    donor_cohort: Literal["all_donors", "dp_typed_only"]
    calculation_mode: Literal["all_donors_reference", "dp_typed_subset"]
    calculated_at: datetime
    provenance: DataProvenance
    recip_hla: Optional[str]
    recip_hla_used: Optional[List[str]]
    recip_hla_conversions: Dict[str, str]
