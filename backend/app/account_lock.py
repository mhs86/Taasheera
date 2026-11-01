"""Cross-worker owner locks prevent file reads/writes racing with account erasure.

Locks contain no user data and are outside the folders erasure removes. All
workers sharing local passport storage must also share this lock directory.
"""
from contextlib import contextmanager

from fastapi import HTTPException
from filelock import FileLock, Timeout


@contextmanager
def account_lock(directory, traveler_id: int):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A dependency's enter/exit may run in different FastAPI worker threads.
    lock = FileLock(directory / f"{traveler_id}.lock", timeout=15, thread_local=False, mode=0o600)
    try:
        with lock:
            yield
    except Timeout:
        raise HTTPException(503, "Account is busy. Please try again.",
                            headers={"Cache-Control": "no-store", "Retry-After": "15"}) from None
