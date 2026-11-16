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
    "weapon": [
        "two guns", "kitchen knives", "he stabbed him", "shots fired",
        "I heard shots", "he got shot", "someone was shot", "he shot at the car",
        "she shot him",
        # added after the phrase-coverage audit
        "he has an axe", "there is a taser", "he is armed", "I heard gunfire",
        "there is a bomb", "he pulled a weapon", "he has a weapon",
        "she is waving a weapon", "he has a bat", "he has a hammer",
        "she grabbed a crowbar", "he is holding a baseball bat",
    ],
    "violence": [
        "he is attacking her", "being strangled", "punching him",
        "he punched me", "he punches the wall", "they beat up my son",
        "he was beaten up", "they beat him up",
        "he hit her", "he hits me", "she was raped", "it is domestic violence",
    ],
    "injury": [
        "there is blood", "she is unresponsive", "he collapsed",
        "his arm bleeds", "she could bleed out",
        "she was hit by a car", "he got hit by the truck",
    ],
    "medical": [
        "he can't breathe", "can’t breathe", "chest pain", "overdosed",
        "he stopped breathing", "she is barely breathing", "he isn't breathing",
        "he isn’t breathing", "she is no longer breathing",
        "he took too many pills", "she took too many tablets", "he is drowning",
    ],
    "self_harm": [
        "he is suicidal", "wants to die", "end my life",
        "he said he will kill himself", "she keeps hurting herself",
        "I want to hurt myself", "he wants to take his own life",
        "he is going to jump off the bridge", "she jumped off the roof",
        "he is hanging himself",
    ],
    "threat": [
        "I will kill him", "he is gonna hurt me", "threatening to shoot",
        "he said he will kill me", "he'll kill me", "He’ll kill us",
        "she is going to kill me", "he threatened her", "he threatens to come back",
        "someone is holding a hostage",
    ],
}


@pytest.mark.parametrize(
    "category, text",
    [(c, t) for c, texts in PHRASINGS.items() for t in texts],
)
def test_phrasing_flags_category(category, text):
    assert category in scan_transcript(text)


def test_flu_shot_does_not_flag():
    # Bare "shot" is not on the list. "shot at" is, so "flu shot at the
    # pharmacy" still flags: over-sensitive on purpose, a flag only asks for review.
    assert scan_transcript("She just got her flu shot yesterday.") == {}


def test_negation_is_not_understood():
    # Known limitation: matching is lexical, so denials still ask for review.
    assert "weapon" in scan_transcript("He does NOT have a gun.")
    assert "injury" in scan_transcript("Nobody is bleeding.")


def test_screening_question_words_do_not_flag():
    text = "Is anyone injured? Is there a weapon? Is anyone in danger or violent? Any threat? Hurt?"
    assert scan_transcript(text) == {}


@pytest.mark.parametrize(
    "question",
    [
        "Are there any weapons involved?",
        "Does he have a weapon?",
        "Is anyone there with a weapon?",
        "Has anyone been violent or threatened anyone?",
        "Is anyone injured or in immediate danger?",
    ],
)
def test_dispatcher_questions_do_not_flag(question):
    # The new "weapon" and "threatened" phrases need a verb or an object that
    # a screening question does not use.
    assert scan_transcript(question) == {}


@pytest.mark.parametrize(
    "denial",
    [
        "No, there are no weapons.",
        "No, nobody has been violent and nobody has threatened anyone.",
        "No, nobody is injured.",
        "No, nobody is in immediate danger.",
    ],
)
def test_plain_denials_that_echo_the_question_do_not_flag(denial):
    # Callers repeat the question's words when they answer. This is why the
    # bare words stay off the list even for caller lines: flagging them would
    # send every fully screened routine call to human review.
    assert scan_transcript(denial) == {}


def test_routine_scripted_call_stays_clean():
    from app.services.call_session import SCENARIOS

    for scenario_id in ("routine_wellbeing", "incomplete_screening"):
        text = "\n".join(
            f"{speaker.title()}: {line}" for speaker, line in SCENARIOS[scenario_id].lines
        )
        assert scan_transcript(text) == {}, scenario_id


@pytest.mark.parametrize(
    "benign",
    [
        "There is a bat in the attic and it keeps flying around.",
        "He is hammering on the wall at 6 AM again.",
        "The community responders are unarmed.",
        "He takes sleeping pills every night.",
        "They are draping a banner over the fence.",
        "Her kids were playing with grapes in the yard.",
    ],
)
def test_ordinary_sentences_do_not_flag(benign):
    assert scan_transcript(benign) == {}


@pytest.mark.parametrize(
    "over_sensitive, category",
    [
        # Known, accepted false positives: a flag only asks for a human look.
        ("My neighbor has a hammer going at 6 AM.", "weapon"),
        ("She got her flu shot at the pharmacy.", "weapon"),
        ("The kids like to jump off the porch steps.", "self_harm"),
        ("My car battery will kill the mood, it is dead again.", "threat"),
    ],
)
def test_documented_over_sensitivity(over_sensitive, category):
    assert category in scan_transcript(over_sensitive)


def test_no_flags():
    result = scan_transcript(
        "I'd like someone to check on my neighbor."
    )

    assert result == {}