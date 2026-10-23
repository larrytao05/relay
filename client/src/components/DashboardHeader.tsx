import { useState } from "react";
import { useAuth } from "../AuthContext.tsx";
import Brand from "./Brand.tsx";
import Header from "./Header.tsx";
import UserAvatar from "./UserAvatar.tsx";

export default function DashboardHeader() {
  const { state, logout } = useAuth();
  const [request, setRequest] = useState<"idle" | "submitting" | "error">("idle");

  if (state.kind !== "authenticated") return null;

  async function signOut() {
    if (request === "submitting") return;
    setRequest("submitting");
    try {
      await logout();
    } catch {
      setRequest("error");
    }
  }

  const initials = state.user.username.slice(0, 2).toUpperCase();

  return (
    <Header className="dashboard-header">
      <Brand />
      <div className="dashboard-account">
        {request === "error" && <span className="logout-error" role="alert">Couldn't sign out. Try again.</span>}
        <UserAvatar name={state.user.username} initials={initials} />
        <button className="button" type="button" onClick={signOut} disabled={request === "submitting"}>
          {request === "submitting" ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </Header>
  );
}
