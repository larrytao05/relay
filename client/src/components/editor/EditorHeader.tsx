import { Link } from "react-router";
import type { AuthUser } from "../../AuthContext.tsx";
import Brand from "../Brand.tsx";
import Header from "../Header.tsx";
import UserAvatar from "../UserAvatar.tsx";

export type ConnectionStatus = "loading" | "ready" | "saving" | "reconnecting" | "recovering" | "failed";

const statusLabel: Record<ConnectionStatus, string> = {
  loading: "Connecting…",
  ready: "All changes saved",
  saving: "Saving…",
  reconnecting: "Reconnecting…",
  recovering: "Checking last change…",
  failed: "Connection unavailable",
};

export default function EditorHeader({
  title,
  status,
  user,
  onInvite,
  onBack,
  onLogout,
}: {
  title: string;
  status: ConnectionStatus;
  user: AuthUser;
  onInvite(): void;
  onBack(): boolean;
  onLogout(): void;
}) {
  const initials = user.username.slice(0, 2).toUpperCase();
  return (
    <Header className="editor-topbar">
      <div className="editor-top-left">
        <Link className="editor-brand editor-home-link" to="/canvases" aria-label="Back to canvases" onClick={(event) => { if (!onBack()) event.preventDefault(); }}>
          <Brand />
        </Link>
        <span className="editor-breadcrumb">My canvases /</span>
        <div className="editor-document">
          <span className="editor-document-title">{title || "Whiteboard"}</span>
          <span className={`editor-save-status is-${status}`} role="status">
            <i aria-hidden="true" />{statusLabel[status]}
          </span>
        </div>
      </div>
      <div className="editor-top-right">
        <button className="editor-button" type="button" onClick={onInvite}>Invite</button>
        <UserAvatar name={user.username} initials={initials} />
        <button className="editor-signout" type="button" onClick={onLogout} aria-label={`Sign out ${user.username}`}>
          Sign out
        </button>
      </div>
    </Header>
  );
}
