export type CanvasPreviewKind = "checkout" | "account" | "planning";

export type CanvasSummary = {
  id: string;
  name: string;
  preview: CanvasPreviewKind;
};
