"""Google OAuth 2.0 helpers: authorization URL, state tokens, code exchange."""

import secrets
import logging
from urllib.parse import urlencode

import httpx
import jwt

from config import settings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"


def generate_state_token() -> str:
    """Generate a random CSRF state token."""
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    """Build the Google OAuth 2.0 authorization URL."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_user_info(code: str) -> dict:
    """Exchange an authorization code for user info from Google.

    Performs a server-to-server token exchange, then decodes the id_token
    to extract user claims (sub, email, name, picture, email_verified).

    Returns:
        dict with keys: sub, email, name, picture, email_verified

    Raises:
        ValueError: If the token exchange fails or id_token is invalid.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        logger.error("Google token exchange failed: %s %s", response.status_code, response.text)
        raise ValueError("Failed to exchange authorization code with Google")

    token_data = response.json()
    id_token = token_data.get("id_token")
    if not id_token:
        raise ValueError("No id_token in Google token response")

    # Decode id_token without verification — we trust it because we just received
    # it directly from Google over HTTPS in a server-to-server exchange using our
    # client_secret. The client_secret proves this token was issued for us.
    claims = jwt.decode(id_token, options={"verify_signature": False})

    required_fields = ["sub", "email"]
    for field in required_fields:
        if field not in claims:
            raise ValueError(f"Missing '{field}' in Google id_token")

    return {
        "sub": claims["sub"],
        "email": claims["email"],
        "name": claims.get("name"),
        "picture": claims.get("picture"),
        "email_verified": claims.get("email_verified", False),
    }
