"""Turn a passport image into verified fields.

Pipeline: Tesseract reads the page -> we pick out the two MRZ lines -> repair
common OCR damage -> our parser corrects and verifies with check digits -> the
result says how much to trust it:

- verified:      every check digit passed
- needs_review:  MRZ read, but some check failed; the review form highlights those fields
- unreadable:    no usable MRZ (blurry, cropped, not a passport); the traveler types it in

The OCR step is a plain function passed in, so it can be swapped (a model trained
on the MRZ font, or a vision model as a fallback) without touching verification.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from io import BytesIO

import pytesseract
from PIL import Image

from .mrz import LINE_LENGTH, MrzFormatError, PassportMrz, parse_td3, repair_ocr_lines

logger = logging.getLogger(__name__)

MrzReader = Callable[[bytes], tuple[str, str] | None]

# Only MRZ characters, and no dictionary: MRZ text isn't words, and the English
# dictionary would "fix" it into them. --psm 6 reads the page as one block of text.
_TESSERACT_CONFIG = (
    "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< "
    "-c load_system_dawg=0 -c load_freq_dawg=0"
)
_LENGTH_SLACK = 4  # OCR adds or drops a few filler characters; repair fixes that later
# Each attempt is (rotation in degrees, scale). Tesseract doesn't straighten text,
# and is sensitive to letter size, so on real photos a read that fails one way often
# works another. Upright first, then upside down, then the tilts phone photos have.
_ATTEMPTS = [(angle, scale) for scale in (1.0, 1.5) for angle in (0, 180, 3, -3, 6, -6)]
_TIME_BUDGET_SECONDS = 6  # each attempt costs ~0.5-1 s; stay well inside the 10 s target


class ExtractionStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class Extraction:
    status: ExtractionStatus
    mrz: PassportMrz | None = None


def find_mrz_lines(text: str) -> tuple[str, str] | None:
    """Pick the MRZ out of whole-page OCR text: two consecutive lines of about
    44 characters, the first starting with 'P' and containing filler."""
    lines = [line.replace(" ", "") for line in text.splitlines()]
    lines = [line for line in lines if line]
    for first, second in zip(lines, lines[1:]):
        if (
            first.startswith("P")
            and "<" in first
            and abs(len(first) - LINE_LENGTH) <= _LENGTH_SLACK
            and abs(len(second) - LINE_LENGTH) <= _LENGTH_SLACK
        ):
            return first, second
    return None


def read_mrz_lines(image: bytes) -> tuple[str, str] | None:
    """OCR the page with Tesseract and return the two MRZ lines, if found.

    We try several rotations and scales (see _ATTEMPTS). The check digits tell us
    when a read is right, so we stop at the first one that passes them all; otherwise
    we return the first read that at least parses, for the traveler to review.
    """
    fallback = None
    deadline = time.monotonic() + _TIME_BUDGET_SECONDS
    try:
        page = Image.open(BytesIO(image)).convert("L")
        for angle, scale in _ATTEMPTS:
            if time.monotonic() > deadline:
                break
            attempt = page.rotate(angle, expand=True, fillcolor=255) if angle else page
            if scale != 1:
                attempt = attempt.resize((round(attempt.width * scale), round(attempt.height * scale)), Image.LANCZOS)
            lines = find_mrz_lines(pytesseract.image_to_string(attempt, config=_TESSERACT_CONFIG))
            if lines is None:
                continue
            try:
                mrz = parse_td3(*repair_ocr_lines(*lines))
            except MrzFormatError:
                continue
            if mrz.is_valid:
                return lines
            fallback = fallback or lines
    except Exception:
        # Any OCR failure (including Tesseract missing) becomes "type it in yourself", never a crash.
        logger.warning("MRZ OCR failed", exc_info=True)
    return fallback


def extract_passport(
    image: bytes, *, reader: MrzReader = read_mrz_lines, today: date | None = None
) -> Extraction:
    lines = reader(image)
    if lines is None:
        return Extraction(ExtractionStatus.UNREADABLE)
    try:
        mrz = parse_td3(*repair_ocr_lines(*lines), today=today)
    except MrzFormatError:
        return Extraction(ExtractionStatus.UNREADABLE)
    status = ExtractionStatus.VERIFIED if mrz.is_valid else ExtractionStatus.NEEDS_REVIEW
    return Extraction(status, mrz)
