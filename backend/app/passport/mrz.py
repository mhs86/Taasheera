"""Parse and verify the machine-readable zone (MRZ) of a passport.

Passports use the ICAO 9303 "TD3" format: two lines of 44 characters.

    Line 1: P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<
            | |  |
            | |  +-- names: SURNAME<<GIVEN<NAMES, padded with '<'   [5:44]
            | +----- issuing state (3 letters)                     [2:5]
            +------- document type 'P' + optional subtype          [0:2]

    Line 2: L898902C36UTO7408122F1204159ZE184226B<<<<<10
            document number [0:9] + check [9]
            nationality     [10:13]
            birth date      [13:19] YYMMDD + check [19]
            sex             [20]
            expiry date     [21:27] YYMMDD + check [27]
            personal number [28:42] + check [42]
            composite check [43] over [0:10] + [13:20] + [21:43]

Check digits let us verify an OCR read instead of trusting it. Names, sex and
country codes have no check digit, so the review step always shows them.

OCR often confuses look-alike characters (O/0, I/1, B/8). We undo that in layers:
1. By position: the format fixes which positions hold letters and which hold digits.
2. By check digit: in alphanumeric fields (document and personal number) where
   both are legal, we try swapping one look-alike and keep the result only if it's
   the single swap that passes both its own check digit and the composite check.
3. `repair_ocr_lines` handles damage that changes line length (see its docstring).
"""

import re
from dataclasses import dataclass, field
from datetime import date

LINE_LENGTH = 44
_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<")
_WEIGHTS = (7, 3, 1)

_AS_DIGIT = str.maketrans("OQDILZSGB", "000112568")
_AS_LETTER = str.maketrans("012568", "OIZSGB")

# Positions that the format restricts to digits or to letters.
# Document number and personal number are alphanumeric, so they're left alone.
_LINE1_LETTERS = range(2, LINE_LENGTH)  # issuing state and names
_LINE2_DIGITS = (*range(13, 20), *range(21, 28), 9, 43)  # dates and their checks, doc/composite checks
_LINE2_LETTERS = (*range(10, 13), 20)  # nationality and sex

# One likely alternative per character, for check-digit-guided repair. Only pairs
# the check digit can tell apart: it works mod 10, and G (16) counts the same as 6,
# K (20) the same as '<' (0), so swapping those could never be verified.
_LOOKALIKES = {"O": "0", "0": "O", "I": "1", "1": "I", "B": "8", "8": "B",
               "S": "5", "5": "S", "Z": "2", "2": "Z"}
_REPAIRABLE_FIELDS = (("document_number", 0, 9), ("personal_number", 28, 42))  # check digit right after


class MrzFormatError(ValueError):
    """The text is not a structurally valid passport (TD3) MRZ."""


def check_digit(value: str) -> int:
    """ICAO 9303 check digit: weighted sum (7, 3, 1, ...) of character values, mod 10.

    Digits count as themselves, A-Z as 10-35, and the filler '<' as 0.
    """
    total = 0
    for index, char in enumerate(value):
        if char.isdigit():
            number = int(char)
        elif char == "<":
            number = 0
        else:
            number = ord(char) - ord("A") + 10
        total += number * _WEIGHTS[index % 3]
    return total % 10


def _check_passes(value: str, digit: str) -> bool:
    return digit.isdigit() and check_digit(value) == int(digit)


def _parse_date(yymmdd: str, *, is_expiry: bool, today: date) -> date | None:
    """Expand a YYMMDD date. The MRZ has no century, so we infer it.

    Expiry dates are assumed to be in the 2000s. A birth date whose two-digit year
    is later than this year's must be from the 1900s.
    """
    if not yymmdd.isdigit():
        return None
    yy, month, day = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    century = 2000 if is_expiry or yy <= today.year % 100 else 1900
    try:
        return date(century + yy, month, day)
    except ValueError:
        return None


def _correct_positions(line: str, *, digits=(), letters=()) -> str:
    chars = list(line)
    for index in digits:
        chars[index] = chars[index].translate(_AS_DIGIT)
    for index in letters:
        chars[index] = chars[index].translate(_AS_LETTER)
    return "".join(chars)


def _composite_passes(line2: str) -> bool:
    return _check_passes(line2[0:10] + line2[13:20] + line2[21:43], line2[43])


def _repair_by_check_digit(line2: str, start: int, end: int) -> str | None:
    """Return line 2 with one look-alike in [start:end] swapped, if exactly one such swap verifies.

    Only single swaps: every extra variant is another 1-in-10 chance that a wrong
    value passes the check digit by luck. Two misreads in one field go to review instead.
    """
    matches = []
    for index in range(start, end):
        if line2[index] not in _LOOKALIKES:
            continue
        candidate = line2[:index] + _LOOKALIKES[line2[index]] + line2[index + 1:]
        if _check_passes(candidate[start:end], candidate[end]) and _composite_passes(candidate):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def repair_ocr_lines(line1: str, line2: str) -> tuple[str, str]:
    """Undo OCR damage that would otherwise make the lines fail strict parsing.

    After the names, line 1 is only '<' filler, and OCR often reads runs of '<' as
    'K' and miscounts them. A trailing run of '<'/'K' becomes filler again and the
    line is trimmed or padded to 44. The same goes for the filler that ends the
    personal number in line 2.
    """
    line1, line2 = line1.replace(" ", "").upper(), line2.replace(" ", "").upper()

    tail = re.search(r"<[<K]*$", line1)
    if tail:
        line1 = line1[: tail.start()] + "<" * (len(line1) - tail.start())
    if len(line1) > LINE_LENGTH and set(line1[LINE_LENGTH:]) == {"<"}:
        line1 = line1[:LINE_LENGTH]
    line1 = line1.ljust(LINE_LENGTH, "<")

    if len(line2) == LINE_LENGTH:
        filler = re.search(r"<[<K]*$", line2[28:42])
        if filler:
            start = 28 + filler.start()
            line2 = line2[:start] + "<" * (42 - start) + line2[42:]
    return line1, line2


def _clean(value: str) -> str:
    return value.replace("<", " ").strip()


@dataclass(frozen=True)
class PassportMrz:
    document_type: str
    issuing_country: str
    surname: str
    given_names: str
    document_number: str
    nationality: str
    birth_date: date | None
    sex: str  # "M", "F" or "X" (unspecified)
    expiry_date: date | None
    personal_number: str
    # Fields fixed by check-digit-guided repair; the traveler should still glance at them.
    corrected_fields: set[str] = field(default_factory=set)
    # Result of each check digit: document_number, birth_date, expiry_date,
    # personal_number, composite.
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return all(self.checks.values())

    @property
    def suspect_fields(self) -> set[str]:
        """Fields the traveler should look at closely: a failed check digit or an unreadable date."""
        suspects = {name for name, ok in self.checks.items() if not ok and name != "composite"}
        if self.birth_date is None:
            suspects.add("birth_date")
        if self.expiry_date is None:
            suspects.add("expiry_date")
        return suspects


def parse_td3(line1: str, line2: str, *, today: date | None = None) -> PassportMrz:
    """Parse the two MRZ lines of a passport.

    Raises MrzFormatError if the lines can't be a passport MRZ. Check-digit failures
    don't raise: they're reported in `checks`, so the caller can ask the traveler to
    confirm the affected fields.
    """
    today = today or date.today()
    line1, line2 = line1.strip().upper(), line2.strip().upper()

    for number, line in ((1, line1), (2, line2)):
        if len(line) != LINE_LENGTH:
            raise MrzFormatError(f"Line {number} has {len(line)} characters, expected {LINE_LENGTH}.")
        if not set(line) <= _ALLOWED:
            raise MrzFormatError(f"Line {number} contains characters that can't appear in an MRZ.")
    if line1[0] != "P":
        raise MrzFormatError("Not a passport MRZ: line 1 must start with 'P'.")

    line1 = _correct_positions(line1, letters=_LINE1_LETTERS)
    line2 = _correct_positions(line2, digits=_LINE2_DIGITS, letters=_LINE2_LETTERS)

    corrected = set()
    for name, start, end in _REPAIRABLE_FIELDS:
        if not _check_passes(line2[start:end], line2[end]):
            repaired = _repair_by_check_digit(line2, start, end)
            if repaired:
                line2 = repaired
                corrected.add(name)

    surname, _, given_names = line1[5:].partition("<<")

    document_number = line2[0:9]
    birth = line2[13:19]
    expiry = line2[21:27]
    personal_number = line2[28:42]
    personal_check = line2[42]

    checks = {
        "document_number": _check_passes(document_number, line2[9]),
        "birth_date": _check_passes(birth, line2[19]),
        "expiry_date": _check_passes(expiry, line2[27]),
        # An unused personal number may have '<' as its check digit.
        "personal_number": _check_passes(personal_number, personal_check)
        or (personal_check == "<" and set(personal_number) == {"<"}),
        "composite": _composite_passes(line2),
    }

    return PassportMrz(
        document_type=_clean(line1[0:2]),
        issuing_country=_clean(line1[2:5]),
        surname=_clean(surname),
        given_names=_clean(given_names),
        document_number=_clean(document_number),
        nationality=_clean(line2[10:13]),
        birth_date=_parse_date(birth, is_expiry=False, today=today),
        sex=line2[20] if line2[20] in "MF" else "X",
        expiry_date=_parse_date(expiry, is_expiry=True, today=today),
        personal_number=_clean(personal_number),
        corrected_fields=corrected,
        checks=checks,
    )
