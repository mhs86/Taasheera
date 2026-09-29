from app.passport.extraction import ExtractionStatus, extract_passport, find_mrz_lines

SPECIMEN = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
)

# Shaped like real whole-page Tesseract output: visual-zone text squeezed into MRZ
# characters, then the MRZ with a filler misread and a letter O for a zero.
PAGE_TEXT = """UTOPIAPASSPORTPASSEPORT
SURNAMEERIKSSON
GIVENNAMESANNAMARIA

P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<K<KK<<<<<<<<
L8989O2C36UTO7408122F1204159ZE184226B<<<<<10
"""


def test_finds_the_mrz_lines_in_page_text():
    assert find_mrz_lines(PAGE_TEXT) == (
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<K<KK<<<<<<<<",
        "L8989O2C36UTO7408122F1204159ZE184226B<<<<<10",
    )


def test_ignores_text_without_an_mrz():
    assert find_mrz_lines("UTOPIAPASSPORT\nSURNAMEERIKSSON\n") is None


def test_ocr_damage_is_repaired_end_to_end():
    extraction = extract_passport(b"image", reader=lambda image: find_mrz_lines(PAGE_TEXT))

    assert extraction.status == ExtractionStatus.VERIFIED
    assert extraction.mrz.document_number == "L898902C3"
    assert extraction.mrz.corrected_fields == {"document_number"}


def test_missing_mrz_is_unreadable():
    assert extract_passport(b"image", reader=lambda image: None).status == ExtractionStatus.UNREADABLE


def test_mrz_that_cannot_be_parsed_is_unreadable():
    extraction = extract_passport(b"image", reader=lambda image: ("P<" + "X" * 60, SPECIMEN[1]))

    assert extraction.status == ExtractionStatus.UNREADABLE
