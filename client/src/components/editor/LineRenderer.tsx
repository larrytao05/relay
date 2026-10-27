import type { LineProperties } from "../../editor/types.ts";
import { lineArrowheadPoints } from "../../editor/geometry.ts";

export default function LineRenderer({ properties, className, shapeId }: { properties: Pick<LineProperties, "x1" | "y1" | "x2" | "y2" | "color" | "opacity" | "start_arrow" | "end_arrow">; className?: string; shapeId?: string }) {
  const start = properties.start_arrow && lineArrowheadPoints(properties.x1, properties.y1, properties.x2, properties.y2, false);
  const end = properties.end_arrow && lineArrowheadPoints(properties.x1, properties.y1, properties.x2, properties.y2, true);
  return <g data-shape-id={shapeId} className={className} opacity={properties.opacity}>
    <line x1={properties.x1} y1={properties.y1} x2={properties.x2} y2={properties.y2} fill="none" stroke="transparent" strokeWidth="12" pointerEvents="stroke" />
    <line x1={properties.x1} y1={properties.y1} x2={properties.x2} y2={properties.y2} fill="none" stroke={properties.color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    {start && <polygon points={start.join(",")} fill={properties.color} />}
    {end && <polygon points={end.join(",")} fill={properties.color} />}
  </g>;
}
