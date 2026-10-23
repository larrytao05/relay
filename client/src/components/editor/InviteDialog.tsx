import { useState, type FormEvent } from "react";
import { canvasApi } from "../../api/canvases.ts";

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
      setMessage(`${member.username} can now access this canvas.`);
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
