import type { Canvas } from "../types.ts";
import CanvasListItem from "./CanvasListItem.tsx";

export default function CanvasList({ canvases }: { canvases: Canvas[] }) {
  return (
    <section className="canvas-list" aria-label="Your canvases">
      <h2>Canvas</h2>
      {canvases.map((canvas) => (
        <CanvasListItem key={canvas.id} canvas={canvas} />
      ))}
    </section>
  );
}
