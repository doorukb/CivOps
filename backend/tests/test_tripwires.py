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


def test_no_flags():
    result = scan_transcript(
        "I'd like someone to check on my neighbor."
    )

    assert result == {}