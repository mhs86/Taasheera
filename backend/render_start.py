"""Render Free has no pre-deploy command; migrate before starting its single API instance."""

import os

from migrate import upgrade


if __name__ == "__main__":
    upgrade()
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be a valid TCP port.")
    os.execvp("uvicorn", [
        "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port), "--no-access-log",
    ])
