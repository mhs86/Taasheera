import stat

import pytest

from app.passport.storage import PassportImageStorage


@pytest.fixture
def storage(tmp_path):
    return PassportImageStorage(tmp_path)


def test_saved_image_can_be_loaded_by_its_owner(storage):
    upload_id = storage.save(1, b"jpeg bytes")

    assert storage.load(1, upload_id) == b"jpeg bytes"


def test_other_travelers_cannot_load_it(storage):
    upload_id = storage.save(1, b"jpeg bytes")

    assert storage.load(2, upload_id) is None


def test_upload_ids_are_random_and_unique(storage):
    assert storage.save(1, b"a") != storage.save(1, b"b")


@pytest.mark.parametrize("upload_id", ["../1/abc", "..", "", "A" * 32, "not-an-id"])
def test_rejects_ids_that_are_not_ours(storage, upload_id):
    assert storage.load(1, upload_id) is None


def test_files_are_readable_by_owner_only(storage, tmp_path):
    upload_id = storage.save(1, b"jpeg bytes")

    mode = (tmp_path / "1" / f"{upload_id}.jpg").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600
