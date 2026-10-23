import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { canvasApi, CanvasApiError } from "./api/canvases.ts";
import { useAuth } from "./AuthContext.tsx";
import CanvasList from "./components/CanvasList.tsx";
import DashboardHeader from "./components/DashboardHeader.tsx";
import DashboardHeading from "./components/DashboardHeading.tsx";
import InviteDialog from "./components/editor/InviteDialog.tsx";
import type { CanvasListEntry } from "./types.ts";
import "./DashboardPage.css";

type CanvasListState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; canvases: CanvasListEntry[] };

type CreateState =
  | { kind: "closed" }
  | { kind: "editing" }
  | { kind: "submitting" }
  | { kind: "error"; message: string };

export default function DashboardPage() {
  const [listState, setListState] = useState<CanvasListState>({ kind: "loading" });
  const [createState, setCreateState] = useState<CreateState>({ kind: "closed" });
  const [title, setTitle] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [resolvingInviteId, setResolvingInviteId] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState("");
  const [inviteCanvasId, setInviteCanvasId] = useState<string | null>(null);
  const { retrySessionCheck } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const controller = new AbortController();
    setListState({ kind: "loading" });

    void canvasApi.list(controller.signal).then(
      (canvases) => {
        if (!controller.signal.aborted) setListState({ kind: "ready", canvases });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof CanvasApiError && error.status === 401) {
          retrySessionCheck();
          return;
        }
        setListState({ kind: "error", message: getErrorMessage(error) });
      },
    );

    return () => controller.abort();
  }, [loadAttempt, retrySessionCheck]);

  async function createCanvas(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createState.kind === "submitting") return;

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setCreateState({ kind: "error", message: "Enter a canvas name." });
      return;
    }

    setCreateState({ kind: "submitting" });
    try {
      const canvas = await canvasApi.create(trimmedTitle);
      const entry: CanvasListEntry = { canvas, status: "member", invitedBy: null };
      setListState((state) => state.kind === "ready"
        ? { kind: "ready", canvases: [entry, ...state.canvases] }
        : { kind: "ready", canvases: [entry] });
      setTitle("");
      setCreateState({ kind: "closed" });
      navigate(`/canvases/${canvas.id}`);
    } catch (error) {
      if (error instanceof CanvasApiError && error.status === 401) {
        retrySessionCheck();
        return;
      }
      setCreateState({ kind: "error", message: getErrorMessage(error) });
    }
  }

  async function resolveInvite(canvasId: string, action: "accept" | "decline") {
    try {
      if (action === "accept") await canvasApi.acceptInvite(canvasId);
      else await canvasApi.declineInvite(canvasId);
      setListState((state) => {
        if (state.kind !== "ready") return state;
        const canvases: CanvasListEntry[] = action === "decline"
          ? state.canvases.filter((entry) => entry.canvas.id !== canvasId)
          : state.canvases.map((entry) => {
            if (entry.canvas.id !== canvasId) return entry;
            return { canvas: entry.canvas, status: "member", invitedBy: null } satisfies CanvasListEntry;
          });
        return {
          kind: "ready",
          canvases: canvases.sort(
            (left, right) => Number(right.status === "pending") - Number(left.status === "pending"),
          ),
        };
      });
      return true;
    } catch (error) {
      if (error instanceof CanvasApiError && error.status === 401) {
        retrySessionCheck();
        return false;
      }
      setInviteError(getErrorMessage(error));
      return false;
    }
  }

  function openCreateForm() {
    if (createState.kind === "submitting") return;
    setCreateState({ kind: "editing" });
  }

  function closeCreateForm() {
    setTitle("");
    setCreateState({ kind: "closed" });
  }

  return (
    <div className="dashboard-page">
      <DashboardHeader />
      <main className="dashboard-content">
        <DashboardHeading
          onNewCanvas={openCreateForm}
          disabled={listState.kind !== "ready" || createState.kind === "submitting"}
        />
        {createState.kind !== "closed" && (
          <form className="canvas-create-form" onSubmit={createCanvas} aria-busy={createState.kind === "submitting"}>
            <label htmlFor="canvas-title">Canvas name</label>
            <div className="canvas-create-fields">
              <input
                id="canvas-title"
                name="title"
                value={title}
                maxLength={120}
                placeholder="e.g. Product ideas"
                autoFocus
                required
                disabled={createState.kind === "submitting"}
                onChange={(event) => {
                  setTitle(event.currentTarget.value);
                  if (createState.kind === "error") setCreateState({ kind: "editing" });
                }}
              />
              <button className="button primary" type="submit" disabled={createState.kind === "submitting"}>
                {createState.kind === "submitting" ? "Creating…" : "Create canvas"}
              </button>
              <button className="button" type="button" onClick={closeCreateForm} disabled={createState.kind === "submitting"}>
                Cancel
              </button>
            </div>
            {createState.kind === "error" && <p className="canvas-create-error" role="alert">{createState.message}</p>}
          </form>
        )}
        {listState.kind === "loading" && (
          <p className="dashboard-message" role="status">Loading your canvases…</p>
        )}
        {listState.kind === "error" && (
          <div className="dashboard-message dashboard-error" role="alert">
            <p>{listState.message}</p>
            <button className="button" type="button" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>
              Try again
            </button>
          </div>
        )}
        {listState.kind === "ready" && listState.canvases.length === 0 && (
          <section className="dashboard-empty" aria-labelledby="empty-canvases-title">
            <h2 id="empty-canvases-title">No canvases yet</h2>
            <p>Create a canvas to start sharing ideas.</p>
            <button className="button primary" type="button" onClick={openCreateForm} disabled={createState.kind === "submitting"}>
              Create your first canvas
            </button>
          </section>
        )}
        {listState.kind === "ready" && listState.canvases.length > 0 && (
          <CanvasList
            canvases={listState.canvases}
            resolvingInviteId={resolvingInviteId}
            invitationError={inviteError}
            onResolveInvitation={async (canvasId, action) => {
              setResolvingInviteId(canvasId);
              setInviteError("");
              const resolved = await resolveInvite(canvasId, action);
              setResolvingInviteId(null);
              return resolved;
            }}
            onInvite={setInviteCanvasId}
          />
        )}
      </main>
      {inviteCanvasId && <InviteDialog canvasId={inviteCanvasId} onClose={() => setInviteCanvasId(null)} />}
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  if (error instanceof CanvasApiError) return error.message;
  return "Something went wrong. Try again.";
}
