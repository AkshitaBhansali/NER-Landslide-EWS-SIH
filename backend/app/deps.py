"""Shared request dependencies."""
from __future__ import annotations

import hashlib
import hmac
import json
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .casing import shape
from .config import settings
from .db import get_db

__all__ = ["Scope", "get_scope", "get_db", "Session", "respond", "require_role", "make_token"]


@dataclass
class Scope:
    state_code: str | None = None
    district_id: str | None = None

    @property
    def label(self) -> str:
        if self.district_id and self.district_id != "ALL":
            return self.district_id
        if self.state_code and self.state_code != "ALL":
            return self.state_code
        return "ALL"


def get_scope(
    state: str | None = Query(None, description="State code, or ALL"),
    district: str | None = Query(None, description="District id, or ALL"),
) -> Scope:
    return Scope(state_code=state, district_id=district)


def get_case(case: str | None = Query(None, description="'camel' to receive camelCase")) -> str | None:
    return case


def respond(payload, case: str | None = None, response: Response | None = None):
    """Single exit point for every handler, so the casing switch is applied once."""
    if response is not None:
        response.headers["X-Data-Confidence"] = settings.data_confidence
    return shape(payload, case)


# --------------------------------------------------------------------------- #
# Auth — deliberately minimal, and OFF by default.
#
# Real deployment needs the state's SSO. What matters at this stage is that the
# role boundaries exist and are enforced in one place, so adding a real identity
# provider later is a swap of `current_user`, not an audit of every endpoint.
# --------------------------------------------------------------------------- #
ROLE_RANK = {"VIEWER": 0, "FIELD_OFFICER": 1, "DDMA": 2, "STATE_ADMIN": 3}


def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def make_token(username: str, role: str, district_id: str | None) -> str:
    exp = (datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)).timestamp()
    return _sign({"sub": username, "role": role, "district_id": district_id, "exp": exp})


def _verify(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
        expect = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if payload.get("exp", 0) < datetime.now(timezone.utc).timestamp():
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None


def current_user(authorization: str | None = Header(None)) -> dict:
    if not settings.auth_enabled:
        return {"sub": "demo", "role": "STATE_ADMIN", "district_id": None}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    payload = _verify(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    return payload


def require_role(minimum: str):
    def _dep(user: dict = Depends(current_user)) -> dict:
        if ROLE_RANK.get(user.get("role", "VIEWER"), 0) < ROLE_RANK[minimum]:
            raise HTTPException(403, f"Requires role {minimum} or higher")
        return user

    return _dep
