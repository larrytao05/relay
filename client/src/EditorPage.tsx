import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { useAuth } from "./AuthContext.tsx";
import EditorHeader, { type ConnectionStatus } from "./components/editor/EditorHeader.tsx";
import EditorStage from "./components/editor/EditorStage.tsx";
import EditorToolbar from "./components/editor/EditorToolbar.tsx";
import InviteDialog from "./components/editor/InviteDialog.tsx";
import SelectionInspector from "./components/editor/SelectionInspector.tsx";
import { BOARD_HEIGHT, BOARD_WIDTH, normalizedBox, previewShape, shapeBounds } from "./editor/geometry.ts";
import { isTextWithinLimit } from "./editor/text.ts";
import { useCanvasSession } from "./editor/useCanvasSession.ts";
import type { Interaction, Point, ResizeHandle, Shape, Tool } from "./editor/types.ts";
import "./EditorPage.css";

export default function EditorPage() {
  const { canvasId } = useParams();
  const { state: auth, logout } = useAuth();
  const user = auth.kind === "authenticated" ? auth.user : { id: "", username: "User" };
  const { state, dispatch, sendOperation, sendCursor, undo, redo } = useCanvasSession(canvasId);
  const [inviteOpen, setInviteOpen] = useState(false);
  const consumedTextSessions = useRef(new Set<string>());
  const interactionRef = useRef<Interaction>(state.interaction);
  const draftRef = useRef<{ sessionId: string; value: string } | null>(null);
  interactionRef.current = state.interaction;

  const editable = state.phase === "ready" && state.pending === null;
  const canonical = Object.values(state.shapes).filter((shape) => !shape.deleted);
  const optimistic = state.optimistic;
  let visibleShapes = canonical;
  if (optimistic?.kind === "delete") visibleShapes = visibleShapes.filter((shape) => shape.id !== optimistic.shapeId);
  if (optimistic?.kind === "shape") {
    const exists = visibleShapes.some((shape) => shape.id === optimistic.shape.id);
    visibleShapes = exists
      ? visibleShapes.map((shape) => shape.id === optimistic.shape.id ? optimistic.shape : shape)
      : [...visibleShapes, optimistic.shape];
  }
  const selected = visibleShapes.find((shape) => shape.id === state.selectionId) ?? null;
  const orderedShapes = [...visibleShapes].sort((a, b) => a.properties.z_index - b.properties.z_index || a.id.localeCompare(b.id));
  const selectedLayer = orderedShapes.findIndex((shape) => shape.id === selected?.id);
  const preview = getInteractionPreview(state.interaction);

  const setTool = useCallback((tool: Tool) => dispatch({ type: "tool", tool }), [dispatch]);

  const beginBackground = useCallback((point: Point) => {
    if (!editable) return;
    if (state.tool === "select") {
      dispatch({ type: "selection", id: null });
    } else if (state.tool === "text") {
      const width = 220;
      const height = 86;
      const x = Math.min(point.x, BOARD_WIDTH - width);
      const y = Math.min(point.y, BOARD_HEIGHT - height);
      const sessionId = crypto.randomUUID();
      consumedTextSessions.current.clear();
      draftRef.current = { sessionId, value: "" };
      dispatch({ type: "interaction", interaction: { kind: "editingText", sessionId, shapeId: null, expectedRevision: null, start: { x, y }, width, height, color: state.defaultColor, fontSize: 16, draft: "" } });
    } else {
      dispatch({ type: "interaction", interaction: { kind: "creating", shapeKind: state.tool, start: point, current: point, color: state.defaultColor } });
    }
  }, [dispatch, editable, state.defaultColor, state.tool]);

  const beginMove = useCallback((shape: Shape, point: Point) => {
    if (!editable) return;
    dispatch({ type: "selection", id: shape.id });
    dispatch({ type: "interaction", interaction: { kind: "moving", shapeId: shape.id, expectedRevision: shape.revision, baseline: shape, start: point, current: point } });
  }, [dispatch, editable]);

  const beginResize = useCallback((shape: Shape, handle: ResizeHandle, point: Point) => {
    if (!editable) return;
    dispatch({ type: "selection", id: shape.id });
    dispatch({ type: "interaction", interaction: { kind: "resizing", shapeId: shape.id, expectedRevision: shape.revision, baseline: shape, handle, start: point, current: point } });
  }, [dispatch, editable]);

  const moveInteraction = useCallback((point: Point) => {
    const active = interactionRef.current;
    if (active.kind === "creating" || active.kind === "moving" || active.kind === "resizing") {
      dispatch({ type: "interaction", interaction: { ...active, current: point } });
    }
  }, [dispatch]);

  const finishInteraction = useCallback((point: Point) => {
    const active = interactionRef.current;
    if (active.kind === "creating") {
      let shape: Shape | null = null;
      if (active.shapeKind === "line") {
        if (Math.hypot(point.x - active.start.x, point.y - active.start.y) >= 8) {
          shape = { id: crypto.randomUUID(), kind: "line", revision: 1, deleted: false, properties: { x1: active.start.x, y1: active.start.y, x2: point.x, y2: point.y, color: active.color, opacity: 1, z_index: nextZIndex(state.shapes) } };
        }
      } else {
        const box = normalizedBox(active.start, point, active.color);
        if (box) shape = { id: crypto.randomUUID(), kind: active.shapeKind, revision: 1, deleted: false, properties: { ...box, opacity: 1, z_index: nextZIndex(state.shapes) } };
      }
      if (shape) {
        const command = { type: "shape.create" as const, operation_id: crypto.randomUUID(), shape_id: shape.id, kind: shape.kind, properties: shape.properties };
        if (sendOperation(command, { kind: "shape", shape })) dispatch({ type: "selection", id: shape.id });
      }
      dispatch({ type: "interaction", interaction: { kind: "idle" } });
      return;
    }
    if (active.kind === "moving" || active.kind === "resizing") {
      const next = active.kind === "moving"
        ? moveWithinBoard(active.baseline, active.start, point)
        : previewShape(active.baseline, active.start, point, active.handle);
      const patch = shapePatch(active.baseline, next);
      if (Object.keys(patch).length > 0) {
        sendOperation({ type: "shape.update", operation_id: crypto.randomUUID(), shape_id: active.shapeId, expected_revision: active.expectedRevision, patch }, { kind: "shape", shape: next });
      }
      dispatch({ type: "interaction", interaction: { kind: "idle" } });
    }
  }, [dispatch, sendOperation, state.shapes]);

  const beginTextEdit = useCallback((shape: Extract<Shape, { kind: "text" }>) => {
    if (!editable) return;
    const sessionId = crypto.randomUUID();
    consumedTextSessions.current.clear();
    draftRef.current = { sessionId, value: shape.properties.text };
    dispatch({ type: "selection", id: shape.id });
    dispatch({ type: "interaction", interaction: { kind: "editingText", sessionId, shapeId: shape.id, expectedRevision: shape.revision, start: { x: shape.properties.x, y: shape.properties.y }, width: shape.properties.width, height: shape.properties.height, color: shape.properties.color, fontSize: shape.properties.font_size, draft: shape.properties.text } });
  }, [dispatch, editable]);

  const changeTextDraft = useCallback((draft: string) => {
    const active = interactionRef.current;
    if (active.kind !== "editingText") return;
    draftRef.current = { sessionId: active.sessionId, value: draft };
    dispatch({ type: "text.draft", draft });
  }, [dispatch]);

  const cancelText = useCallback((sessionId: string) => {
    if (consumedTextSessions.current.has(sessionId)) return;
    consumedTextSessions.current.add(sessionId);
    if (interactionRef.current.kind === "editingText" && interactionRef.current.sessionId === sessionId) {
      draftRef.current = null;
      dispatch({ type: "interaction", interaction: { kind: "idle" } });
    }
  }, [dispatch]);

  const commitText = useCallback((sessionId: string) => {
    if (consumedTextSessions.current.has(sessionId)) return;
    const active = interactionRef.current;
    if (active.kind !== "editingText" || active.sessionId !== sessionId) return;
    const value = draftRef.current?.sessionId === sessionId ? draftRef.current.value : active.draft;
    if (!isTextWithinLimit(value)) return;
    consumedTextSessions.current.add(sessionId);
    draftRef.current = null;
    if (!active.shapeId) {
      if (!value.trim()) {
        dispatch({ type: "interaction", interaction: { kind: "idle" } });
        return;
      }
      const shape: Shape = { id: crypto.randomUUID(), kind: "text", revision: 1, deleted: false, properties: { x: active.start.x, y: active.start.y, width: active.width, height: active.height, text: value, font_size: active.fontSize, color: active.color, opacity: 1, z_index: nextZIndex(state.shapes) } };
      const command = { type: "shape.create" as const, operation_id: crypto.randomUUID(), shape_id: shape.id, kind: "text" as const, properties: shape.properties };
      if (sendOperation(command, { kind: "shape", shape })) dispatch({ type: "selection", id: shape.id });
    } else {
      const original = state.shapes[active.shapeId];
      if (original?.kind === "text" && original.properties.text !== value) {
        const shape: Shape = { ...original, properties: { ...original.properties, text: value } };
        sendOperation({ type: "shape.update", operation_id: crypto.randomUUID(), shape_id: original.id, expected_revision: active.expectedRevision!, patch: { text: value } }, { kind: "shape", shape });
      }
    }
    dispatch({ type: "interaction", interaction: { kind: "idle" } });
  }, [dispatch, sendOperation, state.shapes]);

  const reapplyRecoveredText = useCallback(() => {
    const recovered = state.recoveredTextDraft;
    if (!recovered || !editable) return;

    const current = recovered.shapeId ? state.shapes[recovered.shapeId] : null;
    const existing = current?.kind === "text" && !current.deleted ? current : null;
    const properties = existing?.properties ?? recovered.properties;
    const draftText = recovered.properties.text;
    const sessionId = crypto.randomUUID();
    consumedTextSessions.current.clear();
    draftRef.current = { sessionId, value: draftText };
    if (existing) dispatch({ type: "selection", id: existing.id });
    dispatch({
      type: "interaction",
      interaction: {
        kind: "editingText",
        sessionId,
        shapeId: existing?.id ?? null,
        expectedRevision: existing?.revision ?? null,
        start: { x: properties.x, y: properties.y },
        width: properties.width,
        height: properties.height,
        color: properties.color,
        fontSize: properties.font_size,
        draft: draftText,
      },
    });
    dispatch({ type: "recovered-text.dismiss" });
  }, [dispatch, editable, state.recoveredTextDraft, state.shapes]);

  const changeColor = useCallback((color: string) => {
    if (!selected) {
      dispatch({ type: "color", color });
      return;
    }
    if (!editable) return;
    const shape = withColor(selected, color);
    sendOperation({ type: "shape.update", operation_id: crypto.randomUUID(), shape_id: selected.id, expected_revision: selected.revision, patch: { color } }, { kind: "shape", shape });
  }, [dispatch, editable, selected, sendOperation]);

  const changeAppearance = useCallback((patch: { opacity?: number; z_index?: number }) => {
    if (!selected || !editable) return;
    const shape = withAppearance(selected, patch);
    sendOperation({ type: "shape.update", operation_id: crypto.randomUUID(), shape_id: selected.id, expected_revision: selected.revision, patch }, { kind: "shape", shape });
  }, [editable, selected, sendOperation]);

  const moveSelectedToFront = useCallback(() => {
    if (!selected || !editable) return;
    const highest = Math.max(...visibleShapes.map((shape) => shape.properties.z_index));
    changeAppearance({ z_index: highest + 1 });
  }, [changeAppearance, editable, selected, visibleShapes]);

  const moveSelectedToBack = useCallback(() => {
    if (!selected || !editable) return;
    const lowest = Math.min(...visibleShapes.map((shape) => shape.properties.z_index));
    changeAppearance({ z_index: lowest - 1 });
  }, [changeAppearance, editable, selected, visibleShapes]);

  const deleteSelection = useCallback(() => {
    if (!selected || !editable) return;
    if (sendOperation({ type: "shape.delete", operation_id: crypto.randomUUID(), shape_id: selected.id, expected_revision: selected.revision }, { kind: "delete", shapeId: selected.id })) {
      dispatch({ type: "selection", id: null });
    }
  }, [dispatch, editable, selected, sendOperation]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.isComposing) return;
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (editable && !state.pending) {
          if (event.shiftKey) redo();
          else undo();
        }
      } else if (event.ctrlKey && event.key.toLowerCase() === "y") {
        event.preventDefault();
        if (editable && !state.pending) redo();
      } else if (!mod && !event.altKey && !event.repeat && (event.key === "Delete" || event.key === "Backspace")) {
        event.preventDefault();
        deleteSelection();
      } else if (!mod && !event.altKey && !event.repeat) {
        const keyTools: Record<string, Tool> = { v: "select", r: "rectangle", o: "ellipse", l: "line", t: "text" };
        const tool = keyTools[event.key.toLowerCase()];
        if (tool && editable) setTool(tool);
        if (event.key === "Escape" && state.interaction.kind !== "idle") {
          if (state.interaction.kind === "editingText") cancelText(state.interaction.sessionId);
          else dispatch({ type: "interaction", interaction: { kind: "idle" } });
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [cancelText, deleteSelection, dispatch, editable, redo, setTool, state.interaction, state.pending, undo]);

  const connectionStatus: ConnectionStatus = state.phase === "ready"
    ? state.pending ? "saving" : "ready"
    : state.phase;

  const allowLeave = useCallback(() => {
    if (state.pending) {
      dispatch({ type: "notice", message: "Wait for the current change to finish saving before leaving." });
      return false;
    }
    if (state.recoveredTextDraft) {
      dispatch({ type: "notice", message: "Reapply or dismiss the unsaved text before leaving this canvas." });
      return false;
    }
    if (state.interaction.kind !== "idle") {
      dispatch({ type: "notice", message: "Finish or cancel the current edit before leaving this canvas." });
      return false;
    }
    return true;
  }, [dispatch, state.interaction.kind, state.pending, state.recoveredTextDraft]);

  async function signOut() {
    if (!allowLeave()) return;
    try {
      await logout();
    } catch {
      dispatch({ type: "notice", message: "Couldn't sign out. Check your connection and try again." });
    }
  }

  return (
    <main className="editor-page">
      <EditorHeader title={state.canvas?.title ?? "Whiteboard"} status={connectionStatus} user={user} onInvite={() => setInviteOpen(true)} onBack={allowLeave} onLogout={() => { void signOut(); }} />
      <div className="editor-workspace">
        <EditorStage
          title={state.canvas?.title ?? "Whiteboard"}
          tool={state.tool}
          disabled={!editable}
          shapes={orderedShapes}
          selectedId={state.selectionId}
          peers={Object.values(state.peers)}
          interaction={state.interaction}
          preview={preview}
          onBackgroundStart={beginBackground}
          onBeginMove={beginMove}
          onBeginResize={beginResize}
          onMove={moveInteraction}
          onFinish={finishInteraction}
          onCancel={() => dispatch({ type: "interaction", interaction: { kind: "idle" } })}
          onEditText={beginTextEdit}
          onTextDraft={changeTextDraft}
          onCommitText={commitText}
          onCancelText={cancelText}
          onCursor={sendCursor}
        />
        <SelectionInspector selected={selected} shapes={visibleShapes} defaultColor={state.defaultColor} disabled={!editable} canBringToFront={selectedLayer >= 0 && selectedLayer < orderedShapes.length - 1} canSendToBack={selectedLayer > 0} onColor={changeColor} onOpacity={(opacity) => changeAppearance({ opacity })} onBringToFront={moveSelectedToFront} onSendToBack={moveSelectedToBack} onDelete={deleteSelection} />
        <EditorToolbar activeTool={state.tool} canUndo={state.undoIds.length > 0} canRedo={state.redoIds.length > 0} disabled={!editable} onTool={setTool} onUndo={undo} onRedo={redo} />
      </div>
      {(state.notice || state.recoveredTextDraft) && <div className="editor-notice" role={state.phase === "failed" || state.recoveredTextDraft ? "alert" : "status"}>
        {state.notice ?? "A text edit was interrupted before it could be saved."}
        {state.phase === "failed" && <a href="/canvases">Back to canvases</a>}
        {state.recoveredTextDraft && <>
          <span className="editor-recovered-preview">“{state.recoveredTextDraft.properties.text.slice(0, 48)}{state.recoveredTextDraft.properties.text.length > 48 ? "…" : ""}”</span>
          <button type="button" className="editor-notice-action" disabled={!editable} onClick={reapplyRecoveredText}>Reapply text</button>
          <button type="button" aria-label="Dismiss recovered text" onClick={() => dispatch({ type: "recovered-text.dismiss" })}>×</button>
        </>}
        {state.notice && <button type="button" aria-label="Dismiss message" onClick={() => dispatch({ type: "notice", message: null })}>×</button>}
      </div>}
      {inviteOpen && canvasId && <InviteDialog canvasId={canvasId} onClose={() => setInviteOpen(false)} />}
    </main>
  );
}

function getInteractionPreview(interaction: Interaction): Shape | null {
  if (interaction.kind === "moving") return moveWithinBoard(interaction.baseline, interaction.start, interaction.current);
  if (interaction.kind === "resizing") return previewShape(interaction.baseline, interaction.start, interaction.current, interaction.handle);
  return null;
}

function moveWithinBoard(shape: Shape, start: Point, current: Point): Shape {
  const bounds = shapeBounds(shape);
  const dx = Math.max(-bounds.x, Math.min(BOARD_WIDTH - bounds.x - bounds.width, current.x - start.x));
  const dy = Math.max(-bounds.y, Math.min(BOARD_HEIGHT - bounds.y - bounds.height, current.y - start.y));
  return previewShape(shape, start, { x: start.x + dx, y: start.y + dy }, "move");
}

function shapePatch(before: Shape, after: Shape): Record<string, unknown> {
  const keys = before.kind === "line" ? ["x1", "y1", "x2", "y2"] : ["x", "y", "width", "height"];
  const patch: Record<string, unknown> = {};
  for (const key of keys) {
    const oldValue = before.properties[key as keyof typeof before.properties];
    const newValue = after.properties[key as keyof typeof after.properties];
    if (oldValue !== newValue) patch[key] = newValue;
  }
  return patch;
}

function withColor(shape: Shape, color: string): Shape {
  switch (shape.kind) {
    case "rectangle":
    case "ellipse":
      return { ...shape, properties: { ...shape.properties, color } };
    case "line":
      return { ...shape, properties: { ...shape.properties, color } };
    case "text":
      return { ...shape, properties: { ...shape.properties, color } };
    default: {
      const exhaustive: never = shape;
      return exhaustive;
    }
  }
}

function withAppearance(shape: Shape, patch: { opacity?: number; z_index?: number }): Shape {
  switch (shape.kind) {
    case "rectangle":
      return { ...shape, properties: { ...shape.properties, ...patch } };
    case "ellipse":
      return { ...shape, properties: { ...shape.properties, ...patch } };
    case "line":
      return { ...shape, properties: { ...shape.properties, ...patch } };
    case "text":
      return { ...shape, properties: { ...shape.properties, ...patch } };
    default: {
      const exhaustive: never = shape;
      return exhaustive;
    }
  }
}

function nextZIndex(shapes: Record<string, Shape>): number {
  const active = Object.values(shapes).filter((shape) => !shape.deleted);
  return active.length === 0 ? 0 : Math.max(...active.map((shape) => shape.properties.z_index)) + 1;
}
