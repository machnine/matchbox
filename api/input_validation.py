"""Clinical vocabulary validation for public calculator inputs."""

from typing import Dict, List, Mapping, Sequence


class AntigenValidationError(ValueError):
    """One API field contains antigens outside its supported vocabulary."""

    def __init__(self, field: str, invalid: Sequence[str]):
        self.field = field
        self.invalid = list(dict.fromkeys(invalid))
        values = ", ".join(repr(value) for value in self.invalid)
        super().__init__(f"unsupported {field} antigen value(s): {values}")

    def detail(self) -> Dict[str, object]:
        """JSON-safe FastAPI error detail."""
        return {"field": self.field, "invalid": self.invalid, "message": str(self)}


def validate_specificities(
    antigens: Sequence[str],
    antigen_vocabulary: Mapping[str, Sequence[str]],
) -> List[str]:
    """Require every antibody specificity to be exposed by the donor cohort."""
    allowed = {antigen for values in antigen_vocabulary.values() for antigen in values}
    invalid = [antigen for antigen in antigens if not antigen or antigen not in allowed]
    if invalid:
        raise AntigenValidationError("specs", invalid)
    return list(antigens)


def validate_recipient_hla(
    antigens: Sequence[str],
    matchability_antigens: Mapping[str, Sequence[str]],
) -> List[str]:
    """Require canonical recipient input to be valid broad B/DR matchability HLA."""
    allowed = {
        "B": set(matchability_antigens.get("B", [])),
        "DR": set(matchability_antigens.get("DR", [])),
    }
    invalid: List[str] = []

    for antigen in antigens:
        locus = "DR" if antigen.startswith("DR") else "B" if antigen.startswith("B") else None
        if locus is None or antigen not in allowed[locus]:
            invalid.append(antigen)

    if invalid:
        raise AntigenValidationError("recip_hla", invalid)
    return list(antigens)
