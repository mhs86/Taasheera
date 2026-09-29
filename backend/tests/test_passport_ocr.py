"""End-to-end OCR on a synthetic specimen passport, using real PassportEye + Tesseract.

Skipped where Tesseract or a monospace font isn't installed (e.g. CI without OCR).
"""

import shutil
import time

import pytest

from app.passport.extraction import ExtractionStatus, extract_passport
from scripts.specimen_passport import FONT, synthetic_passport

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None or FONT is None, reason="needs Tesseract and a monospace font"
)


def test_reads_a_clear_passport_within_the_time_budget():
    extract_passport(synthetic_passport())  # warm-up: first call loads the OCR libraries

    started = time.perf_counter()
    extraction = extract_passport(synthetic_passport())
    elapsed = time.perf_counter() - started

    assert extraction.status == ExtractionStatus.VERIFIED
    assert extraction.mrz.surname == "ERIKSSON"
    assert extraction.mrz.nationality == "UTO"  # OCR reads "UT0"; position correction fixes it
    assert elapsed < 10


def test_blurry_passport_falls_back_to_manual_entry():
    extraction = extract_passport(synthetic_passport(blur=6))

    assert extraction.status == ExtractionStatus.UNREADABLE
