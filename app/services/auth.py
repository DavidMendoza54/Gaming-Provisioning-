from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiToken, User
from app.schemas import LoginRequest, RegisterRequest


password_context = CryptContext(schemes=["argon2"], deprecated="auto")


@dataclass(frozen=True)
class IssuedToken:
    raw_token: str
    api_token: ApiToken


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return password_context.verify(password, password_hash)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def register_user(session: Session, payload: RegisterRequest) -> User:
    email = normalize_email(payload.email)
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ValueError("Email is already registered")

    user = User(email=email, password_hash=hash_password(payload.password), role="user")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session: Session, payload: LoginRequest) -> User | None:
    email = normalize_email(payload.email)
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        return None
    return user


def issue_token(session: Session, user: User, *, name: str = "default") -> IssuedToken:
    raw_token = secrets.token_urlsafe(32)
    api_token = ApiToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        name=name,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(api_token)
    session.commit()
    session.refresh(api_token)
    return IssuedToken(raw_token=raw_token, api_token=api_token)


def get_user_by_token(session: Session, raw_token: str) -> User | None:
    token_hash = hash_token(raw_token)
    api_token = session.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash))
    if api_token is None or api_token.revoked_at is not None:
        return None

    now = datetime.now(UTC)
    expires_at = api_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None

    api_token.last_used_at = now
    session.commit()
    return session.get(User, api_token.user_id)

