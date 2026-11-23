import hmac

from fastapi import Cookie, Depends, Header, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from backend import demo
from backend.config import settings
from backend.db import session
from backend.models import User


def _serializer() -> URLSafeTimedSerializer:
    key = settings().mcp_signing_key
    if len(key) < 32:
        raise RuntimeError("MCP_SIGNING_KEY must be at least 32 characters")
    return URLSafeTimedSerializer(key, salt="hub-mcp-v1")


def credential_user(authorization: str | None = Header(default=None),
                    hub_demo: str | None = Cookie(default=None), db: Session = Depends(session)) -> User:
    if settings().public_demo_mode:
        return demo.authenticate(db, hub_demo)
    token = authorization.removeprefix("Bearer ") if authorization else ""
    configured = [(settings().demo_analyst_token, 1), (settings().demo_manager_token, 2)]
    actor_id = next((id for secret, id in configured if len(secret) >= 24 and hmac.compare_digest(token, secret)), None)
    user = db.get(User, actor_id) if actor_id else None
    if not user or not user.active:
        raise HTTPException(401, "Valid demo bearer token required")
    return user


def issue_capability(user: User) -> str:
    return _serializer().dumps({"id": user.id, "role": user.role})


def verify_capability(db: Session, token: str, *, manager_only: bool = False) -> User:
    try:
        payload = _serializer().loads(token, max_age=120)
    except (BadSignature, SignatureExpired) as exc:
        raise PermissionError("Invalid or expired capability") from exc
    if not isinstance(payload, dict) or type(payload.get("id")) is not int:
        raise PermissionError("Invalid capability")
    user = db.get(User, payload["id"])
    if not user or not user.active or user.role != payload.get("role"):
        raise PermissionError("Inactive or changed identity")
    if manager_only and user.role != "manager":
        raise PermissionError("Manager role required")
    return user
