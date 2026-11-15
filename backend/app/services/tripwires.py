import re

# Illustrative safety keywords, not an official dispatch protocol.
#
# Matching is purely lexical and ignores negation: "he does NOT have a gun" and
# "nobody is bleeding" still flag. That is intended (a flag only asks for human
# review). Do NOT add bare "weapon", "violent", "threat", "hurt", "injured" or
# "danger": the dispatcher's screening questions contain them and would flag
# every call.
_APOS = "['’]"  # straight or curly apostrophe (speech-to-text emits both)

TRIPWIRE_PATTERNS = {
    "weapon": (
        r"\b(?:guns?|handguns?|pistols?|rifles?|shotguns?|firearms?|knife|knives"
        r"|machetes?|gunshots?|shots fired|shooting|stab(?:s|bed|bing)?|blades?)\b"
    ),
    "violence": (
        r"\b(?:attack(?:s|ed|ing)?|assault(?:s|ed|ing)?|strangl(?:e|es|ed|ing)"
        r"|chok(?:e|es|ed|ing)|beating|punching|hitting)\b"
    ),
    "injury": r"\b(?:bleeding|blood|unconscious|unresponsive|collapsed)\b",
    "medical": (
        r"\b(?:seizures?|not breathing|can" + _APOS + r"t breathe"
        r"|overdos(?:e|es|ed|ing)|chest pain)\b"
    ),
    "self_harm": r"\b(?:suicide|suicidal|kill myself|wants? to die|end my life)\b",
    "threat": (
        r"\b(?:kill (?:him|her|them|you)"
        r"|(?:going to|gonna|threatening to) (?:hurt|kill|shoot|stab))\b"
    ),
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
