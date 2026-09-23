from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .database import get_session
from .errors import APIError
from .models import AccessToken, User
from .security import hash_access_token, issue_access_token, verify_password
from .time_utils import utcnow

bearer_scheme = HTTPBearer(auto_error=False)


def authenticate(
    session: Session, email: str, password: str, settings: Settings
) -> tuple[str, AccessToken, User]:
    normalized_email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized_email))
    if (
        user is None
        or user.status != "active"
        or not verify_password(password, user.password_hash)
    ):
        raise APIError(401, "invalid_credentials", "Email or password is incorrect.")

    raw_token = issue_access_token()
    token = AccessToken(
        user_id=user.id,
        token_hash=hash_access_token(raw_token),
        expires_at=utcnow() + timedelta(hours=settings.token_ttl_hours),
    )
    session.add(token)
    session.commit()
    return raw_token, token, user


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "authentication_required", "A bearer token is required.")

    token = session.scalar(
        select(AccessToken).where(
            AccessToken.token_hash == hash_access_token(credentials.credentials)
        )
    )
    if (
        token is None
        or token.revoked_at is not None
        or token.expires_at <= utcnow()
    ):
        raise APIError(401, "invalid_token", "The access token is invalid or expired.")

    user = session.get(User, token.user_id)
    if user is None or user.status != "active":
        raise APIError(401, "inactive_user", "The user account is not active.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[Session, Depends(get_session)]

