from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import (
    create_user_account,
    create_user_session,
    delete_user_session,
    delete_user_sessions_except,
    session_user,
    update_user_password,
    user_by_email,
    user_by_id,
)


PBKDF2_ITERATIONS = 310_000
SESSION_DAYS = 14


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_value)
        expected = base64.b64decode(digest_value)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register(email: str, password: str, organization_name: str) -> tuple[dict[str, Any], str]:
    user = create_user_account(email, hash_password(password), organization_name)
    return user, issue_session(user["id"])


def login(email: str, password: str) -> tuple[dict[str, Any], str] | None:
    user = user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return {"id": user["id"], "email": user["email"]}, issue_session(user["id"])


def issue_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).replace(microsecond=0).isoformat()
    create_user_session(token_hash(token), user_id, expires_at)
    return token


def authenticate(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return session_user(token_hash(token), now)


def logout(token: str | None) -> None:
    if token:
        delete_user_session(token_hash(token))


def change_password(
    user_id: int, current_password: str, new_password: str,
    keep_token: str | None = None,
) -> bool:
    """Cambia la password dell'utente e revoca le altre sessioni.

    La sessione corrente (``keep_token``) resta valida: l'utente non viene
    disconnesso dal dispositivo da cui ha appena cambiato password, mentre
    tutte le altre sessioni vengono invalidate.
    """
    user = user_by_id(user_id)
    if not user or not verify_password(current_password, user["password_hash"]):
        return False
    update_user_password(user_id, hash_password(new_password))
    delete_user_sessions_except(
        user_id, token_hash(keep_token) if keep_token else None
    )
    return True
