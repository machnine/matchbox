"""Recipient HLA input handling for matchability calculations."""

from typing import Dict, List, Mapping, Sequence, Tuple


def canonicalise_recipient_hla(
    antigens: Sequence[str],
    matchability_antigens: Mapping[str, Sequence[str]],
    split_to_broad: Mapping[str, str],
) -> Tuple[List[str], Dict[str, str]]:
    """Convert recognised recipient B/DR splits to matchability broads.

    The matchability vocabulary is authoritative. Values already present in it
    must win over the generic broad/split mapping because it also contains rare
    canonical antigens (for example B42 and DR14) that the calculator handles
    separately through ``antigen_defaults``.

    This function deliberately does not validate otherwise unsupported input;
    stricter API vocabulary validation is a separate concern. It only resolves
    aliases where the mapped broad is valid for the same matchability locus.
    """

    allowed = {
        "B": set(matchability_antigens.get("B", [])),
        "DR": set(matchability_antigens.get("DR", [])),
    }
    canonical: List[str] = []
    conversions: Dict[str, str] = {}

    for raw_antigen in antigens:
        antigen = raw_antigen.strip().upper()
        locus = "DR" if antigen.startswith("DR") else "B" if antigen.startswith("B") else None
        resolved = antigen

        if locus and antigen not in allowed[locus]:
            broad = split_to_broad.get(antigen)
            if broad in allowed[locus]:
                resolved = broad
                conversions[antigen] = broad

        if resolved not in canonical:
            canonical.append(resolved)

    return canonical, conversions
