"""Sign-in for a shared server: accounts set from the CLI, two roles.

Off unless set up: on a personal computer (no ``auth.json`` in the profile)
the app opens without signing in, as before. ``ecosim auth set-user <name>
--role admin|tester`` writes ``<profile>/auth.json`` -- per account the name,
role and password as a scrypt hash (never the password itself), plus a random
secret that signs session cookies; from then on every API call except
``/auth/*`` and ``/health`` needs a valid session. On a server set
``ECOSIM_REQUIRE_AUTH=1`` so that a missing ``auth.json`` locks the app
instead of leaving it open.

Roles: ``admin`` can do everything; ``tester`` can look, compute, export and
save areas, but not change what the app runs on for everyone -- data sources,
the server's folders, reference-area packs (``admin_only``).

Session: an HMAC-signed cookie (``ecosim_session``: user, a fingerprint of
their password hash, expiry), HttpOnly, SameSite=Strict, Secure behind HTTPS.
A new password or a removed account ends that account's sessions. Failed
sign-ins are limited per client address (``_MAX_FAILURES`` in
``_FAILURE_WINDOW_S``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ecosim.core.workspace import profile_dir

COOKIE_NAME = "ecosim_session"
SESSION_SECONDS = 12 * 3600
ROLES = ("admin", "tester")
_MAX_FAILURES = 5
_FAILURE_WINDOW_S = 15 * 60
_SCRYPT = {"n": 2**15, "r": 8, "p": 1}


@dataclass(frozen=True)
class Account:
    username: str
    password_hash: str
    role: str


@dataclass(frozen=True)
class AuthConfig:
    secret: str
    accounts: tuple[Account, ...]

    def account(self, username: str) -> Account | None:
        return next((a for a in self.accounts if a.username == username), None)


def auth_path() -> Path:
    return profile_dir() / "auth.json"


def required() -> bool:
    return os.environ.get("ECOSIM_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")


def load_config() -> AuthConfig | None:
    path = auth_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    accounts = tuple(Account(a["username"], a["password_hash"], a["role"]) for a in data.get("accounts", []))
    return AuthConfig(data["secret"], accounts)


def enabled() -> bool:
    """Whether API calls need a session (auth set up, or required by the server)."""
    return required() or auth_path().exists()


def admin_only(method: str, path: str) -> bool:
    """Calls that change what the app runs on for everyone, or look at the server's disk."""
    if path.startswith("/admin/"):
        return method != "GET" or path == "/admin/browse"
    return path.startswith("/regions/packs") and method != "GET"


# --------------------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, maxmem=2**26, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        **_SCRYPT, salt=base64.b64encode(salt).decode(), digest=base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=2**26, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


# --------------------------------------------------------------------------- accounts


def _write(secret: str, accounts: list[Account]) -> None:
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"secret": secret, "accounts": [
        {"username": a.username, "password_hash": a.password_hash, "role": a.role} for a in accounts]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def set_user(username: str, password: str, role: str) -> None:
    """Add an account, or set an existing one's password and role (which
    ends its sessions)."""
    username = username.strip()
    if not username:
        raise ValueError("The user name can't be empty.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    if len(password) < 10:
        raise ValueError("Use a password of at least 10 characters.")
    cfg = load_config()
    accounts = [a for a in (cfg.accounts if cfg else ()) if a.username != username]
    if role != "admin" and not any(a.role == "admin" for a in accounts):
        raise ValueError("Set up an administrator first (--role admin).")
    accounts.append(Account(username, hash_password(password), role))
    _write(cfg.secret if cfg else secrets.token_hex(32), accounts)


def remove_user(username: str) -> bool:
    cfg = load_config()
    if cfg is None or cfg.account(username) is None:
        return False
    rest = [a for a in cfg.accounts if a.username != username]
    if rest and not any(a.role == "admin" for a in rest):
        raise ValueError("That is the last administrator -- add another one first.")
    _write(cfg.secret, rest)
    return True


def disable() -> bool:
    path = auth_path()
    if not path.exists():
        return False
    path.unlink()
    return True


# --------------------------------------------------------------------------- sessions


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _fingerprint(account: Account) -> str:
    return hashlib.sha256(account.password_hash.encode()).hexdigest()[:16]


def make_session(cfg: AuthConfig, account: Account, *, now: float | None = None) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"u": account.username, "v": _fingerprint(account),
         "exp": int((now or time.time()) + SESSION_SECONDS)}).encode())
    return f"{payload.decode()}.{_sign(payload, cfg.secret)}"


def session_account(token: str | None, cfg: AuthConfig | None, *, now: float | None = None) -> Account | None:
    """The signed-in account, or None: no/forged/expired token, an account
    since removed, or one whose password changed after signing in."""
    if not token or cfg is None or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload.encode(), cfg.secret)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except ValueError:
        return None
    account = cfg.account(data.get("u", ""))
    if account is None or data.get("exp", 0) < (now or time.time()) or data.get("v") != _fingerprint(account):
        return None
    return account


_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_login(cfg: AuthConfig, username: str, password: str) -> Account | None:
    account = cfg.account(username.strip())
    # Hash even for an unknown name, so the answer takes as long either way.
    ok = verify_password(password, account.password_hash if account else _DUMMY_HASH)
    return account if ok and account else None


# --------------------------------------------------------------------------- sign-in attempts


_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def too_many_failures(client: str) -> bool:
    cutoff = time.time() - _FAILURE_WINDOW_S
    with _failures_lock:
        recent = [t for t in _failures.get(client, []) if t > cutoff]
        _failures[client] = recent
        return len(recent) >= _MAX_FAILURES


def note_failure(client: str) -> None:
    with _failures_lock:
        _failures.setdefault(client, []).append(time.time())


def clear_failures(client: str) -> None:
    with _failures_lock:
        _failures.pop(client, None)
