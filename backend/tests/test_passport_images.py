from io import BytesIO

import pytest
from PIL import Image

from app.passport.images import MAX_SIDE, MAX_UPLOAD_BYTES, InvalidImageError, normalize_image


def encode(image: Image.Image, image_format: str, **options) -> bytes:
    output = BytesIO()
    image.save(output, format=image_format, **options)
    return output.getvalue()


def decode(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_accepted_formats_become_jpeg(image_format):
    data = encode(Image.new("RGB", (400, 300), "white"), image_format)

    result = decode(normalize_image(data))

    assert result.format == "JPEG"
    assert result.size == (400, 300)


def test_rejects_other_formats_even_if_they_are_images():
    data = encode(Image.new("RGB", (40, 30), "white"), "GIF")

    with pytest.raises(InvalidImageError) as error:
        normalize_image(data)
    assert error.value.status_code == 415


def test_rejects_files_that_are_not_images():
    with pytest.raises(InvalidImageError) as error:
        normalize_image(b"%PDF-1.7 not an image at all")
    assert error.value.status_code == 422


def test_rejects_oversized_uploads():
    with pytest.raises(InvalidImageError) as error:
        normalize_image(b"\xff" * (MAX_UPLOAD_BYTES + 1))
    assert error.value.status_code == 413


def test_applies_camera_rotation_and_strips_metadata():
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    exif[0x010F] = "PhoneMaker"  # Make: any metadata we shouldn't keep
    data = encode(Image.new("RGB", (400, 300), "white"), "JPEG", exif=exif)

    result = decode(normalize_image(data))

    assert result.size == (300, 400)
    assert len(result.getexif()) == 0


def test_downscales_large_images():
    data = encode(Image.new("RGB", (MAX_SIDE * 2, MAX_SIDE), "white"), "PNG")

    result = decode(normalize_image(data))

    assert result.size == (MAX_SIDE, MAX_SIDE // 2)
