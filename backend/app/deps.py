"""Authentication and role-based access.

* AUTH_MODE=dev  — sign in by choosing a seeded user; the API issues an HMAC-signed token.
* AUTH_MODE=oidc — SSO: the frontend obtains an ID token from your IdP (Okta, Entra ID,
  Google Workspace); the API verifies it against the issuer's JWKS and maps the email to a user.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Candidate, Ticket, User
from .util import unsign

STAFF_ALL_CANDIDATES = {"recruiter", "ta_lead", "coordinator", "admin"}


@lru_cache
def _jwks_client():
    import jwt  # PyJWT

    s = get_settings()
    return jwt.PyJWKClient(f"{s.oidc_issuer.rstrip('/')}/.well-known/jwks.json")


def _user_from_token(db: Session, token: str) -> User | None:
    s = get_settings()
    if s.auth_mode == "oidc":
        import jwt

        try:
            key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=s.oidc_audience or s.oidc_client_id, issuer=s.oidc_issuer)
        except Exception:
            return None
        email = (claims.get("email") or claims.get("preferred_username") or "").lower()
        return db.query(User).filter(User.email == email, User.is_active.is_(True)).one_or_none()
    body = unsign(token)
    if not body or body.get("t") != "session":
        return None
    u = db.get(User, body.get("uid"))
    return u if u and u.is_active else None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
    u = _user_from_token(db, token) if token else None
    if u is None:
        raise HTTPException(401, "Not authenticated")
    request.state.user = u
    return u


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(403, f"Requires role: {', '.join(roles)}")
        return user

    return dep


def can_view_candidate(db: Session, user: User, c: Candidate) -> bool:
    if user.role in STAFF_ALL_CANDIDATES:
        return True
    team = {"payroll": "payroll", "immigration": "immigration", "onboarding": "onboarding", "marketing": "marketing"}.get(user.role)
    if team and db.query(Ticket).filter_by(candidate_id=c.id, team=team).first():
        return True
    return False


def get_candidate_for(db: Session, user: User, cid: int) -> Candidate:
    c = db.get(Candidate, cid)
    if c is None or c.purged:
        raise HTTPException(404, "Candidate not found")
    if c.merged_into_id:
        raise HTTPException(409, f"Merged into #{c.merged_into_id}")
    if not can_view_candidate(db, user, c):
        raise HTTPException(403, "Not authorized for this candidate")
    return c


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
