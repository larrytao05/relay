import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from asyncpg import UniqueViolationError
from fastapi import HTTPException, Response
from starlette.requests import Request

from app import auth, canvases


class MemoryDatabase:
    def __init__(self) -> None:
        self.users_by_username: dict[str, dict] = {}
        self.users_by_id: dict[UUID, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.canvases: dict[UUID, dict] = {}
        self.canvas_members: set[tuple[UUID, UUID]] = set()
        self.canvas_invitations: dict[tuple[UUID, UUID], UUID] = {}


class MemoryConnection:
    def __init__(self, database: MemoryDatabase) -> None:
        self.database = database

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, query: str, *args):
        if query.lstrip().startswith("INSERT INTO app_user"):
            username, password_hash = args
            if username in self.database.users_by_username:
                raise UniqueViolationError("duplicate username")
            user = {"id": uuid4(), "username": username, "password_hash": password_hash}
            self.database.users_by_username[username] = user
            self.database.users_by_id[user["id"]] = user
            return user.copy()

        if query.lstrip().startswith("INSERT INTO canvas"):
            title, created_by = args
            canvas = {
                "id": uuid4(),
                "title": title,
                "created_by": created_by,
                "revision": 0,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            self.database.canvases[canvas["id"]] = canvas
            return canvas.copy()

        if "FROM canvas\n" in query and "JOIN canvas_member" in query:
            canvas_id, user_id = args
            canvas = self.database.canvases.get(canvas_id)
            if canvas and (canvas_id, user_id) in self.database.canvas_members:
                return canvas.copy()
            return None

        if "FROM canvas_invitation" in query and "FOR UPDATE" in query:
            key = (args[0], args[1])
            if key in self.database.canvas_invitations:
                return {"canvas_id": key[0], "invitee_id": key[1]}
            return None

        if query.lstrip().startswith("SELECT id, username FROM app_user"):
            user = self.database.users_by_username.get(args[0])
            return {"id": user["id"], "username": user["username"]} if user else None

        if "FROM app_user WHERE username = $1" in query:
            user = self.database.users_by_username.get(args[0])
            return user.copy() if user else None

        if "FROM auth_session" in query:
            session = self.database.sessions.get(args[0])
            if session is None or session["expires_at"] <= datetime.now(UTC):
                return None
            user = self.database.users_by_id[session["user_id"]]
            return {"id": user["id"], "username": user["username"]}

        raise AssertionError(f"Unexpected query: {query}")

    async def fetch(self, query: str, *args):
        if "FROM canvas\n" in query and "canvas_member.user_id = $1" in query:
            user_id = args[0]
            memberships = [
                {
                    **self.database.canvases[canvas_id],
                    "access": "member",
                    "invited_by": None,
                }
                for canvas_id, member_id in self.database.canvas_members
                if member_id == user_id
            ]
            invitations = [
                {
                    **self.database.canvases[canvas_id],
                    "access": "pending",
                    "invited_by": self.database.users_by_id[invited_by]["username"],
                }
                for (
                    canvas_id,
                    invitee_id,
                ), invited_by in self.database.canvas_invitations.items()
                if invitee_id == user_id
            ]
            return invitations + memberships

        if "FROM canvas_member\n" in query:
            canvas_id = args[0]
            members = [
                self.database.users_by_id[user_id]
                for member_canvas_id, user_id in self.database.canvas_members
                if member_canvas_id == canvas_id
            ]
            return [
                {"id": member["id"], "username": member["username"]}
                for member in sorted(members, key=lambda member: member["username"])
            ]

        raise AssertionError(f"Unexpected query: {query}")

    async def fetchval(self, query: str, *args):
        if query.strip() == "SELECT set_config('lock_timeout', $1, true)":
            return args[0]

        if "SELECT EXISTS" in query:
            return (args[0], args[1]) in self.database.canvas_members
        raise AssertionError(f"Unexpected query: {query}")

    async def execute(self, query: str, *args) -> str:
        if query.lstrip().startswith("INSERT INTO auth_session"):
            token_hash, user_id = args
            self.database.sessions[token_hash] = {
                "user_id": user_id,
                "expires_at": datetime.now(UTC) + timedelta(days=14),
            }
            return "INSERT 0 1"

        if query.lstrip().startswith("INSERT INTO canvas_member"):
            self.database.canvas_members.add((args[0], args[1]))
            return "INSERT 0 1"

        if query.lstrip().startswith("INSERT INTO canvas_invitation"):
            self.database.canvas_invitations.setdefault((args[0], args[1]), args[2])
            return "INSERT 0 1"

        if query.lstrip().startswith("DELETE FROM canvas_invitation"):
            self.database.canvas_invitations.pop((args[0], args[1]), None)
            return "DELETE 1"

        if query.lstrip().startswith("DELETE FROM auth_session"):
            self.database.sessions.pop(args[0], None)
            return "DELETE 1"

        raise AssertionError(f"Unexpected query: {query}")


class MemoryPool:
    def __init__(self, database: MemoryDatabase) -> None:
        self.connection = MemoryConnection(database)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class EndpointHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = MemoryDatabase()
        self.pool = MemoryPool(self.database)
        self.get_pool_patch = patch(
            "app.auth.get_pool", new_callable=AsyncMock, return_value=self.pool
        )
        self.get_pool_patch.start()
        self.addCleanup(self.get_pool_patch.stop)
        self.canvases_pool_patch = patch(
            "app.canvases.get_pool", new_callable=AsyncMock, return_value=self.pool
        )
        self.canvases_pool_patch.start()
        self.addCleanup(self.canvases_pool_patch.stop)

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def signup(self, username: str = "alice", password: str = "password123"):
        response = Response()
        result = self.run_async(
            auth.signup(
                auth.Credentials(username=username, password=password), response
            )
        )
        cookie = SimpleCookie()
        cookie_header = response.headers["set-cookie"]
        cookie.load(cookie_header)
        self.assertIn("httponly", cookie_header.lower())
        self.assertIn("samesite=lax", cookie_header.lower())
        self.assertIn("path=/", cookie_header.lower())
        self.assertIn("max-age=1209600", cookie_header.lower())
        return result, cookie[auth.SESSION_COOKIE_NAME].value

    def test_signup_normalizes_username_hashes_password_and_stores_only_token_digest(
        self,
    ):
        result, token = self.signup(username=" Alice ")

        self.assertEqual(result.user.username, "alice")
        user = self.database.users_by_username["alice"]
        self.assertNotEqual(user["password_hash"], "password123")
        self.assertTrue(auth.verify_password("password123", user["password_hash"]))

        token_hash = auth.hash_session_token(token)
        self.assertIn(token_hash, self.database.sessions)
        self.assertNotIn(token, self.database.sessions)

        with self.assertRaises(HTTPException) as duplicate:
            self.run_async(
                auth.signup(
                    auth.Credentials(username="alice", password="password123"),
                    Response(),
                )
            )
        self.assertEqual(duplicate.exception.status_code, 409)

    def test_login_succeeds_and_uses_one_error_for_unknown_or_wrong_password(self):
        self.signup()

        response = Response()
        result = self.run_async(
            auth.login(
                auth.Credentials(username="ALICE", password="password123"), response
            )
        )
        self.assertEqual(result.user.username, "alice")
        self.assertIn("session=", response.headers["set-cookie"])

        errors = []
        for username, password in (
            ("alice", "incorrect123"),
            ("unknown", "incorrect123"),
        ):
            with (
                self.subTest(username=username),
                self.assertRaises(HTTPException) as raised,
            ):
                self.run_async(
                    auth.login(
                        auth.Credentials(username=username, password=password),
                        Response(),
                    )
                )
            errors.append((raised.exception.status_code, raised.exception.detail))

        self.assertEqual(errors, [(401, "Invalid username or password.")] * 2)

    def test_current_user_requires_an_active_session_and_logout_revokes_it(self):
        with self.assertRaises(HTTPException) as missing:
            self.run_async(auth.current_user(session_token=None))
        self.assertEqual(missing.exception.status_code, 401)

        _, token = self.signup()

        current = self.run_async(auth.current_user(session_token=token))
        self.assertEqual(current.user.username, "alice")

        token_hash = auth.hash_session_token(token)
        self.database.sessions[token_hash]["expires_at"] = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        with self.assertRaises(HTTPException) as expired:
            self.run_async(auth.current_user(session_token=token))
        self.assertEqual(expired.exception.status_code, 401)

        logout_response = Response()
        request = Request(
            {"type": "http", "app": SimpleNamespace(state=SimpleNamespace())}
        )
        self.run_async(
            auth.logout(logout_response, request=request, session_token=token)
        )
        self.assertEqual(logout_response.status_code, 204)
        self.assertNotIn(token_hash, self.database.sessions)
        self.assertIn('session=""', logout_response.headers["set-cookie"])

        # Logout is safe to repeat, including after the session has been removed.
        self.run_async(auth.logout(Response(), request=request, session_token=token))
        with self.assertRaises(HTTPException):
            self.run_async(auth.current_user(session_token=token))

    def test_create_canvas_adds_creator_and_lists_memberships(self):
        user, _ = self.signup()

        created = self.run_async(
            canvases.create_canvas(
                canvases.CanvasCreateRequest(title="  Design review  "), user.user
            )
        )
        listed = self.run_async(canvases.list_canvases(user.user))

        self.assertEqual(created.canvas.title, "Design review")
        self.assertIn((created.canvas.id, user.user.id), self.database.canvas_members)
        self.assertEqual(
            [entry.canvas.id for entry in listed.canvases], [created.canvas.id]
        )
        self.assertEqual(listed.canvases[0].status, "member")

    def test_invitation_stays_pending_until_accepted_and_can_be_declined(self):
        owner, _ = self.signup(username="owner")
        invited, _ = self.signup(username="invitee")
        canvas = self.run_async(
            canvases.create_canvas(
                canvases.CanvasCreateRequest(title="Team board"), owner.user
            )
        ).canvas
        member_canvas = self.run_async(
            canvases.create_canvas(
                canvases.CanvasCreateRequest(title="Member board"), owner.user
            )
        ).canvas
        self.database.canvas_members.add((member_canvas.id, invited.user.id))

        invitation = self.run_async(
            canvases.create_canvas_invitation(
                canvas.id,
                canvases.InviteRequest(username=" INVITEE "),
                owner.user,
            )
        )
        listed = self.run_async(canvases.list_canvases(invited.user))
        repeated = self.run_async(
            canvases.create_canvas_invitation(
                canvas.id,
                canvases.InviteRequest(username="invitee"),
                owner.user,
            )
        )

        self.assertEqual(invitation["user"].id, invited.user.id)
        self.assertEqual(repeated["user"].id, invited.user.id)
        self.assertEqual(
            [entry.status for entry in listed.canvases], ["pending", "member"]
        )
        self.assertEqual(listed.canvases[0].invited_by, owner.user.username)
        self.assertNotIn((canvas.id, invited.user.id), self.database.canvas_members)

        with self.assertRaises(HTTPException) as denied:
            self.run_async(canvases.get_canvas(canvas.id, invited.user))
        self.assertEqual(denied.exception.status_code, 404)

        self.run_async(canvases.accept_canvas_invitation(canvas.id, invited.user))
        self.assertNotIn((canvas.id, invited.user.id), self.database.canvas_invitations)
        opened = self.run_async(canvases.get_canvas(canvas.id, invited.user))
        self.assertEqual(
            {member.id for member in opened.members}, {owner.user.id, invited.user.id}
        )
        self.run_async(canvases.accept_canvas_invitation(canvas.id, invited.user))

        other, _ = self.signup(username="other")
        self.run_async(
            canvases.create_canvas_invitation(
                canvas.id, canvases.InviteRequest(username="other"), owner.user
            )
        )
        self.run_async(canvases.decline_canvas_invitation(canvas.id, other.user))
        self.assertNotIn((canvas.id, other.user.id), self.database.canvas_invitations)
        with self.assertRaises(HTTPException) as declined:
            self.run_async(canvases.accept_canvas_invitation(canvas.id, other.user))
        self.assertEqual(declined.exception.status_code, 404)

        outsider = auth.PublicUser(id=uuid4(), username="outsider")
        with self.assertRaises(HTTPException) as denied:
            self.run_async(canvases.get_canvas(canvas.id, outsider))
        self.assertEqual(denied.exception.status_code, 404)

        with self.assertRaises(HTTPException) as unauthorized_add:
            self.run_async(
                canvases.create_canvas_invitation(
                    canvas.id,
                    canvases.InviteRequest(username="invitee"),
                    outsider,
                )
            )
        self.assertEqual(unauthorized_add.exception.status_code, 404)

        with self.assertRaises(HTTPException) as missing_invitee:
            self.run_async(
                canvases.create_canvas_invitation(
                    canvas.id,
                    canvases.InviteRequest(username="unknown"),
                    owner.user,
                )
            )
        self.assertEqual(missing_invitee.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
