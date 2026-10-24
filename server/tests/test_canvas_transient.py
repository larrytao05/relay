import asyncio
import json
import unittest
from uuid import uuid4

from app.canvas_transient import CanvasTransientTransport, TransientPeer


class CanvasTransientTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_presence_cursor_dedup_stale_versions_and_room_scoping(self):
        canvas_id = uuid4()
        remote_process, remote_id, user_id = str(uuid4()), str(uuid4()), str(uuid4())
        delivered = []
        has_room = True
        transport = _transport(
            str(uuid4()),
            deliver=lambda _canvas_id, event: _append(delivered, event),
            has_room=lambda _canvas_id: has_room,
        )

        def notification(version, event_type, **fields):
            return json.dumps(
                {
                    "type": event_type,
                    "event_id": str(uuid4()),
                    "process_id": remote_process,
                    "canvas_id": str(canvas_id),
                    "connection_id": remote_id,
                    "version": version,
                    **fields,
                }
            )

        join = notification(
            1,
            "presence.joined",
            user={"id": user_id, "username": "remote"},
        )
        await transport.handle_notification(join)
        await transport.handle_notification(join)
        await transport.handle_notification(
            notification(
                2, "cursor", position=None, user={"id": user_id, "username": "remote"}
            )
        )
        await transport.handle_notification(
            notification(
                1, "presence.joined", user={"id": user_id, "username": "remote"}
            )
        )
        await transport.handle_notification(
            notification(
                3,
                "cursor",
                position={"x": float("nan"), "y": 1},
                user={"id": user_id, "username": "remote"},
            )
        )
        await transport.handle_notification(
            notification(
                4,
                "cursor",
                position={"x": 1, "y": 2, "extra": 3},
                user={"id": user_id, "username": "remote"},
            )
        )
        self.assertEqual(
            delivered,
            [
                {
                    "type": "presence.joined",
                    "connection_id": remote_id,
                    "user": {"id": user_id, "username": "remote"},
                },
                {
                    "type": "cursor",
                    "connection_id": remote_id,
                    "user_id": user_id,
                    "position": None,
                },
            ],
        )

        has_room = False
        await transport.handle_notification(
            notification(
                5,
                "cursor",
                position={"x": 5, "y": 8},
                user={"id": user_id, "username": "remote"},
            )
        )
        self.assertEqual(len(delivered), 2)
        await transport.close()

    async def test_sync_fans_out_large_roster_as_individually_bounded_events(self):
        canvas_id = uuid4()
        peers = [
            TransientPeer(uuid4(), uuid4(), "u" * 32, {"x": i, "y": i + 1})
            for i in range(40)
        ]
        published: list[dict[str, object]] = []
        received = asyncio.Event()
        delivered = []

        async def publish(event):
            published.append(event)
            if len(published) == len(peers):
                received.set()

        source = CanvasTransientTransport(
            str(uuid4()),
            publish,
            lambda _canvas_id: _peers(peers),
            lambda: (canvas_id,),
            lambda _canvas_id: True,
            lambda _canvas_id, event: _append(delivered, event),
            _ignore_revocation,
        )
        request = {
            "type": "sync.request",
            "process_id": str(uuid4()),
            "event_id": str(uuid4()),
            "canvas_id": str(canvas_id),
        }
        await source.handle_notification(json.dumps(request))
        await asyncio.wait_for(received.wait(), timeout=1)

        total_size = sum(len(json.dumps(event).encode()) for event in published)
        self.assertGreater(total_size, 8000)
        self.assertEqual(len(published), len(peers))
        self.assertTrue(all("connections" not in event for event in published))
        self.assertTrue(
            all(len(json.dumps(event).encode()) < 7900 for event in published)
        )

        remote = CanvasTransientTransport(
            str(uuid4()),
            _ignore_publish,
            _empty_peers,
            lambda: (),
            lambda _canvas_id: True,
            lambda _canvas_id, event: _append(delivered, event),
            _ignore_revocation,
        )
        for event in published:
            await remote.handle_notification(json.dumps(event))
        self.assertEqual(len(await remote.remote_connections(canvas_id)), len(peers))
        await source.close()
        await remote.close()

    async def test_notification_payload_limit_rejects_oversized_event(self):
        from app.canvas_operation_listener import publish_transient_event

        class Connection:
            async def execute(self, *_args):
                raise AssertionError("oversized event reached PostgreSQL")

        with self.assertRaisesRegex(ValueError, "payload limit"):
            await publish_transient_event(
                Connection(),
                {"type": "sync.peer", "payload": "x" * 8000},
            )

    async def test_shutdown_cancels_and_drains_transient_publishers(self):
        started = asyncio.Event()
        never = asyncio.Event()

        async def publish(_event):
            started.set()
            await never.wait()

        transport = CanvasTransientTransport(
            str(uuid4()),
            publish,
            _empty_peers,
            lambda: (),
            lambda _canvas_id: True,
            _ignore_delivery,
            _ignore_revocation,
        )
        transport.request_sync(uuid4())
        await asyncio.wait_for(started.wait(), timeout=1)
        self.assertTrue(transport._publisher_tasks)
        await transport.close()
        self.assertFalse(transport._publisher_tasks)


def _transport(process_id, deliver, has_room):
    return CanvasTransientTransport(
        process_id=process_id,
        publish=_ignore_publish,
        local_peers=_empty_peers,
        active_canvases=lambda: (),
        has_local_room=has_room,
        deliver=deliver,
        revoke_session=_ignore_revocation,
    )


async def _append(target, value):
    target.append(value)


async def _ignore_delivery(_canvas_id, _event):
    return None


async def _ignore_publish(_event):
    return None


async def _ignore_revocation(_token_hash):
    return None


async def _empty_peers(_canvas_id):
    return []


async def _peers(peers):
    return peers
