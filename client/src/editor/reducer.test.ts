import assert from "node:assert/strict";
import test from "node:test";
import { editorReducer } from "./reducer.ts";
import { initialEditorState, type AppliedEvent, type EditorState, type ServerEvent, type Shape } from "./types.ts";

const user = "00000000-0000-4000-8000-000000000001";
const ownConnection = "00000000-0000-4000-8000-000000000002";
const peerConnection = "00000000-0000-4000-8000-000000000003";
const canvasId = "00000000-0000-4000-8000-000000000004";
const shapeId = "00000000-0000-4000-8000-000000000005";
const operationId = "00000000-0000-4000-8000-000000000006";
const peerId = "00000000-0000-4000-8000-000000000007";
const shape: Shape = { id: shapeId, kind: "rectangle", properties: { x: 10, y: 10, width: 50, height: 30, color: "#ffffff" }, revision: 1, deleted: false };

function snapshot(revision = 1): Extract<ServerEvent, { type: "snapshot" }> {
  return { type: "snapshot", canvas: { id: canvasId, title: "Canvas", created_by: user, revision, created_at: "now", updated_at: "now" }, canvas_revision: revision, shapes: [shape], connection_id: ownConnection, connections: [{ connection_id: ownConnection, user: { id: user, username: "alice" }, cursor: null }, { connection_id: peerConnection, user: { id: peerId, username: "bob" }, cursor: null }] };
}

function applied(id: string, rev: number, nextShape: Shape = { ...shape, revision: rev }): AppliedEvent {
  return { type: "operation.applied", operation_id: id, actor_id: user, kind: "update", target_operation_id: null, canvas_revision: rev, shape: nextShape };
}

function readyState(): EditorState {
  return editorReducer(initialEditorState, { type: "snapshot", event: snapshot() });
}

test("snapshot installs canonical data and excludes this connection from remote peers", () => {
  const state = readyState();
  assert.equal(state.phase, "ready");
  assert.deepEqual(Object.keys(state.peers), [peerConnection]);
  assert.equal(state.shapes[shapeId].revision, 1);
});

test("acknowledgements settle local pending commands and only advance contiguous revisions", () => {
  const state = readyState();
  const command = { command: { type: "shape.update" as const, operation_id: operationId, shape_id: shapeId, expected_revision: 1, patch: { x: 20 } }, wire: "{}", recoveryReplay: false };
  const pending = editorReducer(state, { type: "pending", command, optimistic: null });
  const ack = editorReducer(pending, { type: "event", event: applied(operationId, 2, { ...shape, revision: 2, properties: { ...shape.properties, x: 20 } }) });
  assert.equal(ack.pending, null);
  assert.deepEqual(ack.undoIds, [operationId]);
  assert.equal(ack.canvasRevision, 2);
  const duplicate = editorReducer(ack, { type: "event", event: applied("00000000-0000-4000-8000-000000000008", 1, { ...shape, revision: 3 }) });
  assert.equal(duplicate.canvasRevision, 2);
  assert.equal(duplicate.shapes[shapeId].revision, 2);
});

test("connection history controls follow acknowledged undo and redo operations", () => {
  const createId = "00000000-0000-4000-8000-000000000020";
  const undoId = "00000000-0000-4000-8000-000000000021";
  const redoId = "00000000-0000-4000-8000-000000000022";
  const created = { ...shape, revision: 1 };
  const createCommand = { command: { type: "shape.create" as const, operation_id: createId, shape_id: shapeId, kind: "rectangle" as const, properties: created.properties }, wire: "{}", recoveryReplay: false };
  let state = editorReducer(readyState(), { type: "pending", command: createCommand, optimistic: { kind: "shape", shape: created } });
  state = editorReducer(state, { type: "event", event: { ...applied(createId, 2, created), kind: "create" } });
  assert.deepEqual(state.undoIds, [createId]);
  assert.deepEqual(state.redoIds, []);

  const remoteShape: Shape = { ...shape, id: "00000000-0000-4000-8000-000000000025", revision: 1 };
  const remoteEdit: AppliedEvent = { ...applied("00000000-0000-4000-8000-000000000023", 3, remoteShape), actor_id: peerId };
  state = editorReducer(state, { type: "event", event: remoteEdit });
  assert.deepEqual(state.undoIds, [createId]);

  const undoCommand = { command: { type: "undo" as const, operation_id: undoId, target_operation_id: createId }, wire: "{}", recoveryReplay: false };
  state = editorReducer(state, { type: "pending", command: undoCommand, optimistic: null });
  state = editorReducer(state, { type: "event", event: { ...applied(undoId, 4, { ...shape, revision: 2, deleted: true }), kind: "undo", target_operation_id: createId } });
  assert.deepEqual(state.undoIds, []);
  assert.deepEqual(state.redoIds, [undoId]);

  const redoCommand = { command: { type: "redo" as const, operation_id: redoId, target_operation_id: undoId }, wire: "{}", recoveryReplay: false };
  state = editorReducer(state, { type: "pending", command: redoCommand, optimistic: null });
  state = editorReducer(state, { type: "event", event: { ...applied(redoId, 5, { ...shape, revision: 3 }), kind: "redo", target_operation_id: undoId } });
  assert.deepEqual(state.undoIds, [redoId]);
  assert.deepEqual(state.redoIds, []);
});

test("refused history commands leave undo and redo controls unchanged", () => {
  const undoId = "00000000-0000-4000-8000-000000000024";
  const command = { command: { type: "shape.update" as const, operation_id: operationId, shape_id: shapeId, expected_revision: 1, patch: { x: 20 } }, wire: "{}", recoveryReplay: false };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: null });
  state = editorReducer(state, { type: "event", event: applied(operationId, 2, { ...shape, revision: 2 }) });
  const before = { undoIds: state.undoIds, redoIds: state.redoIds };
  const undoCommand = { command: { type: "undo" as const, operation_id: undoId, target_operation_id: operationId }, wire: "{}", recoveryReplay: false };
  state = editorReducer(state, { type: "pending", command: undoCommand, optimistic: null });
  state = editorReducer(state, { type: "event", event: { type: "error", code: "history_conflict", message: "Another person changed this object.", operation_id: undoId } });
  assert.deepEqual({ undoIds: state.undoIds, redoIds: state.redoIds }, before);
  assert.equal(state.notice, "Another person changed this object.");
});

test("remote deletion clears the deleted selection", () => {
  const state = { ...readyState(), selectionId: shapeId, interaction: { kind: "moving" as const, shapeId, expectedRevision: 1, baseline: shape, start: { x: 1, y: 1 }, current: { x: 2, y: 2 } } };
  const deleted = { ...shape, revision: 2, deleted: true };
  const next = editorReducer(state, { type: "event", event: applied(operationId, 2, deleted) });
  assert.equal(next.selectionId, null);
  assert.equal(next.interaction.kind, "idle");
});

test("uncertain recovered command resolves before history is reset on a fresh connection", () => {
  const base = readyState();
  const command = { command: { type: "shape.update" as const, operation_id: operationId, shape_id: shapeId, expected_revision: 1, patch: { x: 20 } }, wire: "{}", recoveryReplay: false };
  let state = editorReducer(base, { type: "pending", command, optimistic: null });
  state = editorReducer(state, { type: "connection.started" });
  assert.equal(state.recovery, "retry-command");
  state = editorReducer(state, { type: "snapshot", event: snapshot() });
  state = editorReducer(state, { type: "pending.retried" });
  state = editorReducer(state, { type: "event", event: applied(operationId, 1) });
  assert.equal(state.recovery, "reset-history");
  state = editorReducer(state, { type: "connection.started" });
  state = editorReducer(state, { type: "snapshot", event: snapshot() });
  assert.equal(state.recovery, "none");
  assert.equal(state.phase, "ready");
  assert.deepEqual(state.undoIds, []);
});

test("a local create stays optimistic until the committed WS-04 acknowledgement arrives", () => {
  const created: Shape = {
    id: "00000000-0000-4000-8000-000000000009",
    kind: "ellipse",
    properties: { x: 70, y: 80, width: 40, height: 30, color: "#abcdef" },
    revision: 1,
    deleted: false,
  };
  const createId = "00000000-0000-4000-8000-000000000010";
  const command = {
    command: { type: "shape.create" as const, operation_id: createId, shape_id: created.id, kind: created.kind, properties: created.properties },
    wire: "{}",
    recoveryReplay: false,
  };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: { kind: "shape", shape: created } });
  state = editorReducer(state, { type: "selection", id: created.id });
  assert.equal(state.shapes[created.id], undefined);
  assert.equal(state.optimistic?.kind, "shape");

  const ack: AppliedEvent = { type: "operation.applied", operation_id: createId, actor_id: user, kind: "create", target_operation_id: null, canvas_revision: 2, shape: created };
  state = editorReducer(state, { type: "event", event: ack });
  assert.equal(state.pending, null);
  assert.equal(state.optimistic, null);
  assert.equal(state.shapes[created.id], created);
  assert.equal(state.selectionId, created.id);
  assert.equal(state.canvasRevision, 2);
  assert.deepEqual(state.undoIds, [createId]);
});

test("a rejected optimistic create removes its preview and dangling selection", () => {
  const created: Shape = {
    id: "00000000-0000-4000-8000-000000000009",
    kind: "rectangle",
    properties: { x: 70, y: 80, width: 40, height: 30, color: "#abcdef" },
    revision: 1,
    deleted: false,
  };
  const createId = "00000000-0000-4000-8000-000000000010";
  const command = {
    command: { type: "shape.create" as const, operation_id: createId, shape_id: created.id, kind: created.kind, properties: created.properties },
    wire: "{}",
    recoveryReplay: false,
  };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: { kind: "shape", shape: created } });
  state = editorReducer(state, { type: "selection", id: created.id });
  state = editorReducer(state, { type: "event", event: { type: "error", code: "shape_unavailable", message: "Shape ID is already in use.", operation_id: createId } });
  assert.equal(state.pending, null);
  assert.equal(state.optimistic, null);
  assert.equal(state.selectionId, null);
  assert.equal(state.shapes[created.id], undefined);
});

test("a replay acknowledgement older than the reconnect snapshot settles without replacing canonical state", () => {
  const created: Shape = {
    id: "00000000-0000-4000-8000-000000000009",
    kind: "rectangle",
    properties: { x: 70, y: 80, width: 40, height: 30, color: "#abcdef" },
    revision: 1,
    deleted: false,
  };
  const createId = "00000000-0000-4000-8000-000000000010";
  const command = {
    command: { type: "shape.create" as const, operation_id: createId, shape_id: created.id, kind: created.kind, properties: created.properties },
    wire: "{}",
    recoveryReplay: false,
  };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: { kind: "shape", shape: created } });
  state = editorReducer(state, { type: "connection.started" });
  state = editorReducer(state, { type: "snapshot", event: { ...snapshot(3), shapes: [{ ...shape, revision: 2 }, created] } });
  state = editorReducer(state, { type: "pending.retried" });
  const replay: AppliedEvent = { type: "operation.applied", operation_id: createId, actor_id: user, kind: "create", target_operation_id: null, canvas_revision: 2, shape: created };
  state = editorReducer(state, { type: "event", event: replay });

  assert.equal(state.pending, null);
  assert.equal(state.optimistic, null);
  assert.equal(state.canvasRevision, 3);
  assert.equal(state.shapes[created.id], created);
  assert.equal(state.recovery, "reset-history");

  state = editorReducer(state, { type: "connection.started" });
  state = editorReducer(state, { type: "snapshot", event: { ...snapshot(3), shapes: [{ ...shape, revision: 2 }, created] } });
  assert.equal(state.phase, "ready");
  assert.equal(state.recovery, "none");
  assert.deepEqual(state.undoIds, []);
});

test("a successful snapshot clears stale connection notices", () => {
  const failed = editorReducer(readyState(), { type: "notice", message: "Reconnecting…" });
  const recovered = editorReducer(failed, { type: "snapshot", event: snapshot(2) });
  assert.equal(recovered.notice, null);
  assert.equal(recovered.phase, "ready");
});

test("a rejected text update retains the attempted text while installing the conflict shape", () => {
  const textShape: Shape = {
    id: shapeId,
    kind: "text",
    properties: { x: 10, y: 10, width: 120, height: 32, color: "#ffffff", text: "Peer version", font_size: 16 },
    revision: 2,
    deleted: false,
  };
  const command = {
    command: { type: "shape.update" as const, operation_id: operationId, shape_id: shapeId, expected_revision: 1, patch: { text: "My unsaved version" } },
    wire: "{}",
    recoveryReplay: false,
  };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: { kind: "shape", shape: { ...textShape, revision: 1, properties: { ...textShape.properties, text: "My unsaved version" } } } });
  state = editorReducer(state, { type: "event", event: { type: "error", code: "conflict", message: "Shape revision is stale.", operation_id: operationId, shape: textShape } });

  assert.equal(state.pending, null);
  assert.equal(state.optimistic, null);
  assert.deepEqual(state.recoveredTextDraft, { shapeId, text: "My unsaved version", properties: { ...textShape.properties, text: "My unsaved version" } });
  assert.equal(state.shapes[shapeId], textShape);

  state = editorReducer(state, { type: "recovered-text.dismiss" });
  assert.equal(state.recoveredTextDraft, null);
});

test("a remote edit cancels a stale drag and removes its optimistic preview", () => {
  const base = readyState();
  const command = {
    command: { type: "shape.update" as const, operation_id: operationId, shape_id: shapeId, expected_revision: 1, patch: { x: 20 } },
    wire: "{}",
    recoveryReplay: false,
  };
  let state = editorReducer(base, { type: "pending", command, optimistic: { kind: "shape", shape: { ...shape, properties: { ...shape.properties, x: 20 } } } });
  state = editorReducer(state, { type: "selection", id: shapeId });
  const remoteShape = { ...shape, revision: 2, properties: { ...shape.properties, x: 40 } };
  state = editorReducer(state, { type: "event", event: applied("00000000-0000-4000-8000-000000000011", 2, remoteShape) });

  assert.equal(state.shapes[shapeId], remoteShape);
  assert.equal(state.optimistic, null);
  assert.equal(state.selectionId, shapeId);
  assert.equal(state.pending?.command.operation_id, operationId);
});

test("a remote edit cancels an in-progress move using a stale shape revision", () => {
  const moving = { ...readyState(), selectionId: shapeId, interaction: { kind: "moving" as const, shapeId, expectedRevision: 1, baseline: shape, start: { x: 1, y: 1 }, current: { x: 8, y: 6 } } };
  const remoteShape = { ...shape, revision: 2, properties: { ...shape.properties, x: 25 } };
  const state = editorReducer(moving, { type: "event", event: applied("00000000-0000-4000-8000-000000000011", 2, remoteShape) });
  assert.equal(state.interaction.kind, "idle");
  assert.equal(state.selectionId, shapeId);
  assert.equal(state.shapes[shapeId], remoteShape);
});

test("a remote text edit preserves a changed draft before closing the stale editor", () => {
  const textShape: Shape = {
    id: shapeId,
    kind: "text",
    properties: { x: 10, y: 10, width: 120, height: 32, color: "#ffffff", text: "Original", font_size: 16 },
    revision: 1,
    deleted: false,
  };
  const editing = { ...readyState(), shapes: { [shapeId]: textShape }, selectionId: shapeId, interaction: { kind: "editingText" as const, sessionId: "session-1", shapeId, expectedRevision: 1, start: { x: 10, y: 10 }, width: 120, height: 32, color: "#ffffff", fontSize: 16, draft: "My unfinished draft" } };
  const collaboratorShape: Shape = { ...textShape, revision: 2, properties: { ...textShape.properties, text: "Collaborator's edit" } };
  const state = editorReducer(editing, { type: "event", event: applied("00000000-0000-4000-8000-000000000011", 2, collaboratorShape) });

  assert.equal(state.interaction.kind, "idle");
  assert.deepEqual(state.recoveredTextDraft, { shapeId, text: "My unfinished draft", properties: { ...textShape.properties, text: "My unfinished draft" } });
  assert.equal(state.shapes[shapeId], collaboratorShape);
});

test("WS-06 presence and cursor messages add, update, hide, and remove peer cursors without document revisions", () => {
  const connection = "00000000-0000-4000-8000-000000000012";
  const peer = { connection_id: connection, user: { id: peerId, username: "bob" }, cursor: null };
  const initialRevision = readyState().canvasRevision;
  let state = editorReducer(readyState(), { type: "event", event: { type: "presence.joined", connection: peer } });
  assert.deepEqual(state.peers[connection], peer);

  state = editorReducer(state, { type: "event", event: { type: "cursor", connection_id: connection, user_id: peerId, position: { x: 25, y: 30 } } });
  assert.deepEqual(state.peers[connection].cursor, { x: 25, y: 30 });
  state = editorReducer(state, { type: "event", event: { type: "cursor", connection_id: connection, user_id: peerId, position: null } });
  assert.equal(state.peers[connection].cursor, null);

  state = editorReducer(state, { type: "event", event: { type: "presence.left", connection_id: connection } });
  assert.equal(state.peers[connection], undefined);
  assert.equal(state.canvasRevision, initialRevision);
});

test("a rejected text create retains its complete initial geometry and style", () => {
  const textShape: Shape = {
    id: "00000000-0000-4000-8000-000000000013",
    kind: "text",
    properties: { x: 22, y: 33, width: 130, height: 36, color: "#abcdef", text: "Unsaved note", font_size: 18 },
    revision: 1,
    deleted: false,
  };
  const createId = "00000000-0000-4000-8000-000000000014";
  const command = { command: { type: "shape.create" as const, operation_id: createId, shape_id: textShape.id, kind: "text" as const, properties: textShape.properties }, wire: "{}", recoveryReplay: false };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: { kind: "shape", shape: textShape } });
  state = editorReducer(state, { type: "event", event: { type: "error", code: "operation_failed", message: "Could not save text.", operation_id: createId } });
  assert.deepEqual(state.recoveredTextDraft, { shapeId: textShape.id, text: textShape.properties.text, properties: textShape.properties });
});

test("disconnect preserves an in-progress text draft for recovery", () => {
  const textShape: Shape = {
    id: shapeId,
    kind: "text",
    properties: { x: 10, y: 10, width: 120, height: 32, color: "#ffffff", text: "Saved", font_size: 16 },
    revision: 1,
    deleted: false,
  };
  const editing = {
    ...readyState(),
    shapes: { [shapeId]: textShape },
    interaction: { kind: "editingText" as const, sessionId: "session-2", shapeId, expectedRevision: 1, start: { x: 10, y: 10 }, width: 120, height: 32, color: "#ffffff", fontSize: 16, draft: "Unsaved words" },
  };
  const state = editorReducer(editing, { type: "connection.started" });

  assert.equal(state.interaction.kind, "idle");
  assert.deepEqual(state.recoveredTextDraft, { shapeId, text: "Unsaved words", properties: { ...textShape.properties, text: "Unsaved words" } });
  assert.equal(state.phase, "reconnecting");
});

test("an uncertain text create is retained if access expires before its outcome is known", () => {
  const textShape: Shape = {
    id: "00000000-0000-4000-8000-000000000013",
    kind: "text",
    properties: { x: 22, y: 33, width: 130, height: 36, color: "#abcdef", text: "Unsaved note", font_size: 18 },
    revision: 1,
    deleted: false,
  };
  const createId = "00000000-0000-4000-8000-000000000014";
  const command = { command: { type: "shape.create" as const, operation_id: createId, shape_id: textShape.id, kind: "text" as const, properties: textShape.properties }, wire: "{}", recoveryReplay: false };
  let state = editorReducer(readyState(), { type: "pending", command, optimistic: { kind: "shape", shape: textShape } });
  state = editorReducer(state, { type: "connection.failed", message: "Canvas access expired." });

  assert.equal(state.phase, "failed");
  assert.equal(state.pending, null);
  assert.equal(state.optimistic, null);
  assert.deepEqual(state.recoveredTextDraft, { shapeId: textShape.id, text: textShape.properties.text, properties: textShape.properties });
});
