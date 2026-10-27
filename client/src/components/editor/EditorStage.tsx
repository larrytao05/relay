import { useRef, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { BOARD_HEIGHT, BOARD_WIDTH, pointFromClient, shapeBounds } from "../../editor/geometry.ts";
import { isTextWithinLimit, TEXT_LENGTH_ERROR_MESSAGE } from "../../editor/text.ts";
import type { Interaction, Peer, Point, ResizeHandle, Shape, Tool } from "../../editor/types.ts";
import LineRenderer from "./LineRenderer.tsx";

export default function EditorStage({
  title,
  tool,
  disabled,
  shapes,
  selectedId,
  peers,
  interaction,
  preview,
  onBackgroundStart,
  onBeginMove,
  onBeginResize,
  onMove,
  onFinish,
  onCancel,
  onEditText,
  onTextDraft,
  onCommitText,
  onCancelText,
  onCursor,
}: {
  title: string;
  tool: Tool;
  disabled: boolean;
  shapes: Shape[];
  selectedId: string | null;
  peers: Peer[];
  interaction: Interaction;
  preview: Shape | null;
  onBackgroundStart(point: Point): void;
  onBeginMove(shape: Shape, point: Point): void;
  onBeginResize(shape: Shape, handle: ResizeHandle, point: Point): void;
  onMove(point: Point): void;
  onFinish(point: Point): void;
  onCancel(): void;
  onEditText(shape: Extract<Shape, { kind: "text" }>): void;
  onTextDraft(text: string): void;
  onCommitText(sessionId: string): void;
  onCancelText(sessionId: string): void;
  onCursor(point: Point | null): void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const releasedPointerId = useRef<number | null>(null);
  const textSession = interaction.kind === "editingText" ? interaction : null;
  const visibleShapes = shapes.filter((shape) => !shape.deleted);

  function pointFor(clientX: number, clientY: number): Point | null {
    return svgRef.current ? pointFromClient(svgRef.current, clientX, clientY) : null;
  }

  function handlePointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (disabled || event.button !== 0) return;
    // Let the active textarea blur and commit before another canvas action can
    // replace its editing session.
    if (interaction.kind === "editingText") return;
    const point = pointFor(event.clientX, event.clientY);
    if (!point) return;
    onCursor(point);

    // Text is placed on click; it does not need a captured drag gesture.
    if (tool === "text") return;

    releasedPointerId.current = null;
    event.currentTarget.setPointerCapture(event.pointerId);

    const element = event.target as Element;
    const handle = element.closest("[data-resize-handle]")?.getAttribute("data-resize-handle") as ResizeHandle | null;
    const shapeId = element.closest("[data-shape-id]")?.getAttribute("data-shape-id");
    const targetShape = shapeId ? visibleShapes.find((shape) => shape.id === shapeId) : undefined;
    if (tool === "select" && targetShape && handle) {
      onBeginResize(targetShape, handle, point);
      return;
    }
    if (tool === "select" && targetShape) {
      onBeginMove(targetShape, point);
      return;
    }
    onBackgroundStart(point);
  }

  function handleClick(event: React.MouseEvent<SVGSVGElement>) {
    if (disabled || tool !== "text" || interaction.kind !== "idle") return;
    const point = pointFor(event.clientX, event.clientY);
    if (!point) return;
    onCursor(point);
    onBackgroundStart(point);
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const point = pointFor(event.clientX, event.clientY);
    if (!point) return;
    onCursor(point);
    if (interaction.kind !== "idle" && interaction.kind !== "editingText") onMove(point);
  }

  function handlePointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    const point = pointFor(event.clientX, event.clientY);
    if (point && interaction.kind !== "idle" && interaction.kind !== "editingText") onFinish(point);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      releasedPointerId.current = event.pointerId;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handlePointerCancel(event: ReactPointerEvent<SVGSVGElement>) {
    if (interaction.kind !== "idle" && interaction.kind !== "editingText") onCancel();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      releasedPointerId.current = event.pointerId;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleLostPointerCapture(event: ReactPointerEvent<SVGSVGElement>) {
    if (releasedPointerId.current === event.pointerId) {
      releasedPointerId.current = null;
      return;
    }
    if (interaction.kind !== "idle" && interaction.kind !== "editingText") onCancel();
  }

  function handleDoubleClick(event: React.MouseEvent<SVGSVGElement>) {
    const id = (event.target as Element).closest("[data-shape-id]")?.getAttribute("data-shape-id");
    const shape = visibleShapes.find((candidate) => candidate.id === id);
    if (shape?.kind === "text" && !disabled) onEditText(shape);
  }

  function textKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancelText(textSession!.sessionId);
    } else if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onCommitText(textSession!.sessionId);
    }
  }

  return (
    <section className={`editor-stage${disabled ? " is-readonly" : ""}`} aria-label="Whiteboard">
      <div className="editor-canvas-label">{title}</div>
      <div className="editor-board-wrap">
        <div className="editor-board">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${BOARD_WIDTH} ${BOARD_HEIGHT}`}
            role="application"
            aria-label={`${title} whiteboard`}
            data-tool={tool}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerCancel}
            onLostPointerCapture={handleLostPointerCapture}
            onClick={handleClick}
            onDoubleClick={handleDoubleClick}
            onPointerLeave={(event) => { if (!event.currentTarget.hasPointerCapture(event.pointerId)) onCursor(null); }}
          >
            <rect data-board-surface x="0" y="0" width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="transparent" />
            {visibleShapes.map((shape) => <ShapeView key={shape.id} shape={preview?.id === shape.id && !preview.deleted ? preview : shape} />)}
            {preview && !preview.deleted && !visibleShapes.some((shape) => shape.id === preview.id) && <ShapeView shape={preview} />}
            {selectedId && visibleShapes.some((shape) => shape.id === selectedId) && (
              <SelectionOutline shape={preview?.id === selectedId ? preview : visibleShapes.find((shape) => shape.id === selectedId)!} />
            )}
            {interaction.kind === "creating" && <CreationPreview interaction={interaction} />}
            {peers.filter((peer) => peer.cursor !== null).map((peer) => (
              <RemoteCursor key={peer.connection_id} peer={peer} />
            ))}
          </svg>
          {textSession && (
            <textarea
              className="editor-text-editor"
              autoFocus
              aria-label="Edit text on whiteboard"
              value={textSession.draft}
              style={{
                left: `${(textSession.start.x / BOARD_WIDTH) * 100}%`,
                top: `${(textSession.start.y / BOARD_HEIGHT) * 100}%`,
                width: `${(textSession.width / BOARD_WIDTH) * 100}%`,
                height: `${(textSession.height / BOARD_HEIGHT) * 100}%`,
                color: textSession.color,
                fontSize: `${textSession.fontSize * ((svgRef.current?.clientWidth ?? BOARD_WIDTH) / BOARD_WIDTH)}px`,
              }}
              onChange={(event) => onTextDraft(event.currentTarget.value)}
              onBlur={() => onCommitText(textSession.sessionId)}
              onKeyDown={textKeyDown}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            />
          )}
          {textSession && !isTextWithinLimit(textSession.draft) && <p className="editor-text-error" role="alert">{TEXT_LENGTH_ERROR_MESSAGE}</p>}
        </div>
      </div>
      <p className="editor-stage-hint">
        {disabled
          ? "Connect to edit this canvas"
          : textSession
            ? "Enter to save · Shift+Enter for a new line · Esc to cancel"
            : "Select an object to see its properties"}
      </p>
    </section>
  );
}

function ShapeView({ shape }: { shape: Shape }) {
  if (shape.kind === "rectangle") {
    const p = shape.properties;
    return <g data-shape-id={shape.id} opacity={p.opacity}><rect x={p.x} y={p.y} width={p.width} height={p.height} rx="10" fill={p.color} stroke={p.color} strokeWidth="1.5" /></g>;
  }
  if (shape.kind === "ellipse") {
    const p = shape.properties;
    return <g data-shape-id={shape.id} opacity={p.opacity}><ellipse cx={p.x + p.width / 2} cy={p.y + p.height / 2} rx={p.width / 2} ry={p.height / 2} fill={p.color} stroke={p.color} strokeWidth="1.5" /></g>;
  }
  if (shape.kind === "line") {
    return <LineRenderer properties={shape.properties} shapeId={shape.id} />;
  }
  if (shape.kind !== "text") return null;
  const p = shape.properties;
  return <g data-shape-id={shape.id} opacity={p.opacity}>
    <foreignObject x={p.x} y={p.y} width={p.width} height={p.height}>
      <div style={{ width: "100%", height: "100%", overflow: "hidden", whiteSpace: "pre-wrap", overflowWrap: "anywhere", color: p.color, fontSize: p.font_size, lineHeight: 1.35 }}>{p.text}</div>
    </foreignObject>
  </g>;
}

function SelectionOutline({ shape }: { shape: Shape }) {
  const b = shapeBounds(shape);
  const handles: { name: ResizeHandle; x: number; y: number }[] = shape.kind === "line"
    ? [{ name: "start", x: shape.properties.x1, y: shape.properties.y1 }, { name: "end", x: shape.properties.x2, y: shape.properties.y2 }]
    : [{ name: "nw", x: b.x, y: b.y }, { name: "ne", x: b.x + b.width, y: b.y }, { name: "sw", x: b.x, y: b.y + b.height }, { name: "se", x: b.x + b.width, y: b.y + b.height }];
  return <g className="selection-outline" data-shape-id={shape.id}>
    {shape.kind === "line" ? <line x1={shape.properties.x1} y1={shape.properties.y1} x2={shape.properties.x2} y2={shape.properties.y2} /> : <rect x={b.x} y={b.y} width={b.width} height={b.height} />}
    {handles.map((handle) => <circle key={handle.name} data-resize-handle={handle.name} cx={handle.x} cy={handle.y} r="5" />)}
  </g>;
}

function CreationPreview({ interaction }: { interaction: Extract<Interaction, { kind: "creating" }> }) {
  const { start, current, color } = interaction;
  if (interaction.shapeKind === "line") return <LineRenderer className="creation-preview" properties={{ x1: start.x, y1: start.y, x2: current.x, y2: current.y, color, opacity: 1, start_arrow: interaction.start_arrow, end_arrow: interaction.end_arrow }} />;
  const x = Math.min(start.x, current.x);
  const y = Math.min(start.y, current.y);
  const width = Math.abs(current.x - start.x);
  const height = Math.abs(current.y - start.y);
  return interaction.shapeKind === "ellipse"
    ? <ellipse className="creation-preview" cx={x + width / 2} cy={y + height / 2} rx={width / 2} ry={height / 2} stroke={color} />
    : <rect className="creation-preview" x={x} y={y} width={width} height={height} stroke={color} />;
}

function RemoteCursor({ peer }: { peer: Peer }) {
  if (!peer.cursor) return null;
  const hue = [...peer.user.username].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 360;
  const color = `hsl(${hue} 54% 46%)`;
  return <g className="remote-cursor-svg" transform={`translate(${peer.cursor.x} ${peer.cursor.y})`} style={{ color }} aria-label={`${peer.user.username}'s cursor`}>
    <path d="M1 1 14 12l-5.5.5L6 18 1 1Z" fill="currentColor" stroke="white" strokeWidth="1.2" strokeLinejoin="round" />
    <text x="13" y="23" fill="white" stroke="currentColor" strokeWidth="5" strokeLinejoin="round" paintOrder="stroke" fontSize="11" fontWeight="600">{peer.user.username}</text>
    <text x="13" y="23" fill="white" fontSize="11" fontWeight="600">{peer.user.username}</text>
  </g>;
}
