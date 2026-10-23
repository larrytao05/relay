from datetime import datetime
from typing import Annotated
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


class MemberRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def normalize_member_username(cls, username: str) -> str:
        return normalize_username(username)


class CanvasResponse(BaseModel):
    canvas: Canvas


class CanvasListResponse(BaseModel):
    canvases: list[Canvas]


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
                   canvas.created_at, canvas.updated_at
            FROM canvas
            JOIN canvas_member ON canvas_member.canvas_id = canvas.id
            WHERE canvas_member.user_id = $1
            ORDER BY canvas.updated_at DESC, canvas.id
            """,
            user.id,
        )
    return CanvasListResponse(canvases=[_canvas(row) for row in rows])


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
    "/{canvas_id}/members", response_model=UserResponse, status_code=status.HTTP_200_OK
)
async def add_canvas_member(
    canvas_id: UUID,
    request: MemberRequest,
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
        await conn.execute(
            """
            INSERT INTO canvas_member (canvas_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT (canvas_id, user_id) DO NOTHING
            """,
            canvas_id,
            invitee["id"],
        )
    return {"user": PublicUser.model_validate(dict(invitee))}
