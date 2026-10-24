import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from asyncpg import LockNotAvailableError, UniqueViolationError
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from app.canvas_operation_listener import publish_transient_event
from app.db import get_pool

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "session"
SESSION_LIFETIME = timedelta(days=14)
SESSION_MAX_AGE = int(SESSION_LIFETIME.total_seconds())
SCRYPT_COST = 2**14
SCRYPT_BLOCK_SIZE = 8
SCRYPT_PARALLELISM = 1
SCRYPT_KEY_LENGTH = 64
_LOGOUT_LOCK_TIMEOUT = "5s"
USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]{3,32}$")


class Credentials(BaseModel):
    username: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, username: str) -> str:
        return normalize_username(username)


class PublicUser(BaseModel):
    id: UUID
    username: str


class UserResponse(BaseModel):
    user: PublicUser


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_COST,
        r=SCRYPT_BLOCK_SIZE,
        p=SCRYPT_PARALLELISM,
        dklen=SCRYPT_KEY_LENGTH,
        maxmem=64 * 1024 * 1024,
    )
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_COST),
            str(SCRYPT_BLOCK_SIZE),
            str(SCRYPT_PARALLELISM),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived_key).decode("ascii"),
        )
    )


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Username must be 3-32 characters using letters, numbers, _ or -."
        )
    return normalized


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, cost, block_size, parallelism, salt_text, key_text = (
            encoded_hash.split("$")
        )
        if algorithm != "scrypt":
            return False
        n, r, p = int(cost), int(block_size), int(parallelism)
        # Bound parameters before hashing in case a stored hash is malformed.
        if n != SCRYPT_COST or r != SCRYPT_BLOCK_SIZE or p != SCRYPT_PARALLELISM:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected_key = base64.urlsafe_b64decode(key_text.encode("ascii"))
        if len(salt) != 16 or len(expected_key) != SCRYPT_KEY_LENGTH:
            return False
        actual_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected_key),
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, UnicodeError, TypeError):
        return False
    return hmac.compare_digest(actual_key, expected_key)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secure_cookie() -> bool:
    return os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )


def _public_user(row: Any) -> PublicUser:
    return PublicUser(id=row["id"], username=row["username"])


async def _create_session(conn: Any, user_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    await conn.execute(
        """
        INSERT INTO auth_session (token_hash, user_id, expires_at)
        VALUES ($1, $2, now() + interval '14 days')
        """,
        hash_session_token(token),
        user_id,
    )
    return token


@router.post(
    "/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def signup(credentials: Credentials, response: Response) -> UserResponse:
    pool = await get_pool()
    password_hash = hash_password(credentials.password)
    try:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO app_user (username, password_hash)
                VALUES ($1, $2)
                RETURNING id, username
                """,
                credentials.username,
                password_hash,
            )
            token = await _create_session(conn, row["id"])
    except UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken.",
        ) from exc

    _set_session_cookie(response, token)
    return UserResponse(user=_public_user(row))


@router.post("/login", response_model=UserResponse)
async def login(credentials: Credentials, response: Response) -> UserResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, password_hash FROM app_user WHERE username = $1",
            credentials.username,
        )
        # Do a password derivation for unknown accounts too, reducing username
        # enumeration through response timing.
        if row is None:
            verify_password(credentials.password, _DUMMY_PASSWORD_HASH)
            valid = False
        else:
            valid = verify_password(credentials.password, row["password_hash"])
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        token = await _create_session(conn, row["id"])

    _set_session_cookie(response, token)
    return UserResponse(user=_public_user(row))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Response:
    if session_token:
        token_hash = hash_session_token(session_token)
        pool = await get_pool()
        rooms = getattr(request.app.state, "canvas_rooms", None)
        try:
            async with pool.acquire() as conn, conn.transaction():
                await conn.fetchval(
                    "SELECT set_config('lock_timeout', $1, true)",
                    _LOGOUT_LOCK_TIMEOUT,
                )
                await conn.execute(
                    "DELETE FROM auth_session WHERE token_hash = $1",
                    token_hash,
                )
                if rooms is not None:
                    await publish_transient_event(
                        conn,
                        {
                            "type": "session.revoked",
                            "process_id": rooms.process_id,
                            "event_id": str(uuid4()),
                            "canvas_id": str(UUID(int=0)),
                            "token_hash": token_hash,
                        },
                    )
        except LockNotAvailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Logout could not be completed. Please try again.",
            ) from exc
        if rooms is not None:
            try:
                await rooms.revoke_session(token_hash)
            except Exception:
                logger.exception("Local WebSocket revocation failed after logout")
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


async def _load_current_user(session_token: str | None) -> PublicUser:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT app_user.id, app_user.username
            FROM auth_session
            JOIN app_user ON app_user.id = auth_session.user_id
            WHERE auth_session.token_hash = $1
              AND auth_session.expires_at > now()
            """,
            hash_session_token(session_token),
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return _public_user(row)


async def require_authenticated_user(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> PublicUser:
    return await _load_current_user(session_token)


@router.get("/me", response_model=UserResponse)
async def current_user(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> UserResponse:
    return UserResponse(user=await _load_current_user(session_token))


_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")
