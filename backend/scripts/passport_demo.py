"""Local demo of the passport endpoints, until they're wired into main.py with real auth.

Run from backend/:  uvicorn scripts.passport_demo:app --reload
Then open http://127.0.0.1:8000 for the test page, or /docs for the raw API.

There's no login here: requests act as traveler 1, or as whoever the
`X-Demo-Traveler` header names (the test page has a switcher, to show the
owner check returning 404). Local use only. Never deploy this.
"""

import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.passport.router import create_passport_router
from app.passport.storage import PassportImageStorage
from scripts.specimen_passport import FONT, synthetic_passport


def demo_traveler_id(x_demo_traveler: Annotated[int, Header()] = 1) -> int:
    return x_demo_traveler


storage = PassportImageStorage(os.environ.get("PASSPORT_STORAGE_DIR", "storage/passports"))
app = FastAPI(title="Ta'asheera passport demo")
app.include_router(create_passport_router(storage, demo_traveler_id))


@app.get("/", include_in_schema=False)
def test_page():
    return FileResponse(Path(__file__).with_name("passport_demo.html"))


@app.get("/demo/specimen.jpg", include_in_schema=False)
def specimen(blur: Annotated[float, Query(ge=0, le=20)] = 0):
    if FONT is None:
        raise HTTPException(status_code=501, detail="No monospace font available to draw the specimen.")
    return Response(synthetic_passport(blur=blur), media_type="image/jpeg")
