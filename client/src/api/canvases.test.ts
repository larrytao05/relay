import assert from "node:assert/strict";
import test from "node:test";
import { CanvasApiError, createCanvasApi } from "./canvases.ts";

const canvasResponse = {
  id: "74e6be89-4544-40db-b786-46f8050e41ab",
  title: "Design review",
  created_by: "f7183789-e22c-4df8-94dc-b6e2e654519f",
  revision: 2,
  created_at: "2026-10-23T12:00:00Z",
  updated_at: "2026-10-23T12:30:00Z",
};

test("list sends cookies and parses the canvas list", async () => {
  let request: { input: RequestInfo | URL; init?: RequestInit } | undefined;
  const api = createCanvasApi(async (input, init) => {
    request = { input, init };
    return jsonResponse({ canvases: [canvasResponse] });
  });

  const canvases = await api.list();

  assert.equal(String(request?.input), "/api/canvases");
  assert.equal(request?.init?.credentials, "include");
  assert.deepEqual(canvases, [{
    id: canvasResponse.id,
    title: canvasResponse.title,
    createdBy: canvasResponse.created_by,
    revision: 2,
    createdAt: canvasResponse.created_at,
    updatedAt: canvasResponse.updated_at,
  }]);
});

test("create posts a title and returns the created canvas", async () => {
  let request: { input: RequestInfo | URL; init?: RequestInit } | undefined;
  const api = createCanvasApi(async (input, init) => {
    request = { input, init };
    return jsonResponse({ canvas: canvasResponse }, 201);
  });

  const canvas = await api.create("Design review");

  assert.equal(String(request?.input), "/api/canvases");
  assert.equal(request?.init?.method, "POST");
  assert.equal(request?.init?.credentials, "include");
  assert.deepEqual(JSON.parse(String(request?.init?.body)), { title: "Design review" });
  assert.equal(canvas.title, "Design review");
});

test("get encodes the canvas ID and parses its members", async () => {
  let requestedUrl = "";
  const api = createCanvasApi(async (input) => {
    requestedUrl = String(input);
    return jsonResponse({
      canvas: canvasResponse,
      members: [{ id: canvasResponse.created_by, username: "owner" }],
    });
  });

  const detail = await api.get("canvas/id");

  assert.equal(requestedUrl, "/api/canvases/canvas%2Fid");
  assert.equal(detail.canvas.id, canvasResponse.id);
  assert.deepEqual(detail.members, [{ id: canvasResponse.created_by, username: "owner" }]);
});

test("invite posts a username to the canvas member endpoint", async () => {
  let request: { input: RequestInfo | URL; init?: RequestInit } | undefined;
  const api = createCanvasApi(async (input, init) => {
    request = { input, init };
    return jsonResponse({ user: { id: canvasResponse.created_by, username: "new-member" } });
  });

  const member = await api.invite(canvasResponse.id, "new-member");

  assert.equal(String(request?.input), `/api/canvases/${canvasResponse.id}/members`);
  assert.equal(request?.init?.method, "POST");
  assert.equal(request?.init?.credentials, "include");
  assert.deepEqual(JSON.parse(String(request?.init?.body)), { username: "new-member" });
  assert.deepEqual(member, { id: canvasResponse.created_by, username: "new-member" });
});

test("HTTP errors preserve status and validation feedback", async () => {
  const api = createCanvasApi(async () => jsonResponse({
    detail: [{ msg: "Value error, Canvas title is required." }],
  }, 422));

  await assert.rejects(api.create(""), (error: unknown) => {
    assert.ok(error instanceof CanvasApiError);
    assert.equal(error.status, 422);
    assert.equal(error.kind, "http");
    assert.equal(error.message, "Canvas title is required.");
    return true;
  });
});

test("unauthorized responses preserve the status for auth recovery", async () => {
  const api = createCanvasApi(async () => jsonResponse({ detail: "Authentication required." }, 401));

  await assert.rejects(api.list(), (error: unknown) => {
    assert.ok(error instanceof CanvasApiError);
    assert.equal(error.status, 401);
    assert.equal(error.message, "Authentication required.");
    return true;
  });
});

test("network failures are reported separately from HTTP failures", async () => {
  const api = createCanvasApi(async () => {
    throw new TypeError("offline");
  });

  await assert.rejects(api.list(), (error: unknown) => {
    assert.ok(error instanceof CanvasApiError);
    assert.equal(error.kind, "network");
    assert.equal(error.status, null);
    return true;
  });
});

test("malformed success payloads fail at the API boundary", async () => {
  const api = createCanvasApi(async () => jsonResponse({ canvases: [{ id: "bad" }] }));

  await assert.rejects(api.list(), (error: unknown) => {
    assert.ok(error instanceof CanvasApiError);
    assert.equal(error.kind, "invalid-response");
    assert.equal(error.status, 200);
    return true;
  });
});

test("aborted requests stay distinguishable from network failures", async () => {
  const controller = new AbortController();
  const abortError = new DOMException("Aborted", "AbortError");
  const api = createCanvasApi(async () => {
    controller.abort();
    throw abortError;
  });

  await assert.rejects(api.list(controller.signal), abortError);
});

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
