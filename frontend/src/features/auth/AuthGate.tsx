import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, SIGNED_OUT_EVENT } from "../../api/client";
import type { AuthStatus } from "../../api/types";

const AuthContext = createContext<{ status: AuthStatus; signOut: () => void } | null>(null);

/** Who is signed in, and how to sign out -- null where signing in isn't set up. */
function useAuth() {
  return useContext(AuthContext);
}

/**
 * On a server with signing in (backend core/auth.py) shows the sign-in page
 * until there is a session, and again when the server says it ended (any
 * 401). Where signing in isn't set up (a personal computer) the app opens
 * directly.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(() => {
    api.authStatus().then(
      (s) => {
        setStatus(s);
        setError(null);
      },
      (err: Error) => setError(`Cannot reach the server: ${err.message}`),
    );
  }, []);

  useEffect(() => {
    check();
    const onSignedOut = () => setStatus((s) => (s?.enabled ? { enabled: true, user: null, role: null } : s));
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
  }, [check]);

  if (error) {
    return (
      <div className="login">
        <div className="login__card">
          <div className="error">{error}</div>
          <button className="btn" onClick={check}>
            Try again
          </button>
        </div>
      </div>
    );
  }
  if (!status) return null;
  if (status.enabled && !status.user) return <LoginPage onSignedIn={setStatus} />;

  const signOut = () => {
    void api.logout().finally(() => setStatus({ enabled: true, user: null, role: null }));
  };
  return <AuthContext.Provider value={status.enabled ? { status, signOut } : null}>{children}</AuthContext.Provider>;
}

function LoginPage({ onSignedIn }: { onSignedIn: (s: AuthStatus) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.login(username, password));
    } catch (err) {
      setError((err as Error).message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit}>
        <h1 className="login__title">Ecosim — Results Explorer</h1>
        <p className="muted login__subtitle">Sign in to continue.</p>
        <label className="login__field">
          <span>User name</span>
          <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label className="login__field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="btn" type="submit" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

/** Whether this user may change what the app runs on for everyone (data
 * sources, reference-area packs): yes without signing in, else admins only. */
export function useCanManage(): boolean {
  const auth = useAuth();
  return !auth || auth.status.role === "admin";
}

/** "admin · Sign out" next to the theme switch, where signing in is on. */
export function SignOutButton() {
  const auth = useAuth();
  if (!auth) return null;
  return (
    <button
      className="btn btn--ghost"
      onClick={auth.signOut}
      title={`Signed in as ${auth.status.user} (${auth.status.role})`}
    >
      {auth.status.user} · Sign out
    </button>
  );
}
