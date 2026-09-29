"""Validate uploaded passport images and normalize them before storage.

The file type comes from the file's content, never from its name or the
Content-Type header, which the client controls. Every accepted image is
re-encoded as a fresh JPEG. That:
- applies the phone camera's EXIF rotation, so the MRZ is the right way up for OCR
- strips metadata (phone photos can carry GPS location)
- means we never store the uploaded bytes as-is
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 50_000_000  # rejects "decompression bombs": tiny files that expand into huge images
MAX_SIDE = 2400  # plenty for OCR on a passport page, and keeps OCR fast
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class InvalidImageError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def normalize_image(data: bytes) -> bytes:
    """Return the upload as a clean, upright JPEG, or raise InvalidImageError."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImageError("Image must be 10 MB or smaller.", 413)
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise InvalidImageError("Upload a JPEG, PNG or WebP image.", 415)
            if image.width * image.height > MAX_PIXELS:
                raise InvalidImageError("Image dimensions are too large.", 413)
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise InvalidImageError("The file isn't a readable image.", 422) from None

    upright.thumbnail((MAX_SIDE, MAX_SIDE))
    output = BytesIO()
    upright.save(output, format="JPEG", quality=90)
    return output.getvalue()
