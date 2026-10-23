import { useEffect, useState, type FormEvent } from "react";
import { canvasApi } from "../../api/canvases.ts";
import type { CanvasMember } from "../../types.ts";

type MembersState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; members: CanvasMember[] };

export default function InviteDialog({
  canvasId,
  onClose,
}: {
  canvasId: string;
  onClose(): void;
}) {
  const [username, setUsername] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "success" | "error">("idle");
  const [message, setMessage] = useState("");
  const [membersState, setMembersState] = useState<MembersState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void canvasApi.get(canvasId, controller.signal).then(
      (detail) => {
        if (!controller.signal.aborted) setMembersState({ kind: "ready", members: detail.members });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setMembersState({
            kind: "error",
            message: error instanceof Error ? error.message : "Couldn't load canvas members.",
          });
        }
      },
    );
    return () => controller.abort();
  }, [canvasId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "submitting") return;
    const normalizedUsername = username.trim();
    if (!normalizedUsername) {
      setStatus("error");
      setMessage("Enter a username.");
      return;
    }
    setStatus("submitting");
    setMessage("");
    try {
      const member = await canvasApi.invite(canvasId, normalizedUsername);
      setStatus("success");
      setMessage(`Invitation sent to ${member.username}.`);
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Couldn't send the invitation.");
    }
  }

  return (
    <div className="editor-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="editor-dialog" role="dialog" aria-modal="true" aria-labelledby="invite-title" onKeyDown={(event) => { if (event.key === "Escape" && status !== "submitting") onClose(); }}>
        <button className="editor-dialog-close" type="button" aria-label="Close invitation dialog" onClick={onClose}>×</button>
        <h2 id="invite-title">Invite someone</h2>
        <p>Share this canvas with someone who has a Relay account.</p>
        <div className="invite-members" aria-live="polite">
          <h3>People with access</h3>
          {membersState.kind === "loading" && <p className="invite-members-note">Loading people…</p>}
          {membersState.kind === "error" && <p className="invite-members-error" role="alert">{membersState.message}</p>}
          {membersState.kind === "ready" && (membersState.members.length > 0
            ? <ul>{membersState.members.map((member) => <li key={member.id}>{member.username}</li>)}</ul>
            : <p className="invite-members-note">No one has access yet.</p>)}
        </div>
        <form onSubmit={submit}>
          <label htmlFor="invite-username">Username</label>
          <input id="invite-username" name="username" autoFocus autoComplete="username" required value={username} disabled={status === "submitting" || status === "success"} onChange={(event) => { setUsername(event.currentTarget.value); if (status === "error") { setStatus("idle"); setMessage(""); } }} />
          {message && <p className={`invite-message is-${status}`} role={status === "error" ? "alert" : "status"}>{message}</p>}
          <div className="editor-dialog-actions">
            <button className="editor-button" type="button" onClick={onClose} disabled={status === "submitting"}>Close</button>
            <button className="editor-button primary" type="submit" disabled={status === "submitting" || status === "success"}>{status === "submitting" ? "Inviting…" : status === "success" ? "Invited" : "Invite"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
