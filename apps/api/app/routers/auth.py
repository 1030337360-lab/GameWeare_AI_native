import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from psycopg.errors import UniqueViolation

from app.config import get_settings
from app.database import db_connection
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, SessionState, UserProfile
from app.services.auth_service import (
    GOOGLE_STATE_KEY_PREFIX,
    get_optional_user,
    hash_password,
    issue_auth_response,
    redis_client,
    require_user,
    revoke_token,
    serialize_user,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    normalized_email = payload.email.strip().lower()
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    display_name = payload.displayName or normalized_email.split("@", 1)[0]
    try:
        with db_connection() as connection:
            user = connection.execute(
                """
INSERT INTO users (email, display_name)
VALUES (%s, %s)
RETURNING id, email, display_name, avatar_url, role
""",
                (normalized_email, display_name),
            ).fetchone()
            connection.execute(
                """
INSERT INTO auth_accounts (user_id, provider, provider_user_id, provider_email, password_hash)
VALUES (%s, 'email', %s, %s, %s)
""",
                (user["id"], normalized_email, normalized_email, hash_password(payload.password)),
            )
            connection.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user["id"],))
            user["last_login_at"] = None
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Email already registered") from exc

    return issue_auth_response(serialize_user(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    normalized_email = payload.email.strip().lower()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT
  u.id,
  u.email,
  u.display_name,
  u.avatar_url,
  u.role,
  u.last_login_at,
  aa.password_hash
FROM auth_accounts aa
JOIN users u ON u.id = aa.user_id
WHERE
  aa.provider = 'email'
  AND aa.provider_email = %s
  AND u.status = 'active'
LIMIT 1
""",
            (normalized_email,),
        ).fetchone()

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    with db_connection() as connection:
        connection.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (row["id"],))
    return issue_auth_response(serialize_user(row))


@router.post("/logout", response_model=SessionState)
def logout(_: None = Depends(revoke_token)) -> SessionState:
    return SessionState(authenticated=False, user=None)


@router.get("/session", response_model=SessionState)
def session(user: UserProfile | None = Depends(get_optional_user)) -> SessionState:
    return SessionState(authenticated=bool(user), user=user)


@router.get("/google/start")
def google_start() -> RedirectResponse:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        return RedirectResponse(f"{settings.web_base_url}/auth/login?oauth_error=google_not_configured")

    state = secrets.token_urlsafe(24)
    redis_client().setex(f"{GOOGLE_STATE_KEY_PREFIX}{state}", 600, "1")
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@router.get("/google/callback")
async def google_callback(code: str, state: str) -> RedirectResponse:
    settings = get_settings()
    state_key = f"{GOOGLE_STATE_KEY_PREFIX}{state}"
    if not redis_client().get(state_key):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    redis_client().delete(state_key)

    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        user_response = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token_payload['access_token']}"},
        )
        user_response.raise_for_status()
        google_user = user_response.json()

    provider_user_id = google_user["sub"]
    provider_email = google_user.get("email")
    display_name = google_user.get("name") or (provider_email.split("@", 1)[0] if provider_email else "Google user")
    avatar_url = google_user.get("picture")

    with db_connection() as connection:
        existing = connection.execute(
            """
SELECT u.id, u.email, u.display_name, u.avatar_url, u.role, u.last_login_at
FROM auth_accounts aa
JOIN users u ON u.id = aa.user_id
WHERE aa.provider = 'google' AND aa.provider_user_id = %s
LIMIT 1
""",
            (provider_user_id,),
        ).fetchone()
        if existing:
            user_row = existing
            connection.execute(
                "UPDATE users SET last_login_at = now(), avatar_url = COALESCE(%s, avatar_url) WHERE id = %s",
                (avatar_url, user_row["id"]),
            )
        else:
            user_row = connection.execute(
                """
INSERT INTO users (email, display_name, avatar_url)
VALUES (%s, %s, %s)
ON CONFLICT (email) DO UPDATE SET
  display_name = COALESCE(users.display_name, EXCLUDED.display_name),
  avatar_url = COALESCE(EXCLUDED.avatar_url, users.avatar_url)
RETURNING id, email, display_name, avatar_url, role, last_login_at
""",
                (provider_email, display_name, avatar_url),
            ).fetchone()
            existing_google = connection.execute(
                """
SELECT id
FROM auth_accounts
WHERE provider = 'google' AND provider_user_id = %s
LIMIT 1
""",
                (provider_user_id,),
            ).fetchone()
            if existing_google:
                connection.execute(
                    """
UPDATE auth_accounts
SET
  provider_email = %s,
  access_token_encrypted = %s,
  refresh_token_encrypted = COALESCE(%s, refresh_token_encrypted),
  expires_at = now() + (%s || ' seconds')::interval
WHERE id = %s
""",
                    (
                        provider_email,
                        token_payload.get("access_token"),
                        token_payload.get("refresh_token"),
                        token_payload.get("expires_in", 3600),
                        existing_google["id"],
                    ),
                )
            else:
                connection.execute(
                    """
INSERT INTO auth_accounts (
  user_id,
  provider,
  provider_user_id,
  provider_email,
  access_token_encrypted,
  refresh_token_encrypted,
  expires_at
)
VALUES (%s, 'google', %s, %s, %s, %s, now() + (%s || ' seconds')::interval)
""",
                    (
                        user_row["id"],
                        provider_user_id,
                        provider_email,
                        token_payload.get("access_token"),
                        token_payload.get("refresh_token"),
                        token_payload.get("expires_in", 3600),
                    ),
                )
            connection.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_row["id"],))

    auth = issue_auth_response(serialize_user(user_row))
    redirect_url = f"{settings.web_base_url}/auth/callback#access_token={auth.accessToken}"
    return RedirectResponse(redirect_url)
