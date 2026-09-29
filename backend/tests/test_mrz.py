from datetime import date

import pytest

from app.passport.mrz import MrzFormatError, check_digit, parse_td3, repair_ocr_lines


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


def test_corrects_ocr_lookalikes_by_position():
    # Real OCR output on a synthetic specimen: nationality "UTO" read as "UT0".
    # Nationality has no check digit, so only position-based correction can fix it.
    line2 = with_char(SPECIMEN_LINE2, 12, "0")
    # A letter O inside the birth date, and the digit 1 in place of the I in ERIKSSON.
    line2 = with_char(line2, 15, "O")
    line1 = with_char(SPECIMEN_LINE1, 7, "1")

    mrz = parse_td3(line1, line2, today=TODAY)

    assert mrz.nationality == "UTO"
    assert mrz.birth_date == date(1974, 8, 12)
    assert mrz.surname == "ERIKSSON"
    assert mrz.is_valid


def test_check_digit_picks_between_lookalikes_in_document_number():
    # Letter O and zero are both legal in a document number, so position can't decide.
    # Only the single swap O -> 0 passes the check digits (seen on a real passport scan).
    line2 = with_char(SPECIMEN_LINE2, 5, "O")

    mrz = parse_td3(SPECIMEN_LINE1, line2, today=TODAY)

    assert mrz.document_number == "L898902C3"
    assert mrz.corrected_fields == {"document_number"}
    assert mrz.is_valid


def test_does_not_invent_a_value_when_the_truth_is_out_of_reach():
    # "L" misread as "0": L isn't a look-alike we swap. Trying many swaps once produced
    # a wrong value that passed both checks by luck; single swaps must leave it flagged.
    line2 = with_char(SPECIMEN_LINE2, 0, "0")

    mrz = parse_td3(SPECIMEN_LINE1, line2, today=TODAY)

    assert mrz.document_number == "0898902C3"
    assert mrz.corrected_fields == set()
    assert "document_number" in mrz.suspect_fields


def test_repair_turns_k_filler_back_into_filler_and_fixes_length():
    # Tesseract reads runs of '<' as 'K' and miscounts them (seen on a real passport scan).
    ocr_line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<K<KK<<KK<KKK<K<<"
    ocr_line2 = SPECIMEN_LINE2[:37] + "<K<<<" + SPECIMEN_LINE2[42:]

    line1, line2 = repair_ocr_lines(ocr_line1, ocr_line2)

    assert (line1, line2) == (SPECIMEN_LINE1, SPECIMEN_LINE2)


def test_repair_keeps_a_name_that_ends_in_k():
    line1, _ = repair_ocr_lines("P<UTOMALIK<<ERIK" + "<" * 25 + "K", SPECIMEN_LINE2)

    assert line1 == "P<UTOMALIK<<ERIK" + "<" * 28


def test_repair_pads_a_short_line_one():
    line1, _ = repair_ocr_lines(SPECIMEN_LINE1[:40], SPECIMEN_LINE2)

    assert line1 == SPECIMEN_LINE1


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
