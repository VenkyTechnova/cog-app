from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import current_user, require_roles
from ..models import Notification, User
from ..serializers import row, user as ser_user
from ..util import sign

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    email: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    s = get_settings()
    if s.auth_mode != "dev":
        raise HTTPException(400, "Password-less dev login is disabled; sign in with SSO")
    u = db.query(User).filter(User.email == body.email.lower(), User.is_active.is_(True)).one_or_none()
    if u is None:
        raise HTTPException(401, "Unknown user")
    audit(db, "auth.login", "user", u.id, u.id, {"mode": "dev"})
    db.commit()
    return {"token": sign({"t": "session", "uid": u.id}, ttl_seconds=s.token_ttl_hours * 3600), "user": ser_user(u)}


@router.get("/auth/config")
def auth_config():
    s = get_settings()
    return {"mode": s.auth_mode, "issuer": s.oidc_issuer, "client_id": s.oidc_client_id}


@router.get("/auth/dev-users")
def dev_users(db: Session = Depends(get_db)):
    if get_settings().auth_mode != "dev":
        return []
    return [ser_user(u) for u in db.query(User).filter(User.is_active.is_(True)).order_by(User.id).all()]


@router.get("/me")
def me(u: User = Depends(current_user)):
    return ser_user(u)


@router.get("/users")
def users(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return [ser_user(x) for x in db.query(User).order_by(User.name).all()]


class UserIn(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    digest_enabled: bool | None = None
    digest_prefs: dict | None = None


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), u: User = Depends(require_roles("admin"))):
    nu = User(name=body.name, email=(body.email or "").lower(), role=body.role or "recruiter")
    db.add(nu)
    db.flush()
    audit(db, "user.created", "user", nu.id, u.id, {"role": nu.role})
    db.commit()
    return ser_user(nu)


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserIn, db: Session = Depends(get_db), u: User = Depends(current_user)):
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    changes = body.model_dump(exclude_none=True)
    if uid != u.id and u.role != "admin":
        raise HTTPException(403)
    if u.role != "admin":
        changes = {k: v for k, v in changes.items() if k in ("digest_enabled", "digest_prefs")}
    for k, v in changes.items():
        setattr(target, k, v)
    audit(db, "user.updated", "user", uid, u.id, changes)
    db.commit()
    return ser_user(target)


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), u: User = Depends(current_user)):
    rows = db.query(Notification).filter_by(user_id=u.id).order_by(Notification.created_at.desc()).limit(50).all()
    return {"unread": sum(1 for n in rows if not n.read), "items": [row(n) for n in rows]}


@router.post("/notifications/read")
def read_all(db: Session = Depends(get_db), u: User = Depends(current_user)):
    db.query(Notification).filter_by(user_id=u.id, read=False).update({Notification.read: True})
    db.commit()
    return {"ok": True}
