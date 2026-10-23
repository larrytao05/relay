import type { DurableCommand, EditorState, OptimisticIntent, ServerEvent, Shape, Tool } from "./types.ts";
import { initialEditorState } from "./types.ts";

export type EditorAction =
  | { type: "connection.started" }
  | { type: "snapshot"; event: Extract<ServerEvent, { type: "snapshot" }> }
  | { type: "event"; event: Exclude<ServerEvent, { type: "snapshot" }> }
  | { type: "pending"; command: EditorState["pending"]; optimistic: OptimisticIntent | null }
  | { type: "pending.retried" }
  | { type: "connection.failed"; message: string }
  | { type: "tool"; tool: Tool }
  | { type: "color"; color: string }
  | { type: "selection"; id: string | null }
  | { type: "interaction"; interaction: EditorState["interaction"] }
  | { type: "text.draft"; draft: string }
  | { type: "notice"; message: string | null }
  | { type: "recovered-text.dismiss" }
  | { type: "recovery.finished" };

export function editorReducer(state: EditorState = initialEditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "connection.started": {
      const recovery = state.recovery === "reset-history" ? state.recovery : state.pending ? "retry-command" : "none";
      return {
        ...state,
        phase: recovery === "none" ? (state.canvas ? "reconnecting" : "loading") : "recovering",
        recovery,
        peers: {},
        interaction: { kind: "idle" },
        undoIds: [],
        redoIds: [],
        recoveredTextDraft: getPendingTextDraft(state) ?? getActiveTextDraft(state) ?? state.recoveredTextDraft,
      };
    }
    case "snapshot": {
      const { event } = action;
      const shapes = Object.fromEntries(event.shapes.map((shape) => [shape.id, shape]));
      const peers = Object.fromEntries(event.connections.filter((peer) => peer.connection_id !== event.connection_id).map((peer) => [peer.connection_id, peer]));
      const resetFinished = state.recovery === "reset-history";
      return {
        ...state,
        phase: state.recovery === "retry-command" ? "recovering" : "ready",
        recovery: resetFinished ? "none" : state.recovery,
        canvas: event.canvas,
        canvasRevision: event.canvas_revision,
        shapes,
        connectionId: event.connection_id,
        peers,
        notice: null,
        selectionId: state.selectionId && shapes[state.selectionId] && !shapes[state.selectionId].deleted ? state.selectionId : null,
        interaction: { kind: "idle" },
        undoIds: resetFinished ? [] : state.undoIds,
        redoIds: resetFinished ? [] : state.redoIds,
      };
    }
    case "pending": return { ...state, pending: action.command, optimistic: action.optimistic };
    case "pending.retried":
      return state.pending ? { ...state, pending: { ...state.pending, recoveryReplay: true } } : state;
    case "tool": return { ...state, tool: action.tool, interaction: { kind: "idle" } };
    case "color": return { ...state, defaultColor: action.color };
    case "selection": return { ...state, selectionId: action.id, interaction: { kind: "idle" } };
    case "interaction": return { ...state, interaction: action.interaction };
    case "text.draft": return state.interaction.kind === "editingText" ? { ...state, interaction: { ...state.interaction, draft: action.draft } } : state;
    case "notice": return { ...state, notice: action.message };
    case "recovered-text.dismiss": return { ...state, recoveredTextDraft: null };
    case "connection.failed": return {
      ...state,
      phase: "failed",
      notice: action.message,
      interaction: { kind: "idle" },
      pending: null,
      optimistic: null,
      recovery: "none",
      recoveredTextDraft: getPendingTextDraft(state) ?? getActiveTextDraft(state) ?? state.recoveredTextDraft,
    };
    case "recovery.finished": return { ...state, phase: "ready", recovery: "none", undoIds: [], redoIds: [] };
    case "event": return reduceServerEvent(state, action.event);
  }
}

function reduceServerEvent(state: EditorState, event: Exclude<ServerEvent, { type: "snapshot" }>): EditorState {
  if (event.type === "presence.joined") return { ...state, peers: { ...state.peers, [event.connection.connection_id]: event.connection } };
  if (event.type === "presence.left") {
    const peers = { ...state.peers };
    delete peers[event.connection_id];
    return { ...state, peers };
  }
  if (event.type === "cursor") {
    const peer = state.peers[event.connection_id];
    return peer ? { ...state, peers: { ...state.peers, [event.connection_id]: { ...peer, cursor: event.position } } } : state;
  }
  if (event.type === "error") {
    const shapes = event.shape ? installNewerShape(state.shapes, event.shape) : state.shapes;
    const target = event.shape;
    const matched = event.operation_id !== undefined && state.pending?.command.operation_id === event.operation_id;
    const failedOptimisticCreate = matched && state.optimistic?.kind === "shape"
      && state.selectionId !== null
      && state.optimistic.shape.id === state.selectionId
      && !shapes[state.selectionId];
    const selectionId = failedOptimisticCreate || (target?.deleted && state.selectionId === target.id)
      ? null
      : matched && state.optimistic?.kind === "delete"
        ? state.optimistic.shapeId
        : state.selectionId;
    const recovery = matched && state.pending?.recoveryReplay ? "reset-history" : state.recovery;
    const interruptedDraft = target ? getInterruptedTextDraft(state, target.id) : null;
    const canonicalTextShape = target?.kind === "text" ? target : state.shapes[state.pending?.command.type === "shape.update" ? state.pending.command.shape_id : ""];
    const recoveredTextDraft = matched && state.pending
      ? getTextDraft(state.pending.command, canonicalTextShape) ?? interruptedDraft ?? state.recoveredTextDraft
      : interruptedDraft ?? state.recoveredTextDraft;
    return {
      ...state,
      phase: recovery === "reset-history" ? "recovering" : state.phase,
      recovery,
      shapes,
      selectionId,
      interaction: target && state.interaction.kind !== "idle" && "shapeId" in state.interaction && state.interaction.shapeId === target.id ? { kind: "idle" } : state.interaction,
      pending: matched ? null : state.pending,
      optimistic: matched ? null : state.optimistic,
      recoveredTextDraft,
      undoIds: recovery === "reset-history" ? [] : state.undoIds,
      redoIds: recovery === "reset-history" ? [] : state.redoIds,
      notice: event.message,
    };
  }

  const pending = state.pending;
  const isLocalAck = pending?.command.operation_id === event.operation_id;
  const isRecoveryAck = isLocalAck && pending.recoveryReplay;
  const isNewDocumentRevision = event.canvas_revision === state.canvasRevision + 1;
  const oldShape = state.shapes[event.shape.id];
  const remoteSupersedesShape = !isLocalAck && isNewDocumentRevision
    && event.shape.revision > (oldShape?.revision ?? 0);
  const shapes = isNewDocumentRevision ? installNewerShape(state.shapes, event.shape) : state.shapes;
  const matchedShape = shapes[event.shape.id];
  const selectionId = matchedShape?.deleted && state.selectionId === matchedShape.id ? null : state.selectionId;
  let undoIds = state.undoIds;
  let redoIds = state.redoIds;
  if (isLocalAck && !isRecoveryAck) {
    if (event.kind === "undo" && event.target_operation_id) {
      undoIds = removeLast(undoIds, event.target_operation_id);
      redoIds = [...redoIds, event.operation_id];
    } else if (event.kind === "redo" && event.target_operation_id) {
      redoIds = removeLast(redoIds, event.target_operation_id);
      undoIds = [...undoIds, event.operation_id];
    } else {
      undoIds = [...undoIds, event.operation_id];
      redoIds = [];
    }
  }
  const recovery = isRecoveryAck ? "reset-history" : state.recovery;
  const remoteSupersedesPreview = remoteSupersedesShape && (
    (state.optimistic?.kind === "shape" && state.optimistic.shape.id === event.shape.id && event.shape.revision > state.optimistic.shape.revision)
    || (state.optimistic?.kind === "delete" && state.optimistic.shapeId === event.shape.id
      && state.pending?.command.type === "shape.delete"
      && event.shape.revision > state.pending.command.expected_revision)
  );
  const interruptedDraft = remoteSupersedesShape ? getInterruptedTextDraft(state, event.shape.id) : null;
  const cancelsInteraction = remoteSupersedesShape
    && state.interaction.kind !== "idle"
    && "shapeId" in state.interaction
    && state.interaction.shapeId === event.shape.id;
  return {
    ...state,
    phase: recovery === "reset-history" ? "recovering" : state.phase,
    recovery,
    canvasRevision: isNewDocumentRevision ? event.canvas_revision : state.canvasRevision,
    shapes,
    selectionId,
    interaction: matchedShape?.deleted || cancelsInteraction ? { kind: "idle" } : state.interaction,
    pending: isLocalAck ? null : pending,
    optimistic: isLocalAck || remoteSupersedesPreview ? null : state.optimistic,
    undoIds: isRecoveryAck ? [] : undoIds,
    redoIds: isRecoveryAck ? [] : redoIds,
    recoveredTextDraft: interruptedDraft
      ?? (isLocalAck && pending && getTextShapeId(pending.command) === state.recoveredTextDraft?.shapeId ? null : state.recoveredTextDraft),
    notice: null,
  };
}

function getTextDraft(command: DurableCommand, canonicalShape: Shape | undefined): EditorState["recoveredTextDraft"] {
  if (command.type === "shape.create" && command.kind === "text" && "text" in command.properties) {
    return { shapeId: command.shape_id, text: command.properties.text, properties: command.properties };
  }
  if (command.type === "shape.update" && typeof command.patch.text === "string") {
    if (canonicalShape?.kind !== "text") return null;
    return { shapeId: command.shape_id, text: command.patch.text, properties: { ...canonicalShape.properties, text: command.patch.text } };
  }
  return null;
}

function getInterruptedTextDraft(state: EditorState, shapeId: string): EditorState["recoveredTextDraft"] {
  const interaction = state.interaction;
  const shape = state.shapes[shapeId];
  if (interaction.kind !== "editingText" || interaction.shapeId !== shapeId || shape?.kind !== "text") return null;
  return interaction.draft === shape.properties.text ? null : { shapeId, text: interaction.draft, properties: { ...shape.properties, text: interaction.draft } };
}

function getActiveTextDraft(state: EditorState): EditorState["recoveredTextDraft"] {
  const interaction = state.interaction;
  if (interaction.kind !== "editingText") return null;
  if (interaction.shapeId) return getInterruptedTextDraft(state, interaction.shapeId);
  if (!interaction.draft.trim()) return null;
  const properties = {
    x: interaction.start.x,
    y: interaction.start.y,
    width: interaction.width,
    height: interaction.height,
    text: interaction.draft,
    font_size: interaction.fontSize,
    color: interaction.color,
  };
  return { shapeId: null, text: interaction.draft, properties };
}

function getPendingTextDraft(state: EditorState): EditorState["recoveredTextDraft"] {
  if (!state.pending) return null;
  const command = state.pending.command;
  const shapeId = getTextShapeId(command);
  if (!shapeId) return null;
  const canonicalShape = state.shapes[shapeId];
  return getTextDraft(command, canonicalShape);
}

function getTextShapeId(command: DurableCommand): string | null {
  if (command.type === "shape.create" && command.kind === "text") return command.shape_id;
  if (command.type === "shape.update" && typeof command.patch.text === "string") return command.shape_id;
  return null;
}

function installNewerShape(shapes: Record<string, Shape>, incoming: Shape): Record<string, Shape> {
  const current = shapes[incoming.id];
  if (current && current.revision >= incoming.revision) return shapes;
  return { ...shapes, [incoming.id]: incoming };
}

function removeLast(items: string[], target: string): string[] {
  const index = items.lastIndexOf(target);
  return index < 0 ? items : [...items.slice(0, index), ...items.slice(index + 1)];
}
