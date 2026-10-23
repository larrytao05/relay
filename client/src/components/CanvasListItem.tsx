import type { CanvasSummary } from "../types.ts";
import { Link } from "react-router";
import CanvasThumbnail from "./CanvasThumbnail.tsx";

export default function CanvasListItem({ canvas }: { canvas: CanvasSummary }) {
  return (
    <Link className="canvas-row" to={`/canvases/${canvas.id}`}>
      <span className="canvas-thumbnail">
        <CanvasThumbnail kind={canvas.preview} />
      </span>
      <span className="canvas-name">{canvas.name}</span>
      <svg className="open-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path
          d="m8 4 6 6-6 6"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </Link>
  );
}
