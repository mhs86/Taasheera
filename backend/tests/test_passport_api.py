from io import BytesIO
from typing import Annotated

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from PIL import Image

from app.passport.router import create_passport_router
from app.passport.storage import PassportImageStorage

SPECIMEN = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
)


def fake_traveler_id(x_traveler: Annotated[int, Header()]) -> int:
    return x_traveler


def make_client(tmp_path, reader) -> TestClient:
    app = FastAPI()
    storage = PassportImageStorage(tmp_path)
    # The fake reader stands in for OCR, so these tests don't need Tesseract.
    app.include_router(create_passport_router(storage, fake_traveler_id, reader=reader))
    return TestClient(app)


def jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (400, 300), "white").save(output, format="JPEG")
    return output.getvalue()


def upload(client, traveler=1, data=None, name="passport.jpg"):
    return client.post(
        "/passports",
        files={"file": (name, data if data is not None else jpeg(), "image/jpeg")},
        headers={"X-Traveler": str(traveler)},
    )


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path, reader=lambda image: SPECIMEN)


def test_upload_then_extract_returns_verified_fields(client):
    upload_id = upload(client).json()["id"]

    response = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verified"
    assert body["fields"]["surname"] == "ERIKSSON"
    assert body["fields"]["expiry_date"] == "2012-04-15"
    assert body["suspect_fields"] == []
    assert "surname" in body["unverifiable_fields"]


def test_failed_check_digit_needs_review(tmp_path):
    misread = (SPECIMEN[0], "L8B8902C3" + SPECIMEN[1][9:])
    client = make_client(tmp_path, reader=lambda image: misread)
    upload_id = upload(client).json()["id"]

    body = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"}).json()

    assert body["status"] == "needs_review"
    assert body["suspect_fields"] == ["document_number"]


@pytest.mark.parametrize("ocr_output", [None, ("garbage", "text")])
def test_unreadable_scan_asks_for_manual_entry(tmp_path, ocr_output):
    client = make_client(tmp_path, reader=lambda image: ocr_output)
    upload_id = upload(client).json()["id"]

    response = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "unreadable", "fields": None, "suspect_fields": [], "corrected_fields": [],
        "unverifiable_fields": [], "checks": {},
    }


def test_other_traveler_gets_404_for_image_and_extraction(client):
    upload_id = upload(client, traveler=1).json()["id"]

    assert client.get(f"/passports/{upload_id}/image", headers={"X-Traveler": "2"}).status_code == 404
    assert client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "2"}).status_code == 404


def test_owner_can_fetch_the_stored_image(client):
    upload_id = upload(client).json()["id"]

    response = client.get(f"/passports/{upload_id}/image", headers={"X-Traveler": "1"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"


def test_review_is_saved_and_owner_scoped(client):
    upload_id = upload(client).json()["id"]
    fields = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"}).json()["fields"]
    fields["surname"] = "CORRECTED"
    url = f"/passports/{upload_id}/review"

    assert client.get(url, headers={"X-Traveler": "1"}).status_code == 404
    assert client.put(url, json=fields, headers={"X-Traveler": "1"}).status_code == 200
    saved = client.get(url, headers={"X-Traveler": "1"})
    assert saved.json()["surname"] == "CORRECTED"
    assert saved.headers["cache-control"] == "private, no-store"
    assert client.get(url, headers={"X-Traveler": "2"}).status_code == 404
    assert client.put(url, json=fields, headers={"X-Traveler": "2"}).status_code == 404


def test_review_rejects_extra_fields(client):
    upload_id = upload(client).json()["id"]
    fields = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"}).json()["fields"]
    fields["traveler_id"] = 2
    assert client.put(f"/passports/{upload_id}/review", json=fields,
                      headers={"X-Traveler": "1"}).status_code == 422


def test_uploads_can_be_disabled_on_a_host_without_durable_storage(tmp_path):
    app = FastAPI()
    app.include_router(create_passport_router(PassportImageStorage(tmp_path), fake_traveler_id,
                                              uploads_enabled=False))
    response = upload(TestClient(app))
    assert response.status_code == 503
    assert not list(tmp_path.iterdir())


def test_file_name_is_ignored_and_content_is_checked(client):
    response = upload(client, data=b"#!/bin/sh\necho not an image", name="passport.jpg")

    assert response.status_code == 422



def test_repaired_document_number_is_reported(tmp_path):
    misread = (SPECIMEN[0], "L8989O2C3" + SPECIMEN[1][9:])
    client = make_client(tmp_path, reader=lambda image: misread)
    upload_id = upload(client).json()["id"]

    body = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"}).json()

    assert body["status"] == "verified"
    assert body["fields"]["document_number"] == "L898902C3"
    assert body["corrected_fields"] == ["document_number"]


def test_review_accepts_a_passport_without_given_names(client):
    upload_id = upload(client).json()["id"]
    fields = client.post(f"/passports/{upload_id}/extract", headers={"X-Traveler": "1"}).json()["fields"]
    fields["given_names"] = ""

    response = client.put(f"/passports/{upload_id}/review", json=fields, headers={"X-Traveler": "1"})

    assert response.status_code == 200
    assert response.json()["given_names"] == ""
