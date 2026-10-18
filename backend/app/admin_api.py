"""Back-office API. Every route here is admin-only through the router's own dependency."""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .models import ROLES, Role, Traveler


PREFIX = "/admin"
FORBIDDEN = "Admin access required."


def install_admin_no_store(app: FastAPI) -> None:
    """Admin responses must never be cached: every status under /admin, including 404, 405,
    redirects, validation errors and handlers that build their own Response."""

    @app.middleware("http")
    async def admin_no_store(request: Request, call_next):
        response = await call_next(request)
        # Behind a path prefix (uvicorn --root-path) scope["path"] includes it; routing strips it the same way.
        path, root = request.scope["path"], request.scope.get("root_path", "")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if path == PREFIX or path.startswith(PREFIX + "/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def require_role(current_traveler, *roles: str):
    allowed = frozenset(roles)
    if not allowed or not allowed <= set(ROLES):
        raise ValueError("require_role needs one or more of: traveler, support, admin")

    def role_gate(traveler: Annotated[Traveler, Depends(current_traveler)]) -> Traveler:
        # current_traveler loaded this row from the database for this request; access tokens
        # carry no role, so demotion or suspension applies at once.
        # One refusal for every role and status, so it reveals neither.
        if traveler.status != "active" or traveler.role not in allowed:
            raise HTTPException(403, FORBIDDEN, headers={"Cache-Control": "no-store"})
        return traveler

    role_gate.allowed_roles = allowed  # Lets tests find every role-gated route.
    return role_gate


class AdminProfilePublic(BaseModel):
    """GET /admin/me: the signed-in staff member's own account."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role


def create_admin_router(current_traveler) -> APIRouter:
    admin = require_role(current_traveler, "admin")
    # The gate is on the router so later routes cannot skip it; support stays refused
    # until a route opts it in on its own router with require_role.
    router = APIRouter(prefix=PREFIX, tags=["Admin"], dependencies=[Depends(admin)])

    @router.get("/me", response_model=AdminProfilePublic)
    def admin_me(signed_in: Annotated[Traveler, Depends(admin)]):
        return signed_in

    return router
