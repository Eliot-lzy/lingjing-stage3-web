from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


AUTH_COOKIE = "lingjing_access_token"
JWT_ALGORITHM = "HS256"
PASSWORD_ITERATIONS = 390000


def validate_auth_config() -> None:
    secret = os.getenv("JWT_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET must be configured with at least 32 characters."
        )


def jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET is missing or too short.")
    return secret


def jwt_expire_minutes() -> int:
    raw_value = os.getenv("JWT_EXPIRE_MINUTES", "1440")
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError("JWT_EXPIRE_MINUTES must be an integer.") from error
    return max(5, value)


def hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, encoded = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
        expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return hmac.compare_digest(expected, encoded)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=jwt_expire_minutes()),
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def token_from_request(request: Request) -> str | None:
    cookie_token = request.cookies.get(AUTH_COOKIE)
    if cookie_token:
        return cookie_token

    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return None


def decode_user_id(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.InvalidTokenError:
        return None

    user_id = payload.get("sub")
    return str(user_id) if user_id else None


def get_optional_user(
    request: Request,
    database: Session = Depends(get_db),
) -> User | None:
    token = token_from_request(request)
    if not token:
        return None

    user_id = decode_user_id(token)
    if not user_id:
        return None

    return database.get(User, user_id)


def get_current_user(
    user: User | None = Depends(get_optional_user),
) -> User:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="请先登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE,
        value=token,
        max_age=jwt_expire_minutes() * 60,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=AUTH_COOKIE, path="/")
