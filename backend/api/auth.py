"""Authentication endpoints: register, login, token refresh, Google OAuth."""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.requests import Request
from passlib.hash import bcrypt
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user_id,
)
from auth.google import (
    build_authorization_url,
    generate_state_token,
    exchange_code_for_user_info,
)
from models import User, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

OAUTH_STATE_COOKIE = "oauth_state"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    has_password: bool = True


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=body.email, hashed_password=bcrypt.hash(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email and password."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses Google sign-in. Please sign in with Google.",
        )

    if not bcrypt.verify(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    """Exchange a refresh token for new access + refresh tokens."""
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current user info."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        has_password=user.hashed_password is not None,
    )


# ---------------------------------------------------------------------------
# Google OAuth 2.0
# ---------------------------------------------------------------------------


@router.get("/google/login")
async def google_login():
    """Redirect user to Google OAuth consent screen."""
    state = generate_state_token()
    url = build_authorization_url(state)

    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=600,  # 10 minutes
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback: validate state, exchange code, issue tokens."""
    frontend_login = "/login"

    # Google returned an error (user denied, etc.)
    if error:
        return RedirectResponse(url=f"{frontend_login}?error={error}")

    if not code or not state:
        return RedirectResponse(url=f"{frontend_login}?error=missing_params")

    # CSRF validation
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not cookie_state or cookie_state != state:
        return RedirectResponse(url=f"{frontend_login}?error=invalid_state")

    # Exchange code for user info
    try:
        google_user = await exchange_code_for_user_info(code)
    except ValueError as exc:
        logger.error("Google OAuth code exchange failed: %s", exc)
        return RedirectResponse(url=f"{frontend_login}?error=exchange_failed")

    if not google_user.get("email_verified"):
        return RedirectResponse(url=f"{frontend_login}?error=email_not_verified")

    google_id = google_user["sub"]
    email = google_user["email"].lower()
    display_name = google_user.get("name")
    avatar_url = google_user.get("picture")

    # Find or create user
    # 1. Lookup by google_id (returning Google user)
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        # 2. Lookup by email (link existing email/password account)
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            # Link Google to existing account
            user.google_id = google_id
            if display_name and not user.display_name:
                user.display_name = display_name
            if avatar_url and not user.avatar_url:
                user.avatar_url = avatar_url
        else:
            # 3. Create new user (Google-only, no password)
            user = User(
                email=email,
                hashed_password=None,
                google_id=google_id,
                display_name=display_name,
                avatar_url=avatar_url,
            )
            db.add(user)

    else:
        # Update profile info from Google on each login
        if display_name:
            user.display_name = display_name
        if avatar_url:
            user.avatar_url = avatar_url

    await db.commit()
    await db.refresh(user)

    # Issue JWT tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    # Redirect to frontend callback page with tokens
    from urllib.parse import urlencode
    params = urlencode({"access_token": access_token, "refresh_token": refresh_token})
    redirect_url = f"/auth/google/callback?{params}"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    # Clear the state cookie
    response.delete_cookie(key=OAUTH_STATE_COOKIE)
    return response
