import type { CanvasListEntry } from "../types.ts";
import { Link } from "react-router";
import CanvasThumbnail from "./CanvasThumbnail.tsx";

export default function CanvasListItem({
  entry,
  disabled,
  resolving,
  onResolveInvitation,
  onInvite,
}: {
  entry: CanvasListEntry;
  disabled: boolean;
  resolving: boolean;
  onResolveInvitation(canvasId: string, action: "accept" | "decline"): Promise<boolean>;
  onInvite(canvasId: string): void;
}) {
  const { canvas } = entry;
  const thumbnail = (
    <span className="canvas-thumbnail">
      <CanvasThumbnail />
    </span>
  );

  if (entry.status === "member") {
    return (
      <div className="canvas-row canvas-row-managed">
        <Link className="canvas-row-link" to={`/canvases/${canvas.id}`}>
          {thumbnail}
          <span className="canvas-name">{canvas.title}</span>
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
        <button
          className="canvas-invite-button"
          type="button"
          aria-label={`Invite someone to ${canvas.title}`}
          title="Invite someone"
          onClick={() => onInvite(canvas.id)}
        >
          +
        </button>
      </div>
    );
  }

  return (
    <div className="canvas-row is-pending">
      {thumbnail}
      <span className="canvas-row-content">
        <span className="canvas-name">{canvas.title}</span>
        <span className="canvas-invitation-byline">Invited by {entry.invitedBy}</span>
      </span>
      <span className="canvas-invitation-actions" aria-busy={resolving}>
        <button
          className="button primary"
          type="button"
          disabled={disabled}
          onClick={() => void onResolveInvitation(canvas.id, "accept")}
        >
          {resolving ? "Saving…" : "Accept"}
        </button>
        <button
          className="button"
          type="button"
          disabled={disabled}
          onClick={() => void onResolveInvitation(canvas.id, "decline")}
        >
          {resolving ? "Saving…" : "Decline"}
        </button>
      </span>
    </div>
  );
}
