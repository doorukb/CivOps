import re

# Illustrative safety keywords, not an official dispatch protocol
TRIPWIRE_PATTERNS = {
    "weapon": r"\b(?:gun|knife|firearm|pistol)\b",
    "injury": r"\b(?:bleeding|unconscious)\b",
    "medical": r"\b(?:not breathing|overdose)\b",
    "self_harm": r"\b(?:suicide|kill myself)\b",
}


def scan_transcript(transcript: str) -> dict[str, list[str]]:
    """
    Scan a transcript for potentially dangerous language.

    Returns matching terms grouped by category.
    A match requires human review; it does not determine dispatch.
    """

    flags = {}

    for category, pattern in TRIPWIRE_PATTERNS.items():
        matches = re.findall(
            pattern,
            transcript,
            flags=re.IGNORECASE
        )

        if matches:
            flags[category] = matches

    return flags