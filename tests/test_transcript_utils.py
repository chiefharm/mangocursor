from transcript_utils import normalize_spoken_numbers, transcript_paragraphs


def test_spoken_hour_with_zero_minutes() -> None:
    assert normalize_spoken_numbers("приходите в семнадцать ноль ноль") == (
        "приходите в 17:00"
    )


def test_spoken_compound_hour_with_zero_minutes() -> None:
    assert normalize_spoken_numbers("запись на двадцать один ноль ноль") == (
        "запись на 21:00"
    )


def test_transcript_paragraphs_remove_roles_and_normalize_time() -> None:
    transcript = [("Администратор", "приходите в семнадцать ноль ноль")]

    assert transcript_paragraphs(transcript) == ["приходите в 17:00"]
