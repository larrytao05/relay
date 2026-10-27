export type Point = { x: number; y: number };
export type ShapeKind = "rectangle" | "ellipse" | "line" | "text";
export type AppearanceProperties = { opacity: number; z_index: number };

export type BoxProperties = AppearanceProperties & {
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
};

export type LineProperties = AppearanceProperties & {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  start_arrow: boolean;
  end_arrow: boolean;
};
export type LineArrowDefaults = Pick<LineProperties, "start_arrow" | "end_arrow">;

export type TextProperties = BoxProperties & {
  text: string;
  font_size: number;
};

export type Shape =
  | { id: string; kind: "rectangle" | "ellipse"; properties: BoxProperties; revision: number; deleted: boolean }
  | { id: string; kind: "line"; properties: LineProperties; revision: number; deleted: boolean }
  | { id: string; kind: "text"; properties: TextProperties; revision: number; deleted: boolean };

export type CanvasSnapshot = {
  id: string;
  title: string;
  created_by: string;
  revision: number;
  created_at: string;
  updated_at: string;
};

export type Peer = {
  connection_id: string;
  user: { id: string; username: string };
  cursor: Point | null;
};

export type Tool = "select" | "rectangle" | "ellipse" | "line" | "text";
export type ResizeHandle = "nw" | "ne" | "sw" | "se" | "start" | "end";

export type Interaction =
  | { kind: "idle" }
  | { kind: "creating"; shapeKind: "rectangle" | "ellipse"; start: Point; current: Point; color: string }
  | { kind: "creating"; shapeKind: "line"; start: Point; current: Point; color: string; start_arrow: boolean; end_arrow: boolean }
  | { kind: "moving"; shapeId: string; expectedRevision: number; baseline: Shape; start: Point; current: Point }
  | { kind: "resizing"; shapeId: string; expectedRevision: number; baseline: Shape; handle: ResizeHandle; start: Point; current: Point }
  | { kind: "editingText"; sessionId: string; shapeId: string | null; expectedRevision: number | null; start: Point; width: number; height: number; color: string; fontSize: number; draft: string };

export type DurableCommand =
  | { type: "shape.create"; operation_id: string; shape_id: string; kind: ShapeKind; properties: Shape["properties"] }
  | { type: "shape.update"; operation_id: string; shape_id: string; expected_revision: number; patch: Record<string, unknown> }
  | { type: "shape.delete"; operation_id: string; shape_id: string; expected_revision: number }
  | { type: "undo" | "redo"; operation_id: string; target_operation_id: string };

export type AppliedEvent = {
  type: "operation.applied";
  operation_id: string;
  actor_id: string;
  kind: "create" | "update" | "delete" | "undo" | "redo";
  target_operation_id: string | null;
  canvas_revision: number;
  shape: Shape;
};

export type ServerEvent =
  | { type: "snapshot"; canvas: CanvasSnapshot; canvas_revision: number; shapes: Shape[]; connection_id: string; connections: Peer[] }
  | AppliedEvent
  | { type: "presence.joined"; connection: Peer }
  | { type: "presence.left"; connection_id: string }
  | { type: "cursor"; connection_id: string; user_id: string; position: Point | null }
  | { type: "error"; code: string; message: string; operation_id?: string; shape?: Shape };

export type PendingOperation = { command: DurableCommand; wire: string; recoveryReplay: boolean };
export type OptimisticIntent = { kind: "shape"; shape: Shape } | { kind: "delete"; shapeId: string };

export type EditorState = {
  phase: "loading" | "ready" | "reconnecting" | "recovering" | "failed";
  canvas: CanvasSnapshot | null;
  canvasRevision: number;
  shapes: Record<string, Shape>;
  connectionId: string | null;
  peers: Record<string, Peer>;
  tool: Tool;
  defaultColor: string;
  lineArrowDefaults: LineArrowDefaults;
  selectionId: string | null;
  interaction: Interaction;
  pending: PendingOperation | null;
  optimistic: OptimisticIntent | null;
  undoIds: string[];
  redoIds: string[];
  notice: string | null;
  recoveredTextDraft: { shapeId: string | null; text: string; properties: TextProperties } | null;
  recovery: "none" | "retry-command" | "reset-history";
};

export const initialEditorState: EditorState = {
  phase: "loading",
  canvas: null,
  canvasRevision: 0,
  shapes: {},
  connectionId: null,
  peers: {},
  tool: "select",
  defaultColor: "#f6e8bd",
  lineArrowDefaults: { start_arrow: false, end_arrow: false },
  selectionId: null,
  interaction: { kind: "idle" },
  pending: null,
  optimistic: null,
  undoIds: [],
  redoIds: [],
  notice: null,
  recoveredTextDraft: null,
  recovery: "none",
};

export function isBoxShape(shape: Shape): shape is Extract<Shape, { kind: "rectangle" | "ellipse" | "text" }> {
  return shape.kind !== "line";
}
