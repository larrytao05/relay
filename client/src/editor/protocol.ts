import type { CanvasSnapshot, Peer, Point, ServerEvent, Shape } from "./types.ts";

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Parse a frame at the WebSocket boundary. Values stay unknown until validated. */
export function parseServerEvent(data: string): ServerEvent {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    throw new Error("The server sent invalid JSON.");
  }
  if (!record(value) || typeof value.type !== "string") throw new Error("The server sent an unknown message.");

  switch (value.type) {
    case "snapshot": {
      const canvas = parseCanvas(value.canvas);
      if (!safeRevision(value.canvas_revision) || value.canvas_revision !== canvas.revision || !Array.isArray(value.shapes) || !Array.isArray(value.connections) || !uuid(value.connection_id)) {
        throw new Error("The server sent an invalid canvas snapshot.");
      }
      const shapes = value.shapes.map(parseShape);
      if (shapes.some((shape) => shape.deleted)) throw new Error("The server sent a deleted shape in the canvas snapshot.");
      const connections = value.connections.map(parsePeer);
      if (!connections.some((peer) => peer.connection_id === value.connection_id)) throw new Error("The server sent a snapshot without this connection.");
      return { type: "snapshot", canvas, canvas_revision: value.canvas_revision, shapes, connection_id: value.connection_id, connections };
    }
    case "operation.applied": {
      const kind = parseOperationKind(value.kind);
      if (!uuid(value.operation_id) || !uuid(value.actor_id) || !safeRevision(value.canvas_revision) || kind === null || !(value.target_operation_id === null || uuid(value.target_operation_id))) {
        throw new Error("The server sent an invalid operation.");
      }
      return {
        type: "operation.applied",
        operation_id: value.operation_id,
        actor_id: value.actor_id,
        kind,
        target_operation_id: value.target_operation_id,
        canvas_revision: value.canvas_revision,
        shape: parseShape(value.shape),
      };
    }
    case "presence.joined":
      if (!uuid(value.connection_id) || !record(value.user) || !uuid(value.user.id) || typeof value.user.username !== "string") {
        throw new Error("The server sent invalid presence data.");
      }
      return {
        type: "presence.joined",
        connection: {
          connection_id: value.connection_id,
          user: { id: value.user.id, username: value.user.username },
          cursor: null,
        },
      };
    case "presence.left":
      if (!uuid(value.connection_id)) throw new Error("The server sent invalid presence data.");
      return { type: "presence.left", connection_id: value.connection_id };
    case "cursor":
      if (!uuid(value.connection_id) || !uuid(value.user_id) || !(value.position === null || validPoint(value.position))) {
        throw new Error("The server sent invalid cursor data.");
      }
      return { type: "cursor", connection_id: value.connection_id, user_id: value.user_id, position: value.position === null ? null : parsePoint(value.position) };
    case "error": {
      if (typeof value.code !== "string" || typeof value.message !== "string" || (value.operation_id !== undefined && !uuid(value.operation_id))) {
        throw new Error("The server sent an invalid error response.");
      }
      const result: ServerEvent = value.shape === undefined
        ? { type: "error", code: value.code, message: value.message, ...(value.operation_id === undefined ? {} : { operation_id: value.operation_id }) }
        : { type: "error", code: value.code, message: value.message, ...(value.operation_id === undefined ? {} : { operation_id: value.operation_id }), shape: parseShape(value.shape) };
      return result;
    }
    default:
      throw new Error("The server sent an unsupported message type.");
  }
}

function parseCanvas(value: unknown): CanvasSnapshot {
  if (!record(value) || !uuid(value.id) || typeof value.title !== "string" || !uuid(value.created_by) || !safeRevision(value.revision) || typeof value.created_at !== "string" || typeof value.updated_at !== "string") {
    throw new Error("The server sent invalid canvas details.");
  }
  return { id: value.id, title: value.title, created_by: value.created_by, revision: value.revision, created_at: value.created_at, updated_at: value.updated_at };
}

function parseShape(value: unknown): Shape {
  if (!record(value) || !uuid(value.id) || !safeRevision(value.revision) || typeof value.deleted !== "boolean" || !record(value.properties)) {
    throw new Error("The server sent an invalid shape.");
  }
  const properties = value.properties;
  if (typeof properties.color !== "string" || !/^#[0-9a-f]{6}$/i.test(properties.color)) throw new Error("The server sent an invalid shape color.");
  const opacity = properties.opacity === undefined ? 1 : properties.opacity;
  const zIndex = properties.z_index === undefined ? 0 : properties.z_index;
  if (!finite(opacity) || opacity < 0 || opacity > 1 || !finite(zIndex)) throw new Error("The server sent invalid shape appearance properties.");
  const base = { id: value.id, revision: value.revision, deleted: value.deleted };
  switch (value.kind) {
    case "rectangle":
    case "ellipse":
      if (!finite(properties.x) || !finite(properties.y) || !positive(properties.width) || !positive(properties.height)) throw new Error("The server sent invalid shape geometry.");
      return { ...base, kind: value.kind, properties: { x: properties.x, y: properties.y, width: properties.width, height: properties.height, color: properties.color, opacity, z_index: zIndex } };
    case "line":
      if (!finite(properties.x1) || !finite(properties.y1) || !finite(properties.x2) || !finite(properties.y2)) throw new Error("The server sent invalid line geometry.");
      return { ...base, kind: "line", properties: { x1: properties.x1, y1: properties.y1, x2: properties.x2, y2: properties.y2, color: properties.color, opacity, z_index: zIndex } };
    case "text":
      if (!finite(properties.x) || !finite(properties.y) || !positive(properties.width) || !positive(properties.height) || !positive(properties.font_size) || typeof properties.text !== "string" || properties.text.length > 10_000) throw new Error("The server sent invalid text properties.");
      return { ...base, kind: "text", properties: { x: properties.x, y: properties.y, width: properties.width, height: properties.height, color: properties.color, opacity, z_index: zIndex, text: properties.text, font_size: properties.font_size } };
    default:
      throw new Error("The server sent an unsupported shape kind.");
  }
}

function parsePeer(value: unknown): Peer {
  if (!record(value) || !uuid(value.connection_id) || !record(value.user) || !uuid(value.user.id) || typeof value.user.username !== "string" || !(value.cursor === null || validPoint(value.cursor))) {
    throw new Error("The server sent invalid presence data.");
  }
  return { connection_id: value.connection_id, user: { id: value.user.id, username: value.user.username }, cursor: value.cursor === null ? null : parsePoint(value.cursor) };
}

function parsePoint(value: unknown): Point {
  if (!record(value) || !finite(value.x) || !finite(value.y)) throw new Error("The server sent an invalid point.");
  return { x: value.x, y: value.y };
}

function parseOperationKind(value: unknown): "create" | "update" | "delete" | "undo" | "redo" | null {
  switch (value) {
    case "create":
    case "update":
    case "delete":
    case "undo":
    case "redo":
      return value;
    default:
      return null;
  }
}

function validPoint(value: unknown): value is Record<string, unknown> {
  return record(value) && finite(value.x) && finite(value.y);
}
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function uuid(value: unknown): value is string { return typeof value === "string" && uuidPattern.test(value); }
function finite(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function positive(value: unknown): value is number { return finite(value) && value > 0; }
function safeRevision(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
