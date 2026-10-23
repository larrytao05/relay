import type { Interaction, Shape } from "./types.ts";

const geometry = new Set(["x", "y", "width", "height", "x1", "y1", "x2", "y2"]);

export function changedProperties(before: Shape, after: Shape): string[] {
  const previous: Record<string, unknown> = before.properties;
  return Object.entries(after.properties).filter(([key, value]) => previous[key] !== value).map(([key]) => key);
}

export function propertiesConflict(local: string[], remote: string[]): boolean {
  return remote.some((key) => local.includes(key) || (geometry.has(key) && local.some((field) => geometry.has(field))));
}

export function withPropertyPatch(shape: Shape, patch: Record<string, unknown>): Shape {
  switch (shape.kind) {
    case "rectangle":
    case "ellipse": return { ...shape, properties: { ...shape.properties, ...patch } };
    case "line": return { ...shape, properties: { ...shape.properties, ...patch } };
    case "text": return { ...shape, properties: { ...shape.properties, ...patch } };
  }
}

export function rebaseInteraction(interaction: Interaction, before: Shape, after: Shape): Interaction {
  if (!("shapeId" in interaction) || interaction.shapeId !== after.id) return interaction;
  const touched = interaction.kind === "editingText" ? ["text"] : [...geometry];
  if (after.deleted || before.kind !== after.kind || propertiesConflict(touched, changedProperties(before, after))) return { kind: "idle" };
  if (interaction.kind === "editingText" && after.kind === "text") {
    const p = after.properties;
    return { ...interaction, start: { x: p.x, y: p.y }, width: p.width, height: p.height, color: p.color, fontSize: p.font_size };
  }
  if (interaction.kind === "moving" || interaction.kind === "resizing") return { ...interaction, baseline: after };
  return interaction;
}
