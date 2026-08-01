"""bulk paste ingest and antigen normalisation

Nobody will click forty specificities with two MFI values each. The data already
exists as an export from SAB analysis software, so the tool takes a paste and
works out what it is.

Column order is never prescribed -- every lab's export differs -- so roles are
detected by heuristic and offered back for confirmation rather than assumed.

Normalisation is forgiving on the specificity string but never silent: an
unmatched token surfaces as an explicit item with suggestions, never a quiet
discard. The vocabulary is fixed and small, which makes suggestion cheap.

The normalisation rules here match those already applied client-side in
static/scripts.js (DPB1*04:01 -> DPB4, C7 -> CW7, DP4 -> DPB4) so that the paste
box and the existing antigen input cannot disagree about what a token means.
"""

import re
from difflib import get_close_matches
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel

# Delimiters seen in real exports, in detection priority order. Tab first: an
# Excel paste is tab-delimited and may legitimately contain commas inside a
# specificity list within a cell.
DELIMITERS = [("\t", "tab"), (",", "comma"), (";", "semicolon"), ("|", "pipe")]

# These conditions alter or omit optional data but still leave a safe current-MFI
# profile that can be assessed. They remain visible to the user as warnings.
NON_BLOCKING_PROBLEM_KINDS = frozenset({"peak_below_current"})

# Header tokens that identify a column's role. Matched case-insensitively as
# substrings, longest first, so "peak mfi" beats "mfi".
ROLE_HINTS = {
    "peak_mfi": ["peak mfi", "peak_mfi", "peakmfi", "historic mfi", "highest mfi", "peak"],
    "current_mfi": ["current mfi", "current_mfi", "currentmfi", "latest mfi", "mfi", "value", "current"],
    "spec": ["specificity", "specificities", "antigen", "allele", "bead", "spec", "hla"],
}


class ColumnRole(str, Enum):
    """what a pasted column contains"""

    SPEC = "spec"
    CURRENT_MFI = "current_mfi"
    PEAK_MFI = "peak_mfi"
    IGNORE = "ignore"


class ParseProblem(BaseModel):
    """something the user must resolve before the paste can be committed"""

    kind: str
    row: Optional[int] = None
    token: Optional[str] = None
    message: str
    suggestions: List[str] = []


class ParsedRow(BaseModel):
    """one specificity from the paste, normalised"""

    raw_spec: str
    spec: Optional[str]
    current: Optional[float]
    peak: Optional[float]
    row: int
    recognised: bool


class ParseResult(BaseModel):
    """the outcome of a paste, for preview before commit"""

    delimiter: str
    header_detected: bool
    columns: List[str]
    roles: List[ColumnRole]
    rows: List[ParsedRow]
    problems: List[ParseProblem]

    @property
    def ok(self) -> bool:
        return not any(problem.kind not in NON_BLOCKING_PROBLEM_KINDS for problem in self.problems)

    @property
    def recognised_rows(self) -> List[ParsedRow]:
        return [r for r in self.rows if r.recognised]


def detect_delimiter(text: str) -> Tuple[str, str]:
    """pick the delimiter that splits lines most consistently

    Consistency, not raw count: a specificity column may contain commas, but the
    true delimiter is the one giving every line the same field count.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "\t", "tab"

    best = ("\t", "tab", -1.0)
    for delim, name in DELIMITERS:
        counts = [ln.count(delim) for ln in lines]
        if not any(counts):
            continue
        # reward a consistent, non-zero field count
        modal = max(set(counts), key=counts.count)
        if modal == 0:
            continue
        consistency = counts.count(modal) / len(counts)
        score = consistency * (1 + min(modal, 4) * 0.1)
        if score > best[2]:
            best = (delim, name, score)

    if best[2] < 0:
        # single column paste -- treat whitespace runs as the delimiter
        return None, "whitespace"
    return best[0], best[1]


def split_line(line: str, delimiter: Optional[str]) -> List[str]:
    if delimiter is None:
        return [f for f in re.split(r"[\s]+", line.strip()) if f]
    return [f.strip() for f in line.split(delimiter)]


def looks_like_number(value: str) -> bool:
    """whether a field parses as an MFI reading"""
    if not value:
        return False
    cleaned = value.replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def to_number(value: str) -> Optional[float]:
    if not looks_like_number(value):
        return None
    return float(value.replace(",", "").replace(" ", "").strip())


def detect_header(fields: Sequence[str]) -> bool:
    """a first line is a header if no field parses as a number

    An all-text first row in an MFI export is a header; a row with numbers is
    data, even if the specificity column is text.
    """
    return bool(fields) and not any(looks_like_number(f) for f in fields)


def role_from_header(header: str) -> Optional[ColumnRole]:
    """map a header string to a column role"""
    lowered = header.strip().lower()
    if not lowered:
        return None
    for role, hints in ROLE_HINTS.items():
        for hint in hints:
            if hint in lowered:
                return ColumnRole(role)
    return None


def infer_roles(
    header: Optional[Sequence[str]],
    sample_rows: Sequence[Sequence[str]],
    vocabulary: Sequence[str],
) -> List[ColumnRole]:
    """work out what each column holds

    Header names win where present. Otherwise: the column with the most tokens
    resolving against the vocabulary is the specificity column, and numeric
    columns become current then peak MFI in the order they appear -- current
    first because a single-MFI export is far more common than a peak-only one.
    """
    width = max((len(r) for r in sample_rows), default=0)
    if header:
        width = max(width, len(header))
    roles: List[Optional[ColumnRole]] = [None] * width

    if header:
        for i, name in enumerate(header[:width]):
            roles[i] = role_from_header(name)

    # score remaining columns
    numeric_cols: List[int] = []
    spec_scores: Dict[int, int] = {}
    for i in range(width):
        if roles[i] is not None:
            continue
        values = [r[i] for r in sample_rows if i < len(r) and r[i]]
        if not values:
            continue
        if all(looks_like_number(v) for v in values):
            numeric_cols.append(i)
        else:
            hits = sum(1 for v in values if normalise_spec(v, vocabulary)[0] is not None)
            spec_scores[i] = hits

    if ColumnRole.SPEC not in [r for r in roles if r] and spec_scores:
        best = max(spec_scores, key=lambda k: spec_scores[k])
        if spec_scores[best]:
            roles[best] = ColumnRole.SPEC

    assigned = {r for r in roles if r}
    for i in numeric_cols:
        if ColumnRole.CURRENT_MFI not in assigned:
            roles[i] = ColumnRole.CURRENT_MFI
            assigned.add(ColumnRole.CURRENT_MFI)
        elif ColumnRole.PEAK_MFI not in assigned:
            roles[i] = ColumnRole.PEAK_MFI
            assigned.add(ColumnRole.PEAK_MFI)

    return [r or ColumnRole.IGNORE for r in roles]


def normalise_spec(token: str, vocabulary: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    """normalise one specificity token against the cohort vocabulary

    Returns (matched, suggestions). A token that cannot be matched returns
    (None, suggestions) so the caller can surface it for the user to resolve.

    Handles, in order: whitespace and case; allele-level DPB1*04:01 and DPB1*0401
    to DPB4; bare C7 to CW7 and DP4 to DPB4 (matching the client-side rules);
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


def parse(
    text: str,
    vocabulary: Sequence[str],
    roles: Optional[Sequence[ColumnRole]] = None,
) -> ParseResult:
    """parse a pasted block into specificities with MFI values

    Roles may be supplied to override detection -- the UI offers a per-column
    dropdown and re-parses with the user's choice.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    problems: List[ParseProblem] = []

    if not lines:
        return ParseResult(
            delimiter="none",
            header_detected=False,
            columns=[],
            roles=[],
            rows=[],
            problems=[ParseProblem(kind="empty", message="nothing to parse")],
        )

    delimiter, delim_name = detect_delimiter(text)
    split = [split_line(ln, delimiter) for ln in lines]

    header_detected = detect_header(split[0]) if len(split) > 1 else False
    header = split[0] if header_detected else None
    data_rows = split[1:] if header_detected else split

    resolved_roles = list(roles) if roles else infer_roles(header, data_rows[:25], vocabulary)

    if ColumnRole.SPEC not in resolved_roles:
        problems.append(
            ParseProblem(
                kind="no_spec_column",
                message="could not identify which column holds the specificity; set it manually",
            )
        )
        return ParseResult(
            delimiter=delim_name,
            header_detected=header_detected,
            columns=list(header) if header else [],
            roles=resolved_roles,
            rows=[],
            problems=problems,
        )

    spec_idx = resolved_roles.index(ColumnRole.SPEC)
    cur_idx = resolved_roles.index(ColumnRole.CURRENT_MFI) if ColumnRole.CURRENT_MFI in resolved_roles else None
    peak_idx = resolved_roles.index(ColumnRole.PEAK_MFI) if ColumnRole.PEAK_MFI in resolved_roles else None

    if cur_idx is None:
        problems.append(
            ParseProblem(
                kind="no_current_mfi",
                message="no current MFI column identified; burden cannot be computed without it",
            )
        )

    rows: List[ParsedRow] = []
    seen: Dict[str, int] = {}

    for n, fields in enumerate(data_rows, start=1):
        if spec_idx >= len(fields):
            problems.append(
                ParseProblem(kind="short_row", row=n, message=f"row {n} has {len(fields)} fields, expected more")
            )
            continue

        raw = fields[spec_idx]
        if not raw.strip():
            continue

        spec, suggestions = normalise_spec(raw, vocabulary)
        current = to_number(fields[cur_idx]) if cur_idx is not None and cur_idx < len(fields) else None
        peak = to_number(fields[peak_idx]) if peak_idx is not None and peak_idx < len(fields) else None

        if spec is None:
            problems.append(
                ParseProblem(
                    kind="unrecognised_specificity",
                    row=n,
                    token=raw,
                    message=f"{raw!r} is not in the antigen vocabulary",
                    suggestions=suggestions,
                )
            )
        else:
            if spec in seen:
                problems.append(
                    ParseProblem(
                        kind="duplicate_specificity",
                        row=n,
                        token=spec,
                        message=f"{spec} appears on rows {seen[spec]} and {n}",
                    )
                )
            else:
                seen[spec] = n

            if cur_idx is not None and current is None:
                problems.append(
                    ParseProblem(
                        kind="missing_mfi",
                        row=n,
                        token=spec,
                        message=f"{spec} has no readable current MFI",
                    )
                )
            if current is not None and current < 0:
                problems.append(
                    ParseProblem(
                        kind="negative_mfi", row=n, token=spec, message=f"{spec} has a negative MFI ({current})"
                    )
                )
            if peak is not None and current is not None and peak < current:
                problems.append(
                    ParseProblem(
                        kind="peak_below_current",
                        row=n,
                        token=spec,
                        message=(
                            f"{spec} peak ({peak:.0f}) is below current ({current:.0f}); "
                            "that peak was treated as unavailable"
                        ),
                    )
                )
                peak = None

        rows.append(
            ParsedRow(
                raw_spec=raw,
                spec=spec,
                current=current,
                peak=peak,
                row=n,
                recognised=spec is not None,
            )
        )

    return ParseResult(
        delimiter=delim_name,
        header_detected=header_detected,
        columns=list(header) if header else [],
        roles=resolved_roles,
        rows=rows,
        problems=problems,
    )


def parse_donor_type(text: str, vocabulary: Sequence[str]) -> Tuple[List[str], List[ParseProblem]]:
    """parse a donor HLA type -- the same normalisation, one entry point per token

    Donor types carry no MFI, so this takes any delimiter and returns the
    recognised antigen list plus whatever could not be resolved.
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
