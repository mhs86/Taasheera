"""Passport upload (US 6) and extraction (US 7) endpoints.

Follows the app's router-factory pattern. `current_traveler_id` is a FastAPI
dependency returning the signed-in traveler's id; main.py passes one built on the
auth module. Endpoints are plain `def`, so FastAPI runs them in a worker thread
and OCR (CPU-bound, a few hundred ms) doesn't block other requests.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel

from .extraction import Extraction, MrzReader, extract_passport, read_mrz_lines
from .images import MAX_UPLOAD_BYTES, InvalidImageError, normalize_image
from .storage import PassportImageStorage

# Fields the MRZ has no check digit for. The review form always asks the
# traveler to confirm these, even when every check passed.
UNVERIFIABLE_FIELDS = ["surname", "given_names", "nationality", "issuing_country", "sex"]


class PassportUploadPublic(BaseModel):
    id: str


class PassportFields(BaseModel):
    surname: str
    given_names: str
    document_number: str
    nationality: str
    issuing_country: str
    birth_date: date | None
    sex: Literal["M", "F", "X"]
    expiry_date: date | None
    personal_number: str


class ExtractionPublic(BaseModel):
    status: Literal["verified", "needs_review", "unreadable"]
    fields: PassportFields | None
    # Fields whose check digit failed or whose date is impossible: highlight them.
    suspect_fields: list[str]
    # OCR misreads fixed using the check digit (e.g. letter O -> zero).
    corrected_fields: list[str]
    unverifiable_fields: list[str]
    checks: dict[str, bool]

    @classmethod
    def from_extraction(cls, extraction: Extraction) -> "ExtractionPublic":
        mrz = extraction.mrz
        if mrz is None:
            return cls(status=extraction.status, fields=None, suspect_fields=[],
                       corrected_fields=[], unverifiable_fields=[], checks={})
        return cls(
            status=extraction.status,
            fields=PassportFields(
                surname=mrz.surname,
                given_names=mrz.given_names,
                document_number=mrz.document_number,
                nationality=mrz.nationality,
                issuing_country=mrz.issuing_country,
                birth_date=mrz.birth_date,
                sex=mrz.sex,
                expiry_date=mrz.expiry_date,
                personal_number=mrz.personal_number,
            ),
            suspect_fields=sorted(mrz.suspect_fields),
            corrected_fields=sorted(mrz.corrected_fields),
            unverifiable_fields=UNVERIFIABLE_FIELDS,
            checks=mrz.checks,
        )


def create_passport_router(
    storage: PassportImageStorage,
    current_traveler_id,
    *,
    reader: MrzReader = read_mrz_lines,
) -> APIRouter:
    router = APIRouter(prefix="/passports", tags=["passports"])
    TravelerId = Annotated[int, Depends(current_traveler_id)]

    def load_owned(traveler_id: int, upload_id: str) -> bytes:
        image = storage.load(traveler_id, upload_id)
        if image is None:
            # 404 whether it doesn't exist or belongs to someone else, so ids can't be probed.
            raise HTTPException(status_code=404, detail="Passport upload not found.")
        return image

    @router.post("", response_model=PassportUploadPublic, status_code=201)
    def upload_passport(file: UploadFile, traveler_id: TravelerId):
        # Read one byte past the limit so oversized files are detected without reading them fully.
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        try:
            jpeg = normalize_image(data)
        except InvalidImageError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        return PassportUploadPublic(id=storage.save(traveler_id, jpeg))

    @router.get("/{upload_id}/image")
    def passport_image(upload_id: str, traveler_id: TravelerId):
        image = load_owned(traveler_id, upload_id)
        return Response(image, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @router.post("/{upload_id}/extract", response_model=ExtractionPublic)
    def extract(upload_id: str, traveler_id: TravelerId):
        image = load_owned(traveler_id, upload_id)
        return ExtractionPublic.from_extraction(extract_passport(image, reader=reader))

    return router
