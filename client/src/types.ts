export type Canvas = {
  id: string;
  title: string;
  createdBy: string;
  revision: number;
  createdAt: string;
  updatedAt: string;
};

export type CanvasMember = {
  id: string;
  username: string;
};

export type CanvasDetail = {
  canvas: Canvas;
  members: CanvasMember[];
};
