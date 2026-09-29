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
"""

from dataclasses import dataclass, field
from datetime import date

LINE_LENGTH = 44
_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<")
_WEIGHTS = (7, 3, 1)


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
        "composite": _check_passes(line2[0:10] + line2[13:20] + line2[21:43], line2[43]),
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
        checks=checks,
    )
