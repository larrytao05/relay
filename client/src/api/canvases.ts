import type { Canvas, CanvasDetail, CanvasMember } from "../types.ts";

export type CanvasApiErrorKind = "http" | "network" | "invalid-response";

export class CanvasApiError extends Error {
  readonly status: number | null;
  readonly kind: CanvasApiErrorKind;

  constructor(
    message: string,
    status: number | null,
    kind: CanvasApiErrorKind,
  ) {
    super(message);
    this.name = "CanvasApiError";
    this.status = status;
    this.kind = kind;
  }
}

export function createCanvasApi(fetcher: typeof fetch = fetch) {
  async function requestJson(
    path: string,
    init: RequestInit = {},
  ): Promise<{ payload: unknown; status: number }> {
    let response: Response;
    try {
      response = await fetcher(path, { ...init, credentials: "include" });
    } catch (error) {
      if (init.signal?.aborted) throw error;
      throw new CanvasApiError("Couldn't connect to the server. Try again.", null, "network");
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error) {
      if (init.signal?.aborted) throw error;
      if (!response.ok) {
        throw new CanvasApiError(
          `The request failed (${response.status}).`,
          response.status,
          "http",
        );
      }
      throw new CanvasApiError(
        "The server returned an invalid response.",
        response.status,
        "invalid-response",
      );
    }

    if (!response.ok) {
      throw new CanvasApiError(
        getErrorMessage(payload, response.status),
        response.status,
        "http",
      );
    }

    return { payload, status: response.status };
  }

  function parseCanvasResponse(payload: unknown, status: number): Canvas {
    if (!isRecord(payload) || !("canvas" in payload)) {
      throw invalidResponse(status);
    }
    return parseCanvas(payload.canvas, status);
  }

  return {
    async list(signal?: AbortSignal): Promise<Canvas[]> {
      const { payload, status } = await requestJson("/api/canvases", { signal });
      if (!isRecord(payload) || !Array.isArray(payload.canvases)) {
        throw invalidResponse(status);
      }
      return payload.canvases.map((canvas) => parseCanvas(canvas, status));
    },

    async create(title: string): Promise<Canvas> {
      const { payload, status } = await requestJson("/api/canvases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      return parseCanvasResponse(payload, status);
    },

    async get(canvasId: string, signal?: AbortSignal): Promise<CanvasDetail> {
      const path = `/api/canvases/${encodeURIComponent(canvasId)}`;
      const { payload, status } = await requestJson(path, { signal });
      if (!isRecord(payload) || !("canvas" in payload) || !Array.isArray(payload.members)) {
        throw invalidResponse(status);
      }
      return {
        canvas: parseCanvas(payload.canvas, status),
        members: payload.members.map((member) => parseCanvasMember(member, status)),
      };
    },

    async invite(canvasId: string, username: string): Promise<CanvasMember> {
      const path = `/api/canvases/${encodeURIComponent(canvasId)}/members`;
      const { payload, status } = await requestJson(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username }),
      });
      if (!isRecord(payload) || !("user" in payload)) throw invalidResponse(status);
      return parseCanvasMember(payload.user, status);
    },
  };
}

export const canvasApi = createCanvasApi();

function parseCanvas(value: unknown, status: number): Canvas {
  if (
    !isRecord(value) ||
    !isUuid(value.id) ||
    typeof value.title !== "string" ||
    !isUuid(value.created_by) ||
    typeof value.revision !== "number" ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0 ||
    !isDateString(value.created_at) ||
    !isDateString(value.updated_at)
  ) {
    throw invalidResponse(status);
  }

  return {
    id: value.id,
    title: value.title,
    createdBy: value.created_by,
    revision: value.revision,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

function parseCanvasMember(value: unknown, status: number): CanvasMember {
  if (!isRecord(value) || !isUuid(value.id) || typeof value.username !== "string") {
    throw invalidResponse(status);
  }
  return { id: value.id, username: value.username };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isDateString(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function getErrorMessage(payload: unknown, status: number): string {
  if (!isRecord(payload) || !("detail" in payload)) {
    return `The request failed (${status}).`;
  }
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    const message = payload.detail.find(
      (item) => isRecord(item) && typeof item.msg === "string",
    );
    if (isRecord(message) && typeof message.msg === "string") {
      return message.msg.replace(/^Value error,\s*/, "");
    }
  }
  return `The request failed (${status}).`;
}

function invalidResponse(status: number): CanvasApiError {
  return new CanvasApiError(
    "The server returned an unexpected canvas response.",
    status,
    "invalid-response",
  );
}
