"""Sign in / out (core/auth.py)."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ecosim.core import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def client_address(request: Request) -> str:
    """The client's address -- behind a reverse proxy (``ECOSIM_TRUST_PROXY=1``)
    the one the proxy saw, the last entry it appended to X-Forwarded-For."""
    if os.environ.get("ECOSIM_TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _https(request: Request) -> bool:
    if os.environ.get("ECOSIM_TRUST_PROXY") == "1" and request.headers.get("x-forwarded-proto") == "https":
        return True
    return request.url.scheme == "https"


def current_account(request: Request) -> auth.Account | None:
    return auth.session_account(request.cookies.get(auth.COOKIE_NAME), auth.load_config())


def _status(account: auth.Account | None) -> dict:
    return {"enabled": True, "user": account.username if account else None,
            "role": account.role if account else None}


@router.get("/status")
def status(request: Request) -> dict:
    """``enabled``: the app needs signing in; ``user``/``role``: who is signed in."""
    if not auth.enabled():
        return {"enabled": False, "user": None, "role": None}
    return _status(current_account(request))


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    cfg = auth.load_config()
    if cfg is None or not cfg.accounts:
        raise HTTPException(status_code=503, detail="Signing in isn't set up on this server yet "
                                                    "(administrator: run `ecosim auth set-user`).")
    client = client_address(request)
    if auth.too_many_failures(client):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
    account = auth.check_login(cfg, body.username, body.password)
    if account is None:
        auth.note_failure(client)
        raise HTTPException(status_code=401, detail="Wrong user name or password.")
    auth.clear_failures(client)
    response.set_cookie(
        auth.COOKIE_NAME, auth.make_session(cfg, account), max_age=auth.SESSION_SECONDS,
        httponly=True, samesite="strict", secure=_https(request), path="/",
    )
    return _status(account)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"enabled": auth.enabled(), "user": None, "role": None}
