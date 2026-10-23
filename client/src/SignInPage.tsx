import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { useAuth, type AuthUser } from "./AuthContext.tsx";
import Brand from "./components/Brand.tsx";
import Header from "./components/Header.tsx";
import "./SignInPage.css";

type SignInPageProps = {
  mode?: "sign-in" | "sign-up";
};

type FormState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string };

export default function SignInPage({ mode = "sign-in" }: SignInPageProps) {
  const isSignUp = mode === "sign-up";

  return (
    <div className="sign-in-page">
      <SiteHeader />
      <SignInLayout>
        <SignInIntro />
        <SignInPanel isSignUp={isSignUp} />
      </SignInLayout>
    </div>
  );
}

function SiteHeader() {
  return (
    <Header className="sign-in-header">
      <RelayBrand />
    </Header>
  );
}

function RelayBrand() {
  return (
    <Link className="relay-brand-link" to="/login" aria-label="Relay sign in">
      <Brand />
    </Link>
  );
}

function SignInLayout({ children }: { children: ReactNode }) {
  return <main className="sign-in-layout">{children}</main>;
}

function SignInIntro() {
  return (
    <section className="sign-in-intro" aria-label="About Relay">
      <IntroCopy />
      <CanvasPreview />
      <IntroFootnote />
    </section>
  );
}

function IntroCopy() {
  return (
    <div className="intro-copy">
      <h1>Make space for good ideas.</h1>
      <p>A shared canvas for sketching through decisions together.</p>
    </div>
  );
}

function CanvasPreview() {
  return (
    <figure className="canvas-preview" aria-hidden="true">
      <CanvasIllustration />
      <figcaption className="canvas-caption">Checkout flow · 3 people</figcaption>
    </figure>
  );
}

function CanvasIllustration() {
  return (
    <svg viewBox="0 0 390 265" fill="none" aria-hidden="true">
      <path d="M106 107h57m73 0h50M199 130v45m-61 0h123" stroke="#91a0ae" strokeWidth="2" />
      <path d="M162 103l7 4-7 4m70-8 7 4-7 4m-40 59 7 4-7 4m-54-4 7 4-7 4m123-8 7 4-7 4" stroke="#91a0ae" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="49" y="82" width="58" height="48" rx="7" fill="#edf1ff" stroke="#cbd6fb" strokeWidth="1.5" />
      <path d="M63 98h29M63 107h20" stroke="#7f91c9" strokeWidth="2" strokeLinecap="round" />
      <rect x="163" y="82" width="74" height="48" rx="7" fill="#f6e8bd" stroke="#e8d596" strokeWidth="1.5" />
      <path d="M178 98h44M178 107h31" stroke="#ac9453" strokeWidth="2" strokeLinecap="round" />
      <ellipse cx="307" cy="106" rx="28" ry="24" fill="#d9eee4" stroke="#b6ddca" strokeWidth="1.5" />
      <path d="M294 106h26" stroke="#6b9c82" strokeWidth="2" strokeLinecap="round" />
      <rect x="116" y="153" width="54" height="43" rx="7" fill="#f2dfe0" stroke="#e7cacc" strokeWidth="1.5" />
      <path d="M129 169h28M129 178h18" stroke="#ae7c82" strokeWidth="2" strokeLinecap="round" />
      <rect x="228" y="153" width="62" height="43" rx="7" fill="#fff" stroke="#dce2e8" strokeWidth="1.5" />
      <path d="M242 169h34M242 178h23" stroke="#94a0ad" strokeWidth="2" strokeLinecap="round" />
      <circle cx="315" cy="211" r="13" fill="#559681" stroke="#fff" strokeWidth="3" />
      <path d="m310 211 3 3 6-7" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IntroFootnote() {
  return <p className="intro-footnote">A calmer way to work through a design review.</p>;
}

function SignInPanel({ isSignUp }: { isSignUp: boolean }) {
  return (
    <section className="sign-in-panel" aria-labelledby="auth-title">
      <div className="sign-in-form-wrap">
        <SignInHeading isSignUp={isSignUp} />
        <SignInForm isSignUp={isSignUp} />
        <SignupPrompt isSignUp={isSignUp} />
        <SessionNote />
      </div>
    </section>
  );
}

function SignInHeading({ isSignUp }: { isSignUp: boolean }) {
  return (
    <div className="sign-in-heading">
      <h2 id="auth-title">{isSignUp ? "Create your account" : "Welcome back"}</h2>
      <p>{isSignUp ? "Set up your account to start collaborating." : "Sign in to pick up where your team left off."}</p>
    </div>
  );
}

function SignInForm({ isSignUp }: { isSignUp: boolean }) {
  const [state, setState] = useState<FormState>({ kind: "idle" });
  const { setAuthenticated } = useAuth();
  const navigate = useNavigate();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.kind === "submitting") return;

    const formData = new FormData(event.currentTarget);
    const username = formData.get("username");
    const password = formData.get("password");
    if (typeof username !== "string" || typeof password !== "string") {
      setState({ kind: "error", message: "Enter your username and password." });
      return;
    }

    setState({ kind: "submitting" });
    try {
      const response = await fetch(`/api/auth/${isSignUp ? "signup" : "login"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      const result: unknown = await response.json().catch(() => null);

      if (!response.ok) {
        setState({ kind: "error", message: getResponseError(result) });
        return;
      }
      if (!isUserResponse(result)) {
        setState({ kind: "error", message: "The server returned an unexpected response." });
        return;
      }

      setAuthenticated(result.user);
      navigate("/canvases", { replace: true });
    } catch {
      setState({ kind: "error", message: "Couldn't connect. Check your connection and try again." });
    }
  }

  return (
    <form className="sign-in-form" onSubmit={submit} aria-busy={state.kind === "submitting"}>
      <CredentialField
        id="username"
        label="Username"
        placeholder="Your username"
        autoComplete="username"
        maxLength={64}
        describedBy="username-hint"
        hint="3–32 letters, numbers, underscores, or hyphens. Case and surrounding spaces are ignored."
        required
      />
      <CredentialField
        id="password"
        label="Password"
        type="password"
        placeholder="Enter your password"
        autoComplete={isSignUp ? "new-password" : "current-password"}
        minLength={8}
        maxLength={128}
        required
      />
      <SubmitButton
        label={isSignUp ? "Create account" : "Sign in"}
        pendingLabel={isSignUp ? "Creating account…" : "Signing in…"}
        submitting={state.kind === "submitting"}
      />
      <FormFeedback state={state} isSignUp={isSignUp} />
    </form>
  );
}

function CredentialField({
  id,
  label,
  type = "text",
  placeholder,
  autoComplete,
  minLength,
  maxLength,
  describedBy,
  hint,
  required = false,
}: {
  id: string;
  label: string;
  type?: "text" | "password";
  placeholder: string;
  autoComplete: string;
  minLength?: number;
  maxLength?: number;
  describedBy?: string;
  hint?: string;
  required?: boolean;
}) {
  return (
    <div className="credential-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={id}
        type={type}
        placeholder={placeholder}
        autoComplete={autoComplete}
        minLength={minLength}
        maxLength={maxLength}
        aria-describedby={describedBy}
        required={required}
      />
      {hint && <p className="field-hint" id={describedBy}>{hint}</p>}
    </div>
  );
}

function SubmitButton({
  label,
  pendingLabel,
  submitting,
}: {
  label: string;
  pendingLabel: string;
  submitting: boolean;
}) {
  return (
    <button className="sign-in-submit" type="submit" disabled={submitting}>
      {submitting ? pendingLabel : label}
    </button>
  );
}

function FormFeedback({ state, isSignUp }: { state: FormState; isSignUp: boolean }) {
  const message = state.kind === "error"
    ? state.message
    : state.kind === "submitting" && isSignUp
      ? "Creating your account…"
      : state.kind === "submitting"
        ? "Signing you in…"
        : "";
  return (
    <p className="form-feedback" role={state.kind === "error" ? "alert" : "status"} aria-live="polite">
      {message}
    </p>
  );
}

function isUserResponse(value: unknown): value is { user: AuthUser } {
  if (typeof value !== "object" || value === null || !("user" in value)) return false;
  const user = value.user;
  return typeof user === "object" && user !== null &&
    "id" in user && typeof user.id === "string" &&
    "username" in user && typeof user.username === "string";
}

function getResponseError(value: unknown) {
  if (typeof value !== "object" || value === null || !("detail" in value)) {
    return "Check your username and password and try again.";
  }

  if (typeof value.detail === "string") return value.detail;

  if (Array.isArray(value.detail)) {
    const message = value.detail.find(
      (item): item is { msg: string } =>
        typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string",
    )?.msg;
    if (message) return message.replace(/^Value error,\s*/, "");
  }

  return "Check your username and password and try again.";
}

function SignupPrompt({ isSignUp }: { isSignUp: boolean }) {
  return (
    <p className="signup-prompt">
      {isSignUp ? "Already have an account? " : "New to Relay? "}
      <Link to={isSignUp ? "/login" : "/signup"}>
        {isSignUp ? "Sign in" : "Create an account"}
      </Link>
    </p>
  );
}

function SessionNote() {
  return (
    <p className="session-note">
      <svg viewBox="0 0 16 18" fill="none" aria-hidden="true">
        <path d="M3 7V5a5 5 0 0 1 10 0v2m-11 0h12v9H2V7Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <circle cx="8" cy="11" r="1" fill="currentColor" />
      </svg>
      <span>Your canvas is ready when you are.</span>
    </p>
  );
}
