import assert from "node:assert/strict";
import test from "node:test";
import { parseServerEvent } from "./protocol.ts";

const user = "00000000-0000-4000-8000-000000000001";
const connection = "00000000-0000-4000-8000-000000000002";
const canvas = "00000000-0000-4000-8000-000000000003";
const shape = { id: "00000000-0000-4000-8000-000000000004", kind: "rectangle", properties: { x: 2, y: 3, width: 40, height: 20, color: "#abcdef" }, revision: 1, deleted: false };

test("parses the actual snapshot shape and connection payload", () => {
  const parsed = parseServerEvent(JSON.stringify({ type: "snapshot", canvas: { id: canvas, title: "Sketch", created_by: user, revision: 1, created_at: "now", updated_at: "now" }, canvas_revision: 1, shapes: [shape], connection_id: connection, connections: [{ connection_id: connection, user: { id: user, username: "alice" }, cursor: null }] }));
  assert.equal(parsed.type, "snapshot");
  if (parsed.type === "snapshot") {
    assert.equal(parsed.shapes[0].properties.opacity, 1);
    assert.equal(parsed.shapes[0].properties.z_index, 0);
  }
});

test("defaults legacy line ends and rejects malformed arrow settings", () => {
  const legacy = { ...shape, kind: "line", properties: { x1: 1, y1: 2, x2: 3, y2: 4, color: "#abcdef" } };
  const parsed = parseServerEvent(JSON.stringify({ type: "operation.applied", operation_id: "00000000-0000-4000-8000-000000000005", actor_id: user, kind: "create", target_operation_id: null, canvas_revision: 2, shape: legacy }));
  assert.equal(parsed.type, "operation.applied");
  if (parsed.type === "operation.applied" && parsed.shape.kind === "line") assert.deepEqual([parsed.shape.properties.start_arrow, parsed.shape.properties.end_arrow], [false, false]);
  for (const value of ["true", 1, null]) assert.throws(() => parseServerEvent(JSON.stringify({ type: "operation.applied", operation_id: "00000000-0000-4000-8000-000000000005", actor_id: user, kind: "create", target_operation_id: null, canvas_revision: 2, shape: { ...legacy, properties: { ...legacy.properties, start_arrow: value } } })));
});

test("parses saved opacity and layer order and rejects invalid opacity", () => {
  const parsed = parseServerEvent(JSON.stringify({ type: "operation.applied", operation_id: "00000000-0000-4000-8000-000000000005", actor_id: user, kind: "update", target_operation_id: null, canvas_revision: 2, shape: { ...shape, properties: { ...shape.properties, opacity: 0.35, z_index: 8 } } }));
  assert.equal(parsed.type, "operation.applied");
  if (parsed.type === "operation.applied") {
    assert.equal(parsed.shape.properties.opacity, 0.35);
    assert.equal(parsed.shape.properties.z_index, 8);
  }
  assert.throws(() => parseServerEvent(JSON.stringify({ type: "operation.applied", operation_id: "00000000-0000-4000-8000-000000000005", actor_id: user, kind: "update", target_operation_id: null, canvas_revision: 2, shape: { ...shape, properties: { ...shape.properties, opacity: 1.5 } } })));
});

test("accepts server errors with an authoritative conflict shape", () => {
  const parsed = parseServerEvent(JSON.stringify({ type: "error", code: "conflict", message: "Changed by another editor.", operation_id: "00000000-0000-4000-8000-000000000005", shape: { ...shape, revision: 2 } }));
  assert.equal(parsed.type, "error");
});

test("parses the committed acknowledgement emitted by WS-04", () => {
  const parsed = parseServerEvent(JSON.stringify({
    type: "operation.applied",
    operation_id: "00000000-0000-4000-8000-000000000005",
    actor_id: user,
    kind: "create",
    target_operation_id: null,
    canvas_revision: 2,
    shape,
  }));
  assert.equal(parsed.type, "operation.applied");
  if (parsed.type === "operation.applied") {
    assert.equal(parsed.canvas_revision, 2);
    assert.equal(parsed.target_operation_id, null);
    assert.equal(parsed.shape.id, shape.id);
  }
});

test("parses the WS-05 update and delete acknowledgement envelope", () => {
  for (const [kind, revision, deleted] of [["update", 2, false], ["delete", 3, true]] as const) {
    const parsed = parseServerEvent(JSON.stringify({
      type: "operation.applied",
      operation_id: "00000000-0000-4000-8000-000000000005",
      actor_id: user,
      kind,
      target_operation_id: null,
      canvas_revision: revision,
      shape: { ...shape, revision, deleted },
    }));
    assert.equal(parsed.type, "operation.applied");
    if (parsed.type === "operation.applied") {
      assert.equal(parsed.kind, kind);
      assert.equal(parsed.shape.deleted, deleted);
    }
  }
});

test("parses WS-06 presence and cursor messages including cursor hiding", () => {
  const joined = parseServerEvent(JSON.stringify({ type: "presence.joined", connection_id: connection, user: { id: user, username: "alice" } }));
  assert.equal(joined.type, "presence.joined");
  if (joined.type === "presence.joined") {
    assert.equal(joined.connection.connection_id, connection);
    assert.equal(joined.connection.user.username, "alice");
    assert.equal(joined.connection.cursor, null);
  }

  const moved = parseServerEvent(JSON.stringify({ type: "cursor", connection_id: connection, user_id: user, position: { x: 14, y: 28 } }));
  const hidden = parseServerEvent(JSON.stringify({ type: "cursor", connection_id: connection, user_id: user, position: null }));
  const left = parseServerEvent(JSON.stringify({ type: "presence.left", connection_id: connection }));
  assert.equal(moved.type, "cursor");
  assert.equal(hidden.type, "cursor");
  if (hidden.type === "cursor") assert.equal(hidden.position, null);
  assert.deepEqual(left, { type: "presence.left", connection_id: connection });
});

test("rejects malformed shape records and unsupported message names", () => {
  assert.throws(() => parseServerEvent(JSON.stringify({ type: "snapshot", canvas: {}, canvas_revision: 0, shapes: [{ ...shape, properties: { ...shape.properties, width: 0 } }], connection_id: connection, connections: [] })));
  assert.throws(() => parseServerEvent(JSON.stringify({ type: "peers", peers: [] })));
});

test("rejects inconsistent snapshots and incomplete applied events", () => {
  assert.throws(() => parseServerEvent(JSON.stringify({ type: "snapshot", canvas: { id: canvas, title: "Sketch", created_by: user, revision: 1, created_at: "now", updated_at: "now" }, canvas_revision: 2, shapes: [], connection_id: connection, connections: [{ connection_id: connection, user: { id: user, username: "alice" }, cursor: null }] })));
  assert.throws(() => parseServerEvent(JSON.stringify({ type: "operation.applied", operation_id: "00000000-0000-4000-8000-000000000005", actor_id: user, kind: "made-up", canvas_revision: 2, target_operation_id: null, shape })));
  assert.throws(() => parseServerEvent(JSON.stringify({ type: "operation.applied", operation_id: "00000000-0000-4000-8000-000000000005", actor_id: user, kind: "create", canvas_revision: 2, shape })));
});

test("accepts code-point-limit text in snapshots and applied events", () => {
  for (const character of ["a", "é", "🧪"]) {
    const textShape = {
      id: "00000000-0000-4000-8000-000000000006",
      kind: "text",
      properties: { x: 1, y: 2, width: 40, height: 20, color: "#abcdef", font_size: 12, text: character.repeat(10_000) },
      revision: 1,
      deleted: false,
    };
    const snapshot = parseServerEvent(JSON.stringify({
      type: "snapshot",
      canvas: { id: canvas, title: "Sketch", created_by: user, revision: 1, created_at: "now", updated_at: "now" },
      canvas_revision: 1,
      shapes: [textShape],
      connection_id: connection,
      connections: [{ connection_id: connection, user: { id: user, username: "alice" }, cursor: null }],
    }));
    const applied = parseServerEvent(JSON.stringify({
      type: "operation.applied",
      operation_id: "00000000-0000-4000-8000-000000000005",
      actor_id: user,
      kind: "create",
      target_operation_id: null,
      canvas_revision: 2,
      shape: textShape,
    }));

    assert.equal(snapshot.type, "snapshot");
    if (snapshot.type === "snapshot") assert.equal(snapshot.shapes[0].properties.text, textShape.properties.text);
    assert.equal(applied.type, "operation.applied");
    if (applied.type === "operation.applied") assert.equal(applied.shape.properties.text, textShape.properties.text);
  }
});

test("rejects text exceeding the code-point limit in snapshots and applied events", () => {
  const textShape = {
    id: "00000000-0000-4000-8000-000000000006",
    kind: "text",
    properties: { x: 1, y: 2, width: 40, height: 20, color: "#abcdef", font_size: 12, text: "🧪".repeat(10_001) },
    revision: 1,
    deleted: false,
  };
  assert.throws(() => parseServerEvent(JSON.stringify({
    type: "snapshot",
    canvas: { id: canvas, title: "Sketch", created_by: user, revision: 1, created_at: "now", updated_at: "now" },
    canvas_revision: 1,
    shapes: [textShape],
    connection_id: connection,
    connections: [{ connection_id: connection, user: { id: user, username: "alice" }, cursor: null }],
  })));
  assert.throws(() => parseServerEvent(JSON.stringify({
    type: "operation.applied",
    operation_id: "00000000-0000-4000-8000-000000000005",
    actor_id: user,
    kind: "create",
    target_operation_id: null,
    canvas_revision: 2,
    shape: textShape,
  })));
});
