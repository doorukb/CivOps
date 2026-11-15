import pytest

from app.services.tripwires import scan_transcript


def test_weapon_detected():
    result = scan_transcript(
        "My neighbor is holding a knife."
    )

    assert "weapon" in result
    assert "knife" in result["weapon"]


def test_multiple_categories():
    result = scan_transcript(
        "Someone has a gun and another person is bleeding."
    )

    assert "weapon" in result
    assert "injury" in result


def test_case_insensitive():
    result = scan_transcript(
        "HE HAS A KNIFE!"
    )

    assert "weapon" in result


def test_no_false_substring_match():
    result = scan_transcript(
        "I've begun cleaning the house."
    )

    assert "weapon" not in result


PHRASINGS = {
    "weapon": ["two guns", "kitchen knives", "he stabbed him", "shots fired"],
    "violence": ["he is attacking her", "being strangled", "punching him"],
    "injury": ["there is blood", "she is unresponsive", "he collapsed"],
    "medical": ["he can't breathe", "can’t breathe", "chest pain", "overdosed"],
    "self_harm": ["he is suicidal", "wants to die", "end my life"],
    "threat": ["I will kill him", "he is gonna hurt me", "threatening to shoot"],
}


@pytest.mark.parametrize(
    "category, text",
    [(c, t) for c, texts in PHRASINGS.items() for t in texts],
)
def test_phrasing_flags_category(category, text):
    assert category in scan_transcript(text)


def test_negation_is_not_understood():
    # Known limitation: matching is lexical, so denials still ask for review.
    assert "weapon" in scan_transcript("He does NOT have a gun.")
    assert "injury" in scan_transcript("Nobody is bleeding.")


def test_screening_question_words_do_not_flag():
    text = "Is anyone injured? Is there a weapon? Is anyone in danger or violent? Any threat? Hurt?"
    assert scan_transcript(text) == {}


def test_no_flags():
    result = scan_transcript(
        "I'd like someone to check on my neighbor."
    )

    assert result == {}