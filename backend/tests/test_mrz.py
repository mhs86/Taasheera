from datetime import date

import pytest

from app.passport.mrz import MrzFormatError, check_digit, parse_td3


# ICAO 9303 specimen passport ("Utopia"). Never use real passport data in tests.
SPECIMEN_LINE1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
SPECIMEN_LINE2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
TODAY = date(2026, 9, 29)


def with_char(line: str, index: int, char: str) -> str:
    return line[:index] + char + line[index + 1:]


def test_specimen_lines_are_44_characters():
    assert len(SPECIMEN_LINE1) == 44
    assert len(SPECIMEN_LINE2) == 44


@pytest.mark.parametrize(
    ("value", "expected"),
    [("L898902C3", 6), ("740812", 2), ("120415", 9), ("ZE184226B<<<<<", 1), ("<<<<<<", 0)],
)
def test_check_digit_matches_icao_specimen(value, expected):
    assert check_digit(value) == expected


def test_parses_every_field_of_the_specimen():
    mrz = parse_td3(SPECIMEN_LINE1, SPECIMEN_LINE2, today=TODAY)

    assert mrz.document_type == "P"
    assert mrz.issuing_country == "UTO"
    assert mrz.surname == "ERIKSSON"
    assert mrz.given_names == "ANNA MARIA"
    assert mrz.document_number == "L898902C3"
    assert mrz.nationality == "UTO"
    assert mrz.birth_date == date(1974, 8, 12)
    assert mrz.sex == "F"
    assert mrz.expiry_date == date(2012, 4, 15)
    assert mrz.personal_number == "ZE184226B"
    assert mrz.is_valid
    assert mrz.suspect_fields == set()


def test_misread_document_number_is_flagged_not_rejected():
    # OCR confusing "8" with "B" is a typical error. The check digit catches it.
    line2 = with_char(SPECIMEN_LINE2, 2, "B")

    mrz = parse_td3(SPECIMEN_LINE1, line2, today=TODAY)

    assert mrz.document_number == "L8B8902C3"
    assert not mrz.is_valid
    assert mrz.checks["document_number"] is False
    assert mrz.checks["composite"] is False
    assert mrz.checks["birth_date"] is True
    assert mrz.suspect_fields == {"document_number"}


def test_impossible_date_is_suspect():
    # Month 13 with a check digit that still matches, so only the date itself is wrong.
    birth = "741312"
    line2 = SPECIMEN_LINE2[:13] + birth + str(check_digit(birth)) + SPECIMEN_LINE2[20:]

    mrz = parse_td3(SPECIMEN_LINE1, line2, today=TODAY)

    assert mrz.birth_date is None
    assert "birth_date" in mrz.suspect_fields


def test_birth_year_century_is_inferred_from_today():
    birth = "050101"
    line2 = SPECIMEN_LINE2[:13] + birth + str(check_digit(birth)) + SPECIMEN_LINE2[20:]

    assert parse_td3(SPECIMEN_LINE1, line2, today=TODAY).birth_date == date(2005, 1, 1)
    assert parse_td3(SPECIMEN_LINE1, line2, today=date(2004, 1, 1)).birth_date == date(1905, 1, 1)


def test_unspecified_sex_and_missing_given_names():
    line1 = "P<UTOMONONYM" + "<" * 32
    line2 = with_char(SPECIMEN_LINE2, 20, "<")

    mrz = parse_td3(line1, line2, today=TODAY)

    assert mrz.surname == "MONONYM"
    assert mrz.given_names == ""
    assert mrz.sex == "X"


def test_unused_personal_number_accepts_filler_check_digit():
    body = SPECIMEN_LINE2[:28] + "<" * 14 + "<"
    line2 = body + str(check_digit(body[0:10] + body[13:20] + body[21:43]))

    mrz = parse_td3(SPECIMEN_LINE1, line2, today=TODAY)

    assert mrz.personal_number == ""
    assert mrz.is_valid


def test_accepts_lowercase_and_surrounding_whitespace():
    mrz = parse_td3(f"  {SPECIMEN_LINE1.lower()} ", f"{SPECIMEN_LINE2}\n", today=TODAY)

    assert mrz.is_valid


@pytest.mark.parametrize(
    ("line1", "line2", "message"),
    [
        (SPECIMEN_LINE1[:-1], SPECIMEN_LINE2, "Line 1 has 43 characters"),
        (SPECIMEN_LINE1, SPECIMEN_LINE2 + "<", "Line 2 has 45 characters"),
        (with_char(SPECIMEN_LINE1, 7, "!"), SPECIMEN_LINE2, "characters that can't appear"),
        (with_char(SPECIMEN_LINE1, 0, "I"), SPECIMEN_LINE2, "Not a passport"),
    ],
)
def test_rejects_text_that_is_not_a_passport_mrz(line1, line2, message):
    with pytest.raises(MrzFormatError, match=message):
        parse_td3(line1, line2, today=TODAY)
