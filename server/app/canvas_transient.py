"""Process-local cache and PostgreSQL transport for transient canvas events."""

import asyncio
import json
import logging
import math
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)
_PEER_TTL = 20.0
_MAX_SEEN_EVENTS = 4096
_MAX_PEER_VERSIONS = 8192
_MAX_PUBLISH_TASKS = 512
_MAX_REMOTE_PEERS_PER_CANVAS = 256
_SESSION_HASH = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TransientPeer:
    connection_id: UUID
    user_id: UUID
    username: str
    cursor: dict[str, float] | None


@dataclass
class _RemotePeer:
    process_id: str
    version: int
    user_id: str
    username: str
    cursor: dict[str, float] | None
    last_seen: float


class CanvasTransientTransport:
    """Coordinate transient peer state without making it durable."""

    def __init__(
        self,
        process_id: str,
        publish: Callable[[dict[str, object]], Awaitable[None]],
        local_peers: Callable[[UUID], Awaitable[list[TransientPeer]]],
        active_canvases: Callable[[], Iterable[UUID]],
        has_local_room: Callable[[UUID], bool],
        deliver: Callable[[UUID, dict[str, object]], Awaitable[None]],
        revoke_session: Callable[[str], Awaitable[None]],
    ) -> None:
        self.process_id = process_id
        self._publish = publish
        self._local_peers = local_peers
        self._active_canvases = active_canvases
        self._has_local_room = has_local_room
        self._deliver = deliver
        self._revoke_session = revoke_session
        self._remote: dict[UUID, dict[UUID, _RemotePeer]] = {}
        self._versions: OrderedDict[tuple[UUID, UUID], tuple[str, int, float]] = (
            OrderedDict()
        )
        self._seen_events: OrderedDict[str, None] = OrderedDict()
        self._local_versions: dict[UUID, int] = {}
        self._remote_lock = asyncio.Lock()
        self._publisher_tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    def publish_connection_event(
        self,
        canvas_id: UUID,
        connection_id: UUID,
        event_type: str,
        user_id: UUID,
        username: str,
        cursor: dict[str, float] | None = None,
    ) -> None:
        version = self._local_versions.get(connection_id, 0) + 1
        self._local_versions[connection_id] = version
        event: dict[str, object] = {
            "type": event_type,
            "process_id": self.process_id,
            "event_id": str(uuid4()),
            "version": version,
            "canvas_id": str(canvas_id),
            "connection_id": str(connection_id),
            "user": {"id": str(user_id), "username": username},
        }
        if event_type == "cursor":
            event["position"] = cursor
        task = self._schedule_publish(event)
        if event_type == "presence.left":
            self._local_versions.pop(connection_id, None)
            if task is not None:
                task.add_done_callback(
                    lambda _task, key=connection_id: self._local_versions.pop(key, None)
                )

    def request_sync(self, canvas_id: UUID) -> None:
        self._schedule_publish(
            {
                "type": "sync.request",
                "process_id": self.process_id,
                "event_id": str(uuid4()),
                "canvas_id": str(canvas_id),
            }
        )

    async def handle_notification(self, payload: str) -> None:
        event = self._parse_event(payload)
        if event is None:
            return
        event_type = event["type"]
        process_id = event["process_id"]
        if process_id == self.process_id:
            return
        if event_type == "session.revoked":
            token_hash = event.get("token_hash")
            if isinstance(token_hash, str) and _SESSION_HASH.fullmatch(token_hash):
                await self._revoke_session(token_hash)
            return
        canvas_id = event["canvas_id"]
        if not self._has_local_room(canvas_id):
            return
        if not self._remember_event(event["event_id"]):
            return
        if event_type == "sync.request":
            await self._publish_canvas_state(canvas_id)
        elif event_type == "sync.peer":
            await self._apply_peer_event(event, state_sync=True)
        elif event_type == "sync.empty":
            return
        else:
            await self._apply_peer_event(event, state_sync=False)

    async def sync_periodic(self) -> None:
        now = monotonic()
        expired: list[tuple[UUID, UUID]] = []
        async with self._remote_lock:
            self._purge_versions(now)
            for canvas_id, peers in tuple(self._remote.items()):
                for connection_id, peer in tuple(peers.items()):
                    if now - peer.last_seen > _PEER_TTL:
                        peers.pop(connection_id, None)
                        expired.append((canvas_id, connection_id))
                if not peers:
                    self._remote.pop(canvas_id, None)
        for canvas_id, connection_id in expired:
            if self._has_local_room(canvas_id):
                await self._deliver(
                    canvas_id,
                    {"type": "presence.left", "connection_id": str(connection_id)},
                )
        for canvas_id in tuple(self._active_canvases()):
            await self._publish_canvas_state(canvas_id)

    async def remote_connections(self, canvas_id: UUID) -> list[dict[str, object]]:
        now = monotonic()
        async with self._remote_lock:
            return [
                {
                    "connection_id": connection_id,
                    "user": {"id": peer.user_id, "username": peer.username},
                    "cursor": peer.cursor,
                }
                for connection_id, peer in self._remote.get(canvas_id, {}).items()
                if now - peer.last_seen <= _PEER_TTL
            ]

    async def forget_canvas(self, canvas_id: UUID) -> None:
        async with self._remote_lock:
            self._remote.pop(canvas_id, None)
            for key in tuple(self._versions):
                if key[0] == canvas_id:
                    self._versions.pop(key, None)

    async def close(self) -> None:
        self._closing = True
        tasks = tuple(self._publisher_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._publisher_tasks.clear()

    async def _publish_canvas_state(self, canvas_id: UUID) -> None:
        if not self._has_local_room(canvas_id):
            return
        peers = await self._local_peers(canvas_id)
        if not peers:
            self._schedule_publish(self._base_event("sync.empty", canvas_id))
            return
        for peer in peers:
            self._schedule_publish(
                {
                    **self._base_event("sync.peer", canvas_id),
                    "connection_id": str(peer.connection_id),
                    "version": max(self._local_versions.get(peer.connection_id, 0), 1),
                    "user": {"id": str(peer.user_id), "username": peer.username},
                    "cursor": peer.cursor,
                }
            )

    def _base_event(self, event_type: str, canvas_id: UUID) -> dict[str, object]:
        return {
            "type": event_type,
            "process_id": self.process_id,
            "event_id": str(uuid4()),
            "canvas_id": str(canvas_id),
        }

    def _schedule_publish(self, event: dict[str, object]) -> asyncio.Task[None] | None:
        if self._closing:
            return None
        if len(self._publisher_tasks) >= _MAX_PUBLISH_TASKS:
            logger.warning("Transient publisher task limit reached; sync will retry")
            return None
        task = asyncio.create_task(self._publish_event(event))
        self._publisher_tasks.add(task)
        task.add_done_callback(self._publisher_tasks.discard)
        return task

    async def _publish_event(self, event: dict[str, object]) -> None:
        try:
            await self._publish(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not publish transient canvas event")

    async def _apply_peer_event(self, event: dict[str, Any], state_sync: bool) -> None:
        canvas_id: UUID = event["canvas_id"]
        connection_id: UUID = event["connection_id"]
        process_id: str = event["process_id"]
        version: int = event["version"]
        user: dict[str, str] = event["user"]
        event_type: str = event["type"]
        cursor = event.get("cursor") if state_sync else event.get("position")
        now = monotonic()
        async with self._remote_lock:
            self._purge_versions(now)
            previous = self._remote.get(canvas_id, {}).get(connection_id)
            version_key = (canvas_id, connection_id)
            known = self._versions.get(version_key)
            if known is not None and (
                known[0] != process_id
                or known[1] > version
                or (known[1] == version and not state_sync)
            ):
                return
            self._versions[version_key] = (process_id, version, now + _PEER_TTL)
            self._versions.move_to_end(version_key)
            self._trim_versions()
            if not state_sync and event_type == "presence.left":
                self._remote.get(canvas_id, {}).pop(connection_id, None)
                self._versions[version_key] = (process_id, version, now + _PEER_TTL)
                self._versions.move_to_end(version_key)
                wire_events = [
                    {"type": "presence.left", "connection_id": str(connection_id)}
                ]
            else:
                peers = self._remote.setdefault(canvas_id, {})
                if previous is None and len(peers) >= _MAX_REMOTE_PEERS_PER_CANVAS:
                    logger.warning("Remote canvas peer limit reached; sync will retry")
                    return
                peer = _RemotePeer(
                    process_id,
                    version,
                    user["id"],
                    user["username"],
                    cursor,
                    now,
                )
                peers[connection_id] = peer
                if previous is None:
                    wire_events = [
                        {
                            "type": "presence.joined",
                            "connection_id": str(connection_id),
                            "user": {"id": peer.user_id, "username": peer.username},
                        }
                    ]
                    if cursor is not None:
                        wire_events.append(self._cursor_wire(connection_id, peer))
                elif previous.cursor != cursor or (
                    not state_sync and event_type == "cursor"
                ):
                    wire_events = [self._cursor_wire(connection_id, peer)]
                else:
                    wire_events = []
        if self._has_local_room(canvas_id):
            for wire_event in wire_events:
                await self._deliver(canvas_id, wire_event)

    @staticmethod
    def _cursor_wire(connection_id: UUID, peer: _RemotePeer) -> dict[str, object]:
        return {
            "type": "cursor",
            "connection_id": str(connection_id),
            "user_id": peer.user_id,
            "position": peer.cursor,
        }

    def _parse_event(self, payload: str) -> dict[str, Any] | None:
        try:
            event = json.loads(payload)
            if not isinstance(event, dict):
                raise TypeError
            event_type = event["type"]
            process_id = str(UUID(event["process_id"]))
            event_id = str(UUID(event["event_id"]))
            canvas_id = UUID(event["canvas_id"])
            if not isinstance(event_type, str):
                raise TypeError
            parsed: dict[str, Any] = {
                **event,
                "process_id": process_id,
                "event_id": event_id,
                "canvas_id": canvas_id,
            }
            if event_type == "session.revoked":
                token_hash = event.get("token_hash")
                if not isinstance(token_hash, str) or not _SESSION_HASH.fullmatch(
                    token_hash
                ):
                    raise ValueError
                return parsed
            if event_type == "sync.request" or event_type == "sync.empty":
                return parsed
            if event_type not in {
                "presence.joined",
                "presence.left",
                "cursor",
                "sync.peer",
            }:
                raise ValueError
            connection_id = UUID(event["connection_id"])
            version = event["version"]
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise ValueError
            user = event["user"]
            if not isinstance(user, dict):
                raise TypeError
            user_id = str(UUID(user["id"]))
            username = user["username"]
            if not isinstance(username, str) or not username:
                raise TypeError
            position = event.get("cursor" if event_type == "sync.peer" else "position")
            if event_type in {"cursor", "sync.peer"} and not self._valid_cursor(
                position
            ):
                raise ValueError
            parsed.update(
                {
                    "connection_id": connection_id,
                    "version": version,
                    "user": {"id": user_id, "username": username},
                    "position": position,
                    "cursor": position,
                }
            )
            return parsed
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            logger.warning("Ignoring malformed transient canvas notification")
            return None

    @staticmethod
    def _valid_cursor(cursor: object) -> bool:
        if cursor is None:
            return True
        if not isinstance(cursor, dict) or set(cursor) != {"x", "y"}:
            return False
        return all(
            isinstance(cursor[axis], (int, float))
            and not isinstance(cursor[axis], bool)
            and math.isfinite(cursor[axis])
            for axis in ("x", "y")
        )

    def _remember_event(self, event_id: str) -> bool:
        if event_id in self._seen_events:
            return False
        self._seen_events[event_id] = None
        if len(self._seen_events) > _MAX_SEEN_EVENTS:
            self._seen_events.popitem(last=False)
        return True

    def _purge_versions(self, now: float) -> None:
        for key, (_, _, expires_at) in tuple(self._versions.items()):
            if expires_at <= now:
                self._versions.pop(key, None)

    def _trim_versions(self) -> None:
        while len(self._versions) > _MAX_PEER_VERSIONS:
            self._versions.popitem(last=False)
