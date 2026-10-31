"""Back-office API. Every route here is admin-only through the router's own dependency."""

import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import or_, update
from sqlmodel import Session, func, select

from .activity import record_activity
from .auth import check_origin, revoke_all_sessions
from .models import (ROLES, APPLICATION_STATUSES, AccountErasure, ActivityEvent, AuthSession,
                     GoogleIdentity, Role, Status, Traveler, VisaApplication)
from .account_lock import account_lock
from .privacy import DeleteUser, erase_account, erasure_response


PREFIX = "/admin"
FORBIDDEN = "Admin access required."
NOT_FOUND = "User not found."
UserId = Annotated[int, Path(gt=0, le=2_147_483_647)]


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


class AdminUserSummary(BaseModel):
    id: int
    name: str
    email: str
    auth_type: Literal["email_password", "google"]
    role: Role
    status: Status
    created_at: datetime | None  # None for accounts made before sign-up times were recorded.
    last_sign_in_at: datetime | None


class AdminUserPage(BaseModel):
    items: list[AdminUserSummary]
    total: int
    page: int
    page_size: int


class AdminUserCounts(BaseModel):
    active_sessions: int
    sign_ins: int
    failed_sign_ins: int
    passport_uploads: int


class AdminUserDetail(AdminUserSummary):
    """Account information only: never passport images, passport fields or profile details."""
    sso_email: str | None
    password_enabled: bool
    google_linked: bool
    last_sign_in_method: str | None
    counts: AdminUserCounts


class AdminOverview(BaseModel):
    total_users: int
    new_last_7_days: int
    suspended: int
    applications_started: int


class UserSearch(BaseModel):
    # An unknown or misspelled filter is refused rather than silently listing everyone.
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] = ""
    role: Role | None = None
    status: Status | None = None
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=100)


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class MonitoringError(BaseModel):
    id: int
    occurred_at: datetime
    event_type: str
    outcome: str
    source: str


class MonitoringPublic(BaseModel):
    applications_by_status: dict[str, int]
    total_applications: int
    recent_errors: list[MonitoringError]
    agent_failures_available: bool
    pending_erasures: int


def count(session: Session, model, *conditions) -> int:
    return session.exec(select(func.count()).select_from(model).where(*conditions)).one()


def summary_fields(traveler: Traveler) -> dict:
    return {
        "id": traveler.id, "name": traveler.name, "email": traveler.email,
        "auth_type": traveler.auth_type, "role": traveler.role, "status": traveler.status,
        "created_at": traveler.created_at,
        "last_sign_in_at": (datetime.fromtimestamp(traveler.last_login_at, timezone.utc)
                            if traveler.last_login_at is not None else None),
    }


def user_detail(session: Session, passport_storage, traveler: Traveler) -> AdminUserDetail:
    sign_ins = (ActivityEvent.traveler_id == traveler.id, ActivityEvent.event_type == "sign_in")
    return AdminUserDetail(
        **summary_fields(traveler),
        sso_email=traveler.sso_email,
        password_enabled=traveler.password_enabled,
        google_linked=count(session, GoogleIdentity, GoogleIdentity.traveler_id == traveler.id) > 0,
        last_sign_in_method=traveler.last_login_method,
        counts=AdminUserCounts(
            active_sessions=count(session, AuthSession, AuthSession.traveler_id == traveler.id,
                                  AuthSession.revoked.is_(False), AuthSession.expires_at > int(time.time())),
            sign_ins=count(session, ActivityEvent, *sign_ins, ActivityEvent.outcome == "success"),
            failed_sign_ins=count(session, ActivityEvent, *sign_ins, ActivityEvent.outcome != "success"),
            passport_uploads=passport_storage.upload_count(traveler.id),
        ),
    )


def lock_accounts(session: Session, actor_id: int, target_id: int) -> tuple[Traveler, Traveler | None]:
    """Lock the acting admin's and the target's rows, then re-read both."""
    # In id order, so two admins acting on each other cannot deadlock on PostgreSQL;
    # on SQLite the first no-op UPDATE takes the database write lock.
    for traveler_id in sorted({actor_id, target_id}):
        session.execute(update(Traveler).where(Traveler.id == traveler_id).values(role=Traveler.role))
    rows = {row.id: row for row in session.exec(
        select(Traveler).where(Traveler.id.in_(sorted({actor_id, target_id})))
        .execution_options(populate_existing=True))}
    actor = rows.get(actor_id)
    # The gate checked the actor when the request began; another admin may have changed it since.
    if actor is None or actor.status != "active" or actor.role != "admin":
        raise HTTPException(403, FORBIDDEN, headers={"Cache-Control": "no-store"})
    target = rows.get(target_id)
    if target is None:
        raise HTTPException(404, NOT_FOUND)
    if session.get(AccountErasure, target_id) is not None:
        raise HTTPException(409, "Account erasure is pending; this user cannot be changed.")
    return actor, target


def apply_change(session: Session, request: Request, actor: Traveler, target: Traveler,
                 event_type: str, field: str, value: str) -> None:
    previous = getattr(target, field)
    setattr(target, field, value)
    session.add(target)
    if field == "status":
        # Suspension signs the account out everywhere. Reactivation does too, in case it was suspended
        # outside this API, where its sessions were only blocked, and would otherwise work again.
        revoke_all_sessions(session, target.id)
    # record_activity commits, so the change and its audit event are saved together or not at all.
    record_activity(session, request.app.state.activity_directory, target.id, event_type,
                    f"admin:{actor.id}:{previous}->{value}", "success")


def create_admin_router(get_session, current_traveler, passport_storage) -> APIRouter:
    admin = require_role(current_traveler, "admin")
    # The gate is on the router so later routes cannot skip it; support stays refused
    # until a route opts it in on its own router with require_role.
    router = APIRouter(prefix=PREFIX, tags=["Admin"], dependencies=[Depends(admin)])
    SessionDep = Annotated[Session, Depends(get_session)]
    AdminDep = Annotated[Traveler, Depends(admin)]

    @router.get("/me", response_model=AdminProfilePublic)
    def admin_me(signed_in: AdminDep):
        return signed_in

    @router.get("/monitoring", response_model=MonitoringPublic)
    def monitoring(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20):
        counts = dict(session.exec(select(VisaApplication.status, func.count())
                                  .group_by(VisaApplication.status)).all())
        # Only metadata saved by backend code; never return arbitrary request/provider errors.
        errors = session.exec(select(ActivityEvent).where(
            ActivityEvent.outcome.in_(["failure", "error", "unavailable", "timeout", "unreadable"]))
            .order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc()).limit(limit)).all()
        return {"applications_by_status": {value: counts.get(value, 0) for value in APPLICATION_STATUSES},
                "total_applications": sum(counts.values()),
                "recent_errors": [{"id": event.id, "occurred_at": event.occurred_at,
                    "event_type": event.event_type, "outcome": event.outcome,
                    "source": event.identifier if event.event_type == "api_error" else event.event_type}
                    for event in errors],
                "agent_failures_available": False,
                "pending_erasures": count(session, AccountErasure)}

    @router.get("/overview", response_model=AdminOverview)
    def overview(session: SessionDep):
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        return AdminOverview(
            total_users=count(session, Traveler),
            new_last_7_days=count(session, Traveler, Traveler.created_at >= week_ago),
            suspended=count(session, Traveler, Traveler.status == "suspended"),
            applications_started=count(session, VisaApplication),
        )

    @router.get("/users", response_model=AdminUserPage)
    def list_users(search: Annotated[UserSearch, Query()], session: SessionDep):
        filters = []
        if search.q:
            term = search.q.lower()
            filters.append(or_(func.lower(Traveler.name).contains(term, autoescape=True),
                               func.lower(Traveler.email).contains(term, autoescape=True)))
        if search.role is not None:
            filters.append(Traveler.role == search.role)
        if search.status is not None:
            filters.append(Traveler.status == search.status)
        rows = session.exec(select(Traveler).where(*filters).order_by(Traveler.id.desc())
                            .offset((search.page - 1) * search.page_size).limit(search.page_size)).all()
        return AdminUserPage(items=[AdminUserSummary(**summary_fields(row)) for row in rows],
                             total=count(session, Traveler, *filters),
                             page=search.page, page_size=search.page_size)

    @router.get("/users/{user_id}", response_model=AdminUserDetail)
    def get_user(user_id: UserId, session: SessionDep):
        target = session.get(Traveler, user_id)
        if target is None:
            raise HTTPException(404, NOT_FOUND)
        return user_detail(session, passport_storage, target)

    @router.post("/users/{user_id}/suspend", response_model=AdminUserDetail, dependencies=[Depends(check_origin)])
    def suspend_user(user_id: UserId, request: Request, session: SessionDep, signed_in: AdminDep):
        actor, target = lock_accounts(session, signed_in.id, user_id)
        if target.id == actor.id:
            raise HTTPException(409, "You can't suspend your own account.")
        if target.status == "suspended":
            raise HTTPException(409, "This account is already suspended.")
        # Suspension also ends every session, so the account is signed out everywhere at once.
        apply_change(session, request, actor, target, "status_change", "status", "suspended")
        return user_detail(session, passport_storage, target)

    @router.post("/users/{user_id}/reactivate", response_model=AdminUserDetail, dependencies=[Depends(check_origin)])
    def reactivate_user(user_id: UserId, request: Request, session: SessionDep, signed_in: AdminDep):
        actor, target = lock_accounts(session, signed_in.id, user_id)
        if target.status == "active":
            raise HTTPException(409, "This account is already active.")
        apply_change(session, request, actor, target, "status_change", "status", "active")
        return user_detail(session, passport_storage, target)

    @router.put("/users/{user_id}/role", response_model=AdminUserDetail, dependencies=[Depends(check_origin)])
    def change_role(user_id: UserId, data: RoleChange, request: Request, session: SessionDep,
                    signed_in: AdminDep):
        actor, target = lock_accounts(session, signed_in.id, user_id)
        if target.id == actor.id:
            raise HTTPException(409, "You can't change your own role.")
        if target.role == data.role:
            raise HTTPException(409, f"This account already has the {data.role} role.")
        apply_change(session, request, actor, target, "role_change", "role", data.role)
        return user_detail(session, passport_storage, target)

    @router.delete("/users/{user_id}", status_code=204, response_class=Response,
                   responses={202: {"description": "Account disabled; data erasure queued for retry"}},
                   dependencies=[Depends(check_origin)])
    def delete_user(user_id: UserId, data: DeleteUser, request: Request, session: SessionDep,
                    signed_in: AdminDep):
        if user_id != data.expected_user_id:
            raise HTTPException(409, "The selected user changed. Reload before deleting.")
        if user_id == signed_in.id:
            raise HTTPException(409, "Use your account page to delete your own account.")
        # Owner operations hold this same lock until their response finishes.
        with account_lock(request.app.state.account_lock_directory, user_id):
            actor, target = lock_accounts(session, signed_in.id, user_id)
            if target.role == "admin":
                raise HTTPException(409, "Transfer this user's admin role before deletion.")
            complete = erase_account(session, target, passport_storage, request.app.state.activity_directory,
                                     request.app.state.auth_settings.jwt_secret)
            # Keep an administrative action record without retaining the deleted user's ID or data.
            record_activity(session, request.app.state.activity_directory, actor.id,
                            "account_erasure", "account", "success" if complete else "pending")
            return erasure_response(complete)

    return router
