from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth import (
    PublicUser,
    UserResponse,
    normalize_username,
    require_authenticated_user,
)
from app.db import get_pool

router = APIRouter(prefix="/api/canvases", tags=["canvases"])


class Canvas(BaseModel):
    id: UUID
    title: str
    created_by: UUID
    revision: int
    created_at: datetime
    updated_at: datetime


class CanvasCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, title: object) -> object:
        return title.strip() if isinstance(title, str) else title


class InviteRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def normalize_member_username(cls, username: str) -> str:
        return normalize_username(username)


class CanvasResponse(BaseModel):
    canvas: Canvas


class MemberCanvasListEntry(BaseModel):
    canvas: Canvas
    status: Literal["member"]
    invited_by: None = None


class PendingCanvasListEntry(BaseModel):
    canvas: Canvas
    status: Literal["pending"]
    invited_by: str


CanvasListEntry = Annotated[
    MemberCanvasListEntry | PendingCanvasListEntry, Field(discriminator="status")
]


class CanvasListResponse(BaseModel):
    canvases: list[CanvasListEntry]


class CanvasDetailResponse(BaseModel):
    canvas: Canvas
    members: list[PublicUser]


def _canvas(row: object) -> Canvas:
    return Canvas.model_validate(dict(row))


@router.get("", response_model=CanvasListResponse)
async def list_canvases(
    user: Annotated[PublicUser, Depends(require_authenticated_user)],
) -> CanvasListResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT canvas.id, canvas.title, canvas.created_by, canvas.revision,
                   canvas.created_at, canvas.updated_at, 'member' AS access,
                   NULL::text AS invited_by, 1 AS access_order
            FROM canvas
            JOIN canvas_member ON canvas_member.canvas_id = canvas.id
            WHERE canvas_member.user_id = $1
            UNION ALL
            SELECT canvas.id, canvas.title, canvas.created_by, canvas.revision,
                   canvas.created_at, canvas.updated_at, 'pending' AS access,
                   inviter.username AS invited_by, 0 AS access_order
            FROM canvas_invitation
            JOIN canvas ON canvas.id = canvas_invitation.canvas_id
            JOIN app_user AS inviter ON inviter.id = canvas_invitation.invited_by
            WHERE canvas_invitation.invitee_id = $1
            ORDER BY access_order, updated_at DESC, id
            """,
            user.id,
        )
    return CanvasListResponse(
        canvases=[
            PendingCanvasListEntry(
                canvas=_canvas(row), status="pending", invited_by=row["invited_by"]
            )
            if row["access"] == "pending"
            else MemberCanvasListEntry(canvas=_canvas(row), status="member")
            for row in rows
        ]
    )


@router.post("", response_model=CanvasResponse, status_code=status.HTTP_201_CREATED)
async def create_canvas(
    request: CanvasCreateRequest,
    user: Annotated[PublicUser, Depends(require_authenticated_user)],
) -> CanvasResponse:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            INSERT INTO canvas (title, created_by)
            VALUES ($1, $2)
            RETURNING id, title, created_by, revision, created_at, updated_at
            """,
            request.title,
            user.id,
        )
        await conn.execute(
            """
            INSERT INTO canvas_member (canvas_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT (canvas_id, user_id) DO NOTHING
            """,
            row["id"],
            user.id,
        )
    return CanvasResponse(canvas=_canvas(row))


@router.get("/{canvas_id}", response_model=CanvasDetailResponse)
async def get_canvas(
    canvas_id: UUID,
    user: Annotated[PublicUser, Depends(require_authenticated_user)],
) -> CanvasDetailResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT canvas.id, canvas.title, canvas.created_by, canvas.revision,
                   canvas.created_at, canvas.updated_at
            FROM canvas
            JOIN canvas_member ON canvas_member.canvas_id = canvas.id
            WHERE canvas.id = $1 AND canvas_member.user_id = $2
            """,
            canvas_id,
            user.id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Canvas not found."
            )
        member_rows = await conn.fetch(
            """
            SELECT app_user.id, app_user.username
            FROM canvas_member
            JOIN app_user ON app_user.id = canvas_member.user_id
            WHERE canvas_member.canvas_id = $1
            ORDER BY app_user.username
            """,
            canvas_id,
        )
    return CanvasDetailResponse(
        canvas=_canvas(row),
        members=[PublicUser.model_validate(dict(member)) for member in member_rows],
    )


@router.post(
    "/{canvas_id}/invites", response_model=UserResponse, status_code=status.HTTP_200_OK
)
async def create_canvas_invitation(
    canvas_id: UUID,
    request: InviteRequest,
    user: Annotated[PublicUser, Depends(require_authenticated_user)],
) -> dict[str, PublicUser]:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        is_member = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM canvas_member
                WHERE canvas_id = $1 AND user_id = $2
            )
            """,
            canvas_id,
            user.id,
        )
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Canvas not found."
            )

        invitee = await conn.fetchrow(
            "SELECT id, username FROM app_user WHERE username = $1",
            request.username,
        )
        if invitee is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
            )
        is_already_member = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM canvas_member
                WHERE canvas_id = $1 AND user_id = $2
            )
            """,
            canvas_id,
            invitee["id"],
        )
        if is_already_member:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already has access to this canvas.",
            )
        await conn.execute(
            """
            INSERT INTO canvas_invitation (canvas_id, invitee_id, invited_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (canvas_id, invitee_id) DO NOTHING
            """,
            canvas_id,
            invitee["id"],
            user.id,
        )
    return {"user": PublicUser.model_validate(dict(invitee))}


async def _resolve_invitation(canvas_id: UUID, user_id: UUID, *, accept: bool) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        invitation = await conn.fetchrow(
            """
            SELECT canvas_id, invitee_id
            FROM canvas_invitation
            WHERE canvas_id = $1 AND invitee_id = $2
            FOR UPDATE
            """,
            canvas_id,
            user_id,
        )
        if invitation is None:
            is_member = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM canvas_member
                    WHERE canvas_id = $1 AND user_id = $2
                )
                """,
                canvas_id,
                user_id,
            )
            if accept and is_member:
                return
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found.",
            )

        if accept:
            await conn.execute(
                """
                INSERT INTO canvas_member (canvas_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (canvas_id, user_id) DO NOTHING
                """,
                canvas_id,
                user_id,
            )
        await conn.execute(
            """
            DELETE FROM canvas_invitation
            WHERE canvas_id = $1 AND invitee_id = $2
            """,
            canvas_id,
            user_id,
        )


@router.post("/{canvas_id}/invites/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_canvas_invitation(
    canvas_id: UUID,
    user: Annotated[PublicUser, Depends(require_authenticated_user)],
) -> None:
    await _resolve_invitation(canvas_id, user.id, accept=True)


@router.post("/{canvas_id}/invites/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_canvas_invitation(
    canvas_id: UUID,
    user: Annotated[PublicUser, Depends(require_authenticated_user)],
) -> None:
    await _resolve_invitation(canvas_id, user.id, accept=False)
