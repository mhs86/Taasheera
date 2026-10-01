from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app


def test_main_app_passport_routes_require_the_authenticated_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSPORT_STORAGE_DIR", str(tmp_path / "passports"))
    app = create_app(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    image = BytesIO()
    Image.new("RGB", (400, 300), "white").save(image, format="JPEG")

    with TestClient(app) as client:
        for email in ("one@example.com", "two@example.com"):
            assert client.post("/auth/register", json={
                "name": "Traveler", "email": email, "password": "a-safe-password-123",
            }).status_code == 201

        assert client.post("/passports", files={"file": ("passport.jpg", image.getvalue(), "image/jpeg")}).status_code == 401

        first_login = client.post("/auth/login", json={
            "email": "one@example.com", "password": "a-safe-password-123",
        })
        first_headers = {"Authorization": f"Bearer {first_login.json()['access_token']}"}
        upload = client.post(
            "/passports", files={"file": ("passport.jpg", image.getvalue(), "image/jpeg")},
            headers=first_headers,
        )
        assert upload.status_code == 201
        upload_id = upload.json()["id"]
        assert client.get(f"/passports/{upload_id}/image", headers=first_headers).status_code == 200

        second_login = client.post("/auth/login", json={
            "email": "two@example.com", "password": "a-safe-password-123",
        })
        second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}
        assert client.get(f"/passports/{upload_id}/image", headers=second_headers).status_code == 404
        assert client.post(f"/passports/{upload_id}/extract", headers=second_headers).status_code == 404
