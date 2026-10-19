"""Passwords, login sessions and the 'who is logged in?' dependencies.

- Passwords and security answers are stored as salted scrypt hashes (standard library).
- A login creates a random token. The browser gets it in an HttpOnly cookie;
  MongoDB stores only its SHA-256 hash (collection 'sessions'), so a database leak
  does not expose usable tokens.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from pymongo.database import Database
from app.config import get_settings
from app.database import get_db, run_db
from app.services.repository import Doc, to_doc

COOKIE_NAME = "session"


# ------------------------------------------------------------------ hashing
def hash_secret(secret: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(secret.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"{salt.hex()}${digest.hex()}"


def verify_secret(secret: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(secret.encode(), salt=bytes.fromhex(salt_hex),
                                n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except Exception:
        return False


def normalize_answer(answer: str) -> str:
    """'  My School ' and 'my school' count as the same security answer."""
    return " ".join(answer.lower().split())


# ----------------------------------------------------------------- sessions
def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Database, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.sessions.insert_one({
        "_id": _token_id(token), "user_id": user_id, "created_at": now,
        "expires_at": now + timedelta(days=get_settings().SESSION_DAYS),
    })
    return token


def get_user_by_token(db: Database, token: str) -> Doc | None:
    session = db.sessions.find_one({"_id": _token_id(token)})
    if not session:
        return None
    expires = session["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.sessions.delete_one({"_id": session["_id"]})
        return None
    return to_doc(db.users.find_one({"_id": session["user_id"]}))


def delete_session(db: Database, token: str) -> None:
    db.sessions.delete_one({"_id": _token_id(token)})


def set_session_cookie(response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.SESSION_DAYS * 86400,
        httponly=True, samesite="lax",
        secure=settings.ENVIRONMENT.lower() == "production",   # HTTPS-only in production
    )


# ------------------------------------------------------------- dependencies
async def current_user_or_none(request: Request, db: Database = Depends(get_db)) -> Doc | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return await run_db(get_user_by_token, db, token)


async def require_user(user: Doc | None = Depends(current_user_or_none)) -> Doc:
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")
    return user


async def require_admin(user: Doc = Depends(require_user)) -> Doc:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
