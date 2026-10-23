import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export type AuthUser = {
  id: string;
  username: string;
};

export type AuthState =
  | { kind: "checking" }
  | { kind: "anonymous" }
  | { kind: "authenticated"; user: AuthUser }
  | { kind: "unavailable" };

type AuthContextValue = {
  state: AuthState;
  setAuthenticated(user: AuthUser): void;
  logout(): Promise<void>;
  retrySessionCheck(): void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ kind: "checking" });
  const [sessionCheck, setSessionCheck] = useState(0);
  const sessionRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    sessionRequest.current = controller;

    async function loadSession() {
      try {
        const response = await fetch("/api/auth/me", {
          credentials: "include",
          signal: controller.signal,
        });

        if (response.status === 401) {
          setState({ kind: "anonymous" });
          return;
        }
        if (!response.ok) throw new Error("Session check failed.");

        const result = (await response.json()) as { user: AuthUser };
        setState({ kind: "authenticated", user: result.user });
      } catch {
        if (!controller.signal.aborted) setState({ kind: "unavailable" });
      }
    }

    void loadSession();
    return () => {
      controller.abort();
      if (sessionRequest.current === controller) sessionRequest.current = null;
    };
  }, [sessionCheck]);

  function setAuthenticated(user: AuthUser) {
    sessionRequest.current?.abort();
    setState({ kind: "authenticated", user });
  }

  async function logout() {
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) throw new Error("Sign out failed.");
    setState({ kind: "anonymous" });
  }

  const retrySessionCheck = useCallback(() => {
    setState({ kind: "checking" });
    setSessionCheck((attempt) => attempt + 1);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        state,
        setAuthenticated,
        logout,
        retrySessionCheck,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider.");
  return context;
}
