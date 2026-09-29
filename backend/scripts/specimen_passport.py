"""Generate a synthetic passport image carrying the ICAO 9303 specimen MRZ.

Used by the OCR tests and the demo page, so nobody needs a real passport to try
the pipeline. The data belongs to the fictional "Anna Maria Eriksson" of Utopia.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SPECIMEN_MRZ = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
)

_MONOSPACE_FONTS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
]
FONT = next((path for path in _MONOSPACE_FONTS if Path(path).exists()), None)


def synthetic_passport(blur: float = 0) -> bytes:
    """A passport-like page as JPEG: header text, a photo box, and the MRZ at the bottom."""
    if FONT is None:
        raise RuntimeError("No monospace font found to draw the MRZ.")
    image = Image.new("RGB", (1250, 880), (236, 232, 222))
    draw = ImageDraw.Draw(image)
    small, mrz_font = ImageFont.truetype(FONT, 24), ImageFont.truetype(FONT, 34)
    draw.text((50, 40), "UTOPIA  PASSPORT / PASSEPORT", font=small, fill=(40, 40, 90))
    draw.rectangle((50, 140, 330, 520), fill=(190, 190, 200))
    for row, text in enumerate(["Surname: ERIKSSON", "Given names: ANNA MARIA", "Date of birth: 12 AUG 1974"]):
        draw.text((380, 160 + row * 60), text, font=small, fill=(30, 30, 30))
    draw.text((40, 700), SPECIMEN_MRZ[0], font=mrz_font, fill=(10, 10, 10))
    draw.text((40, 770), SPECIMEN_MRZ[1], font=mrz_font, fill=(10, 10, 10))
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    output = BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()
