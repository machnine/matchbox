"""antigen normalisation

Normalisation is forgiving on the specificity string but never silent: an
unmatched token surfaces as an explicit item with suggestions, never a quiet
discard. The vocabulary is fixed and small, which makes suggestion cheap.

Applied server-side so the rules (allele forms, C/CW, DP/DPB, leading zeros,
HLA- prefixes) are stated once and tested directly, rather than duplicated as
regexes in the browser.
"""

import re
from difflib import get_close_matches
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel


class ParseProblem(BaseModel):
    """a token that could not be resolved, with suggestions where there are any"""

    kind: str
    row: Optional[int] = None
    token: Optional[str] = None
    message: str
    suggestions: List[str] = []


def normalise_spec(token: str, vocabulary: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    """normalise one specificity token against the cohort vocabulary

    Returns (matched, suggestions). A token that cannot be matched returns
    (None, suggestions) so the caller can surface it for the user to resolve.

    Handles, in order: whitespace and case; allele-level DPB1*04:01 and DPB1*0401
    to DPB4; bare C7 to CW7 and DP4 to DPB4;
    Bw4/Bw6; and a trailing split-designation suffix.

    Allele-to-broad conversion beyond the DPB1* form is out of scope -- the
    vocabulary is broad/split and callers convert before submitting.
    """
    if token is None:
        return None, []
    text = token.strip().upper()
    if not text:
        return None, []

    vocab = set(vocabulary)

    # exact hit before any rewriting
    if text in vocab:
        return text, []

    candidates = [text]

    # strip a leading HLA- prefix
    stripped = re.sub(r"^HLA[-\s]*", "", text)
    if stripped != text:
        candidates.append(stripped)
    text = stripped

    # Allele form: LOCUS*FIELD1[:FIELD2] or the colonless LOCUS*FFSS.
    #
    # Allele fields are fixed-width two-digit groups, so 0401 is field 04 plus
    # field 01 -- not the number 401. Only the first field maps to a serological
    # specificity, and a bare 0*(\d+) cannot recover it from the colonless form.
    if match := re.match(r"^([A-Z]+\d*)\*(\d+)(?::\d+)*[A-Z]?$", text):
        locus, digits = match.group(1), match.group(2)
        # with a colon the first field is already isolated; without one, take the
        # leading two digits when the run is long enough to be two fields
        first_field = digits if ":" in text else (digits[:2] if len(digits) >= 4 else digits)
        locus = {
            "DPB1": "DPB",
            "DRB1": "DR",
            "DQB1": "DQ",
            "DQA1": "DQA",
            "C": "CW",  # donor columns use CW; exports and the mapping table use C
        }.get(locus, locus)
        candidates.append(f"{locus}{int(first_field)}")

    # DPB*04 or DPB04 -> DPB4
    if match := re.match(r"^DPB\*?0*(\d+)$", text):
        candidates.append(f"DPB{int(match.group(1))}")
    # DP4 -> DPB4
    if match := re.match(r"^DP0*(\d+)$", text):
        candidates.append(f"DPB{int(match.group(1))}")
    # C7 / CW07 -> CW7
    if match := re.match(r"^C[W]?0*(\d+)$", text):
        candidates.append(f"CW{int(match.group(1))}")
    # leading zeros anywhere: B07 -> B7
    if match := re.match(r"^([A-Z]+)0+(\d+)$", text):
        candidates.append(f"{match.group(1)}{int(match.group(2))}")

    for candidate in candidates:
        if candidate in vocab:
            return candidate, []

    suggestions = get_close_matches(text, vocabulary, n=4, cutoff=0.6)
    return None, suggestions


def parse_donor_type(text: str, vocabulary: Sequence[str]) -> Tuple[List[str], List[ParseProblem]]:
    """parse a list of pasted antigen tokens

    Accepts any of the delimiters a paste realistically arrives with, and returns
    the recognised antigens plus whatever could not be resolved. Duplicates are
    collapsed, preserving first-seen order.
    """
    tokens = [t for t in re.split(r"[\s,;|\t]+", text.strip()) if t]
    found: List[str] = []
    problems: List[ParseProblem] = []
    for n, token in enumerate(tokens, start=1):
        spec, suggestions = normalise_spec(token, vocabulary)
        if spec is None:
            problems.append(
                ParseProblem(
                    kind="unrecognised_specificity",
                    row=n,
                    token=token,
                    message=f"{token!r} is not in the antigen vocabulary",
                    suggestions=suggestions,
                )
            )
        elif spec not in found:
            found.append(spec)
    return found, problems
