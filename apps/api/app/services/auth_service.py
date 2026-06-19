from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from uuid import uuid4
from typing import Any

import jwt
import redis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError

from app.config import get_settings
from app.database import db_connection
from app.schemas import AuthResponse, UserProfile

HASH_ITERATIONS = 260000
TOKEN_ALGORITHM = "HS256"
TOKEN_KEY_PREFIX = "auth:jwt:"
GOOGLE_STATE_KEY_PREFIX = "auth:google:state:"
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), HASH_ITERATIONS)
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt, stored_digest = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
    return hmac.compare_digest(digest.hex(), stored_digest)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def serialize_user(row: dict[str, Any]) -> UserProfile:
    settings = get_settings()
    configured_maintainer_email = settings.maintainer_email.strip().lower()
    email = row["email"]
    role = row["role"]
    if configured_maintainer_email and (email or "").lower() == configured_maintainer_email:
        role = "admin"
    return UserProfile(
        id=str(row["id"]),
        email=email,
        displayName=row["display_name"],
        avatarUrl=row["avatar_url"],
        role=role,
        lastLoginAt=row.get("last_login_at"),
    )


def issue_auth_response(user: UserProfile) -> AuthResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    jti = str(uuid4())
    payload = {
        "sub": user.id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + settings.jwt_ttl_seconds,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=TOKEN_ALGORITHM)
    redis_client().setex(
        f"{TOKEN_KEY_PREFIX}{jti}",
        settings.jwt_ttl_seconds,
        json.dumps({"userId": user.id, "tokenHash": hash_token(token)}),
    )
    return AuthResponse(
        authenticated=True,
        user=user,
        accessToken=token,
        tokenType="bearer",
        expiresIn=settings.jwt_ttl_seconds,
    )


def load_user(user_id: str) -> UserProfile | None:
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id, email, display_name, avatar_url, role, last_login_at
FROM users
WHERE id = %s AND status = 'active'
LIMIT 1
""",
            (user_id,),
        ).fetchone()
    return serialize_user(row) if row else None


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserProfile | None:
    if not credentials:
        return None
    if credentials.scheme.lower() != "bearer":
        return None
    settings = get_settings()
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[TOKEN_ALGORITHM])
    except (ExpiredSignatureError, InvalidTokenError):
        return None

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        return None

    cache_key = f"{TOKEN_KEY_PREFIX}{jti}"
    cached = redis_client().get(cache_key)
    if not cached:
        return None
    try:
        cached_payload = json.loads(cached)
    except json.JSONDecodeError:
        return None
    if cached_payload.get("userId") != user_id:
        return None
    if not hmac.compare_digest(cached_payload.get("tokenHash", ""), hash_token(token)):
        return None

    user = load_user(user_id)
    if not user:
        return None
    redis_client().expire(cache_key, settings.jwt_ttl_seconds)
    request.state.user = user
    request.state.jwt_jti = jti
    return user


def require_user(user: UserProfile | None = Depends(get_optional_user)) -> UserProfile:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def revoke_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    if not credentials or credentials.scheme.lower() != "bearer":
        return
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=[TOKEN_ALGORITHM],
            options={"verify_exp": False},
        )
    except InvalidTokenError:
        return
    jti = payload.get("jti")
    if jti:
        redis_client().delete(f"{TOKEN_KEY_PREFIX}{jti}")


def demo_user_id() -> str:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE email = 'system@yahaha.local' LIMIT 1"
        ).fetchone()
    return str(row["id"])
