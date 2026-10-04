"""Private storage for passport images, one folder per traveler.

Ownership is enforced by construction: every read goes through the caller's own
folder, so asking for another traveler's upload id simply finds nothing. Upload
ids are random UUIDs we generate; client-supplied file names are never used in
paths. This local-disk version is for development. Production swaps in a private
bucket with the same `<traveler_id>/<upload_id>` key scheme.
"""

import os
import re
import uuid
import json
from pathlib import Path

_UPLOAD_ID = re.compile(r"[0-9a-f]{32}")


class PassportImageStorage:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, owner_id: int, upload_id: str) -> Path | None:
        # Rejecting anything but our own id format rules out path tricks like "../".
        if not _UPLOAD_ID.fullmatch(upload_id):
            return None
        return self.root / str(int(owner_id)) / f"{upload_id}.jpg"

    def save(self, owner_id: int, jpeg: bytes) -> str:
        upload_id = uuid.uuid4().hex
        path = self._path(owner_id, upload_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Owner-only permissions; O_EXCL refuses to overwrite an existing file.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(jpeg)
        return upload_id

    def load(self, owner_id: int, upload_id: str) -> bytes | None:
        path = self._path(owner_id, upload_id)
        if path is None or not path.is_file():
            return None
        return path.read_bytes()

    def save_review(self, owner_id: int, upload_id: str, fields: dict) -> None:
        image_path = self._path(owner_id, upload_id)
        if image_path is None or not image_path.is_file():
            raise FileNotFoundError(upload_id)
        review_path = image_path.with_suffix(".json")
        temporary = review_path.with_name(f"{review_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(fields, file)
            os.replace(temporary, review_path)
        finally:
            temporary.unlink(missing_ok=True)

    def load_review(self, owner_id: int, upload_id: str) -> dict | None:
        image_path = self._path(owner_id, upload_id)
        if image_path is None or not image_path.is_file():
            return None
        review_path = image_path.with_suffix(".json")
        if not review_path.is_file():
            return None
        return json.loads(review_path.read_text(encoding="utf-8"))
