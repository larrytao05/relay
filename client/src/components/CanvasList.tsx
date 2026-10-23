import type { CanvasListEntry } from "../types.ts";
import CanvasListItem from "./CanvasListItem.tsx";

export default function CanvasList({
  canvases,
  resolvingInviteId,
  invitationError,
  onResolveInvitation,
  onInvite,
}: {
  canvases: CanvasListEntry[];
  resolvingInviteId: string | null;
  invitationError: string;
  onResolveInvitation(canvasId: string, action: "accept" | "decline"): Promise<boolean>;
  onInvite(canvasId: string): void;
}) {
  return (
    <section className="canvas-list" aria-label="Your canvases">
      <h2>Canvas</h2>
      {invitationError && <p className="canvas-invitation-error" role="alert">{invitationError}</p>}
      {canvases.map((entry) => (
        <CanvasListItem
          key={entry.canvas.id}
          entry={entry}
          disabled={resolvingInviteId !== null}
          resolving={resolvingInviteId === entry.canvas.id}
          onResolveInvitation={onResolveInvitation}
          onInvite={onInvite}
        />
      ))}
    </section>
  );
}
