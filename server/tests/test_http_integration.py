"""Optional HTTP integration test requiring a migrated Postgres test database."""

import asyncio
import os
import unittest
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app import db
from app.auth import SESSION_COOKIE_NAME
from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class HttpPostgresIntegrationTests(unittest.TestCase):
    def test_authentication_and_canvas_access_over_http(self):
        database_url = os.environ["TEST_DATABASE_URL"]
        previous_database_url = db.DATABASE_URL
        usernames = [f"test_{uuid4().hex[:20]}", f"test_{uuid4().hex[:20]}"]
        owner_username, member_username = usernames
        db.DATABASE_URL = database_url

        try:
            with TestClient(app) as client:
                owner_signup = client.post(
                    "/api/auth/signup",
                    json={"username": owner_username, "password": "owner-password"},
                )
                self.assertEqual(owner_signup.status_code, 201)
                self.assertIn(SESSION_COOKIE_NAME, owner_signup.cookies)

                member_signup = client.post(
                    "/api/auth/signup",
                    json={"username": member_username, "password": "member-password"},
                )
                self.assertEqual(member_signup.status_code, 201)
                member_token = member_signup.cookies[SESSION_COOKIE_NAME]

                # Authentication is enforced on protected routes.
                client.cookies.clear()
                self.assertEqual(client.get("/api/canvases").status_code, 401)

                # Login establishes a session cookie that /me accepts.
                login = client.post(
                    "/api/auth/login",
                    json={"username": owner_username, "password": "owner-password"},
                )
                self.assertEqual(login.status_code, 200)
                self.assertEqual(
                    client.get("/api/auth/me").json()["user"]["username"],
                    owner_username,
                )
                owner_token = login.cookies[SESSION_COOKIE_NAME]

                created = client.post(
                    "/api/canvases", json={"title": "Integration board"}
                )
                self.assertEqual(created.status_code, 201)
                canvas_id = created.json()["canvas"]["id"]
                self.assertEqual(len(client.get("/api/canvases").json()["canvases"]), 1)

                # A signed-in nonmember cannot read the canvas before being added.
                client.cookies.clear()
                client.cookies.set(SESSION_COOKIE_NAME, member_token)
                self.assertEqual(
                    client.get("/api/auth/me").json()["user"]["username"],
                    member_username,
                )
                self.assertEqual(
                    client.get(f"/api/canvases/{canvas_id}").status_code, 404
                )

                # The owner can add an existing user; membership then grants access.
                client.cookies.clear()
                client.cookies.set(SESSION_COOKIE_NAME, owner_token)
                added = client.post(
                    f"/api/canvases/{canvas_id}/members",
                    json={"username": member_username},
                )
                self.assertEqual(added.status_code, 200)
                self.assertEqual(added.json()["user"]["username"], member_username)

                client.cookies.clear()
                client.cookies.set(SESSION_COOKIE_NAME, member_token)
                detail = client.get(f"/api/canvases/{canvas_id}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(
                    {item["username"] for item in detail.json()["members"]},
                    {owner_username, member_username},
                )

                # Logout revokes the session and clears its cookie.
                logout = client.post("/api/auth/logout")
                self.assertIn('session=""', logout.headers["set-cookie"])
                self.assertEqual(client.get("/api/auth/me").status_code, 401)
        finally:
            db.DATABASE_URL = previous_database_url
            asyncio.run(self._delete_test_rows(database_url, usernames))

    @staticmethod
    async def _delete_test_rows(database_url: str, usernames: list[str]) -> None:
        conn = await asyncpg.connect(database_url)
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    DELETE FROM canvas
                    WHERE created_by IN (
                        SELECT id FROM app_user WHERE username = ANY($1::text[])
                    )
                    """,
                    usernames,
                )
                await conn.execute(
                    "DELETE FROM app_user WHERE username = ANY($1::text[])", usernames
                )
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
