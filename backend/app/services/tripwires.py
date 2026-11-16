"""Keyword tripwire on the raw transcript.

This runs before anything the model extracted is looked at, and nothing in the
model path can clear a flag. A flag never chooses a destination: it only sends
the call to a human dispatcher.

Illustrative safety keywords, not an official dispatch protocol.

Design notes (each has a test in tests/test_tripwires.py):

* Matching is purely lexical and ignores negation: "he does NOT have a gun"
  and "nobody is bleeding" still flag. That is intended. Over-sensitivity costs
  a human look; a miss costs far more.
* Do NOT add bare "weapon", "violent", "threat", "hurt", "injured" or
  "danger". The dispatcher's own screening questions contain them, and callers
  repeat them in plain denials ("No, there are no weapons"), so they would flag
  every fully screened routine call. For the same reason this scan does not
  treat caller lines differently from dispatcher lines. Those words are matched
  only inside a phrase that a question or a denial does not use ("pulled a
  weapon", "threatened her").
* Bare "shot", "pills", "bat" and "hammer" stay out: "flu shot", "sleeping
  pills", "a bat in the attic" and "hammering at 6 AM" are ordinary calls.
  They flag inside a telling phrase ("was shot", "took too many pills",
  "he has a bat").
"""

import re

_APOS = "['\u2019]"  # straight or curly apostrophe (speech-to-text emits both)
_PERSON = r"(?:him|her|them|me|us|you)"
_SELF = r"(?:myself|himself|herself|themselves)"
_BLUNT = r"(?:baseball bat|bat|hammer|crowbar|tire iron|pipe|brick)"

TRIPWIRE_PATTERNS = {
    "weapon": (
        r"\b(?:guns?|handguns?|pistols?|rifles?|shotguns?|firearms?|knife|knives"
        r"|machetes?|gunshots?|gunfire|shots fired|shots|shooting"
        r"|stab(?:s|bed|bing)?|blades?|axes?|tasers?|armed|bombs?|explosives?"
        # "shot" only in a shooting sense, so a "flu shot" stays unflagged
        r"|(?:got|been|was|is|were) shot|shot (?:him|her|them|me|at)"
        # "weapon" only with a verb that a screening question does not use
        r"|(?:has|had|holding|pulled|pulled out|drew|pointed|pointing|waving"
        r"|brandishing) (?:a|the|his|her) weapon"
        # blunt objects only when someone is said to have one
        r"|(?:has|have|had|holding|grabbed|carrying) (?:a|an|the|his|her) "
        + _BLUNT
        + r")\b"
    ),
    "violence": (
        r"\b(?:attack(?:s|ed|ing)?|assault(?:s|ed|ing)?|strangl(?:e|es|ed|ing)"
        r"|chok(?:e|es|ed|ing)|beating|punch(?:ed|es|ing)?|hitting"
        r"|hit(?:s)? " + _PERSON +
        r"|beat up|beaten up|beat (?:him|her|them|me) up"
        r"|rap(?:e|ed|es|ing)|domestic violence)\b"
    ),
    "injury": (
        r"\b(?:bleed(?:s|ing)?(?: out)?|blood|unconscious|unresponsive|collapsed"
        r"|hit by (?:a|the) (?:car|truck|bus|vehicle))\b"
    ),
    "medical": (
        r"\b(?:seizures?|not breathing|can" + _APOS + r"t breathe"
        r"|(?:stopped|isn" + _APOS + r"t|barely|no longer) breathing"
        r"|overdos(?:e|es|ed|ing)|took too many (?:pills|tablets)"
        r"|chest pain|drown(?:s|ed|ing)?)\b"
    ),
    "self_harm": (
        r"\b(?:suicide|suicidal|wants? to die|end my life"
        r"|kill " + _SELF +
        r"|hurt(?:ing)? " + _SELF +
        r"|hang(?:ed|ing)? " + _SELF +
        r"|jump(?:s|ed|ing)? off"
        r"|take (?:my|his|her|their) own life)\b"
    ),
    "threat": (
        r"\b(?:kill " + _PERSON +
        r"|(?:will|" + _APOS + r"ll) kill"
        r"|(?:going to|gonna|threatening to) (?:hurt|kill|shoot|stab)"
        # "threatened anyone" (the screening question, and its denial) is not matched
        r"|threaten(?:s|ed|ing) (?:to\b|him|her|them|me|us)"
        r"|hostages?)\b"
    ),
}

_COMPILED = {
    category: re.compile(pattern, re.IGNORECASE)
    for category, pattern in TRIPWIRE_PATTERNS.items()
}


def scan_transcript(transcript: str) -> dict[str, list[str]]:
    """
    Scan a transcript for potentially dangerous language.

    Returns matching terms grouped by category.
    A match requires human review; it does not determine dispatch.
    """

    flags = {}

    for category, pattern in _COMPILED.items():
        matches = pattern.findall(transcript)

        if matches:
            flags[category] = matches

    return flags
