import type { Point, ResizeHandle, Shape } from "./types.ts";

export const BOARD_WIDTH = 820;
export const BOARD_HEIGHT = 503;
export const MIN_SIZE = 8;

export function pointFromClient(svg: SVGSVGElement, clientX: number, clientY: number): Point | null {
  const matrix = svg.getScreenCTM();
  if (!matrix) return null;
  const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
  return {
    x: clamp(point.x, 0, BOARD_WIDTH),
    y: clamp(point.y, 0, BOARD_HEIGHT),
  };
}

export function shapeBounds(shape: Shape): { x: number; y: number; width: number; height: number } {
  if (shape.kind === "line") {
    const p = shape.properties;
    const x = Math.min(p.x1, p.x2);
    const y = Math.min(p.y1, p.y2);
    return { x, y, width: Math.abs(p.x2 - p.x1), height: Math.abs(p.y2 - p.y1) };
  }
  const p = shape.properties;
  return { x: p.x, y: p.y, width: p.width, height: p.height };
}

export function previewShape(shape: Shape, start: Point, current: Point, mode: "move" | ResizeHandle): Shape {
  const dx = current.x - start.x;
  const dy = current.y - start.y;
  if (mode === "move") return translateShape(shape, dx, dy);
  return resizeShape(shape, mode, current);
}

export function translateShape(shape: Shape, dx: number, dy: number): Shape {
  if (shape.kind === "line") {
    const p = shape.properties;
    return { ...shape, properties: { ...p, x1: p.x1 + dx, y1: p.y1 + dy, x2: p.x2 + dx, y2: p.y2 + dy } };
  }
  const p = shape.properties;
  return { ...shape, properties: { ...p, x: p.x + dx, y: p.y + dy } } as Shape;
}

export function resizeShape(shape: Shape, handle: ResizeHandle, point: Point): Shape {
  if (shape.kind === "line") {
    const p = shape.properties;
    const start = handle === "start";
    return { ...shape, properties: start ? { ...p, x1: point.x, y1: point.y } : { ...p, x2: point.x, y2: point.y } };
  }
  const p = shape.properties;
  let left = p.x;
  let top = p.y;
  let right = p.x + p.width;
  let bottom = p.y + p.height;
  if (handle.includes("w")) left = Math.min(point.x, right - MIN_SIZE);
  if (handle.includes("e")) right = Math.max(point.x, left + MIN_SIZE);
  if (handle.includes("n")) top = Math.min(point.y, bottom - MIN_SIZE);
  if (handle.includes("s")) bottom = Math.max(point.y, top + MIN_SIZE);
  const properties = { ...p, x: left, y: top, width: right - left, height: bottom - top };
  return { ...shape, properties } as Shape;
}

export function normalizedBox(start: Point, current: Point, color: string): { x: number; y: number; width: number; height: number; color: string } | null {
  const x = Math.min(start.x, current.x);
  const y = Math.min(start.y, current.y);
  const width = Math.abs(current.x - start.x);
  const height = Math.abs(current.y - start.y);
  if (width < MIN_SIZE || height < MIN_SIZE) return null;
  return { x, y, width, height, color };
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
