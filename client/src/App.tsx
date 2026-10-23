import "./App.css";
import { Navigate, Outlet, Route, Routes } from "react-router";
import { useAuth } from "./AuthContext.tsx";
import DashboardPage from "./DashboardPage.tsx";
import EditorPage from "./EditorPage.tsx";
import SignInPage from "./SignInPage.tsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route element={<SessionBoundary />}>
        <Route path="/login" element={<PublicAuthPage mode="sign-in" />} />
        <Route path="/signup" element={<PublicAuthPage mode="sign-up" />} />
        <Route element={<RequireAuth />}>
          <Route path="/canvases" element={<DashboardPage />} />
          <Route path="/canvases/:canvasId" element={<EditorPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

function PublicAuthPage({ mode }: { mode: "sign-in" | "sign-up" }) {
  const { state } = useAuth();
  if (state.kind === "authenticated") return <Navigate to="/canvases" replace />;
  return <SignInPage mode={mode} />;
}

function SessionBoundary() {
  const { state, retrySessionCheck } = useAuth();

  if (state.kind === "checking") {
    return <main className="auth-check" role="status">Checking your session…</main>;
  }
  if (state.kind === "unavailable") {
    return (
      <main className="auth-check">
        <p role="alert">We couldn’t verify your session. Check your connection and try again.</p>
        <button className="button" type="button" onClick={retrySessionCheck}>
          Try again
        </button>
      </main>
    );
  }

  return <Outlet />;
}

function RequireAuth() {
  const { state } = useAuth();
  return state.kind === "authenticated" ? <Outlet /> : <Navigate to="/login" replace />;
}
