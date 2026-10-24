import { useCallback, useEffect, useReducer, useRef } from "react";
import { editorReducer, type EditorAction } from "./reducer.ts";
import { parseServerEvent } from "./protocol.ts";
import { isRevisionGap, shouldRetrySocketClose } from "./recovery.ts";
import { isTextWithinLimit, TEXT_LENGTH_ERROR_MESSAGE } from "./text.ts";
import { initialEditorState, type DurableCommand, type EditorState, type OptimisticIntent, type Point, type ServerEvent } from "./types.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type SessionAction = EditorAction | { type: "session.reset" };

function sessionReducer(state: EditorState, action: SessionAction): EditorState {
  return action.type === "session.reset" ? initialEditorState : editorReducer(state, action);
}

export function useCanvasSession(canvasId: string | undefined) {
  const [state, dispatch] = useReducer(sessionReducer, initialEditorState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generationRef = useRef(0);
  const cancelledRef = useRef(false);
  const pendingGuard = useRef(false);
  const retryAttempt = useRef(0);
  const activeCanvasId = useRef<string | undefined>(canvasId);
  const cursorRef = useRef<{ point: Point | null; timer: ReturnType<typeof setTimeout> | null; sentAt: number }>({ point: null, timer: null, sentAt: 0 });

  useEffect(() => {
    cancelledRef.current = false;
    activeCanvasId.current = canvasId;
    pendingGuard.current = false;
    cursorRef.current.point = null;
    cursorRef.current.sentAt = 0;
    if (cursorRef.current.timer) clearTimeout(cursorRef.current.timer);
    cursorRef.current.timer = null;
    dispatch({ type: "session.reset" });
    if (!canvasId || !UUID.test(canvasId)) {
      dispatch({ type: "connection.failed", message: "This canvas address is invalid." });
      return () => { cancelledRef.current = true; };
    }
    const routeCanvasId = canvasId;

    function connect() {
      if (cancelledRef.current) return;
      dispatch({ type: "connection.started" });
      const generation = ++generationRef.current;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${protocol}//${window.location.host}/ws/canvases/${encodeURIComponent(routeCanvasId)}`);
      let protocolFailure: string | null = null;
      socketRef.current = socket;

      socket.onopen = () => { retryAttempt.current = 0; };
      socket.onmessage = (message) => {
        if (generation !== generationRef.current) return;
        if (typeof message.data !== "string") {
          protocolFailure = "The server sent an unsupported message frame.";
          dispatch({ type: "connection.failed", message: protocolFailure });
          socket.close(4002, "Invalid server event");
          return;
        }
        let event: ServerEvent;
        try {
          event = parseServerEvent(message.data);
        } catch (error) {
          protocolFailure = error instanceof Error ? error.message : "The server sent an unreadable update.";
          dispatch({ type: "connection.failed", message: protocolFailure });
          socket.close(4002, "Invalid server event");
          return;
        }

        if (event.type === "snapshot") {
          dispatch({ type: "snapshot", event });
          const current = stateRef.current;
          if (activeCanvasId.current === event.canvas.id && current.canvas?.id === event.canvas.id && current.recovery === "retry-command" && current.pending) {
            try {
              socket.send(current.pending.wire);
              dispatch({ type: "pending.retried" });
            } catch {
              socket.close();
            }
          }
          return;
        }

        const current = stateRef.current;
        if (event.type === "operation.applied" && isRevisionGap(current.canvasRevision, event.canvas_revision)) {
          dispatch({ type: "notice", message: "The canvas changed while reconnecting. Reloading the latest version…" });
          socket.close(4003, "Canvas revision gap");
          return;
        }

        const settlesPending = event.type === "operation.applied"
          ? current.pending?.command.operation_id === event.operation_id
          : event.type === "error" && event.operation_id !== undefined && current.pending?.command.operation_id === event.operation_id;
        const recoveryReplaySettled = settlesPending && current.pending?.recoveryReplay;
        dispatch({ type: "event", event });
        if (settlesPending) pendingGuard.current = false;
        if (recoveryReplaySettled) socket.close(4004, "Reset connection-local history");
        if (event.type === "error" && event.code === "access_revoked") socket.close(1008, "Canvas access revoked");
      };

      socket.onclose = (event) => {
        if (generation !== generationRef.current) return;
        socketRef.current = null;
        if (cancelledRef.current) return;
        if (protocolFailure) return;
        if (event.code === 4002) {
          dispatch({ type: "connection.failed", message: "The server sent an invalid update. Reload the canvas to try again." });
          return;
        }
        if (!shouldRetrySocketClose(event.code)) {
          dispatch({ type: "connection.failed", message: "This canvas is unavailable or your access has expired. Return to canvases and sign in again." });
          return;
        }
        dispatch({ type: "connection.started" });
        const delay = Math.min(500 * 2 ** retryAttempt.current, 10_000);
        retryAttempt.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };
      socket.onerror = () => {
        // Browsers hide pre-accept HTTP details; the close handler reconnects safely.
      };
    }

    connect();
    return () => {
      cancelledRef.current = true;
      pendingGuard.current = false;
      generationRef.current += 1;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (cursorRef.current.timer) clearTimeout(cursorRef.current.timer);
      socketRef.current?.close(1000, "Canvas editor closed");
      socketRef.current = null;
    };
  }, [canvasId]);

  const sendOperation = useCallback((command: DurableCommand, optimistic: OptimisticIntent | null = null): boolean => {
    const socket = socketRef.current;
    const current = stateRef.current;
    const text = command.type === "shape.create" && command.kind === "text" && "text" in command.properties
      ? command.properties.text
      : command.type === "shape.update" && typeof command.patch.text === "string"
        ? command.patch.text
        : null;
    if (text !== null && !isTextWithinLimit(text)) {
      dispatch({ type: "notice", message: TEXT_LENGTH_ERROR_MESSAGE });
      return false;
    }
    if (pendingGuard.current || current.pending || current.phase !== "ready") return false;
    if (socket?.readyState !== WebSocket.OPEN) {
      dispatch({ type: "notice", message: "The connection is reconnecting. Try that change again when it is ready." });
      return false;
    }
    const wire = JSON.stringify(command);
    pendingGuard.current = true;
    dispatch({ type: "pending", command: { command, wire, recoveryReplay: false }, optimistic });
    try {
      socket.send(wire);
      return true;
    } catch {
      pendingGuard.current = false;
      dispatch({ type: "notice", message: "The change could not be sent. Reconnecting to check its status." });
      socket.close();
      return false;
    }
  }, []);

  const sendCursor = useCallback((position: Point | null) => {
    const schedule = cursorRef.current;
    schedule.point = position;
    if (position === null && schedule.timer) {
      clearTimeout(schedule.timer);
      schedule.timer = null;
    }
    const send = () => {
      schedule.timer = null;
      const activeSocket = socketRef.current;
      if (activeSocket?.readyState === WebSocket.OPEN) {
        try {
          activeSocket.send(JSON.stringify({ type: "cursor", position: schedule.point }));
          schedule.sentAt = Date.now();
        } catch {
          activeSocket.close();
        }
      }
    };
    if (position === null || Date.now() - schedule.sentAt >= 50) send();
    else if (!schedule.timer) schedule.timer = setTimeout(send, 50 - (Date.now() - schedule.sentAt));
  }, []);

  useEffect(() => {
    const hideCursor = () => sendCursor(null);
    const visibilityChanged = () => { if (document.hidden) hideCursor(); };
    window.addEventListener("blur", hideCursor);
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      window.removeEventListener("blur", hideCursor);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [sendCursor]);

  const undo = useCallback(() => {
    const target = stateRef.current.undoIds.at(-1);
    return target ? sendOperation({ type: "undo", operation_id: crypto.randomUUID(), target_operation_id: target }) : false;
  }, [sendOperation]);
  const redo = useCallback(() => {
    const target = stateRef.current.redoIds.at(-1);
    return target ? sendOperation({ type: "redo", operation_id: crypto.randomUUID(), target_operation_id: target }) : false;
  }, [sendOperation]);

  return { state, dispatch, sendOperation, sendCursor, undo, redo };
}
