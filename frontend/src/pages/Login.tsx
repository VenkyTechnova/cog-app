import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../lib/api";
import { ROLE_LABELS, useAuth, type User } from "../lib/auth";
import { Avatar, Button, ErrorBox } from "../components/ui";
import { errMsg } from "../lib/api";

export default function Login() {
  const { login, user } = useAuth();
  const nav = useNavigate();
  const [users, setUsers] = useState<User[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (user) nav("/");
    get("/api/auth/config").then(setCfg).catch(() => {});
    get<User[]>("/api/auth/dev-users").then(setUsers).catch((e) => setErr(errMsg(e)));
  }, [user]);

  async function pick(email: string) {
    setBusy(email);
    setErr(null);
    try {
      await login(email);
      nav("/");
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center p-4 bg-gradient-to-br from-brand-800 to-brand-900">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center gap-3 mb-5">
          <img src="/favicon.svg" className="h-10 w-10" alt="" />
          <div>
            <h1 className="text-lg font-semibold">Cognitech Recruiter Workflow</h1>
            <p className="text-xs text-slate-500">Talent Acquisition · Cognitech Technologies</p>
          </div>
        </div>
        <ErrorBox error={err} />
        {cfg?.mode === "oidc" ? (
          <Button variant="primary" className="w-full" onClick={() => (location.href = `${cfg.issuer}/authorize?client_id=${cfg.client_id}&response_type=id_token&scope=openid%20email&redirect_uri=${encodeURIComponent(location.origin + "/login")}&nonce=${Date.now()}`)}>
            Sign in with SSO
          </Button>
        ) : (
          <>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-3">Development sign-in — choose a demo user. In production this is replaced by SSO (OIDC).</p>
            <div className="space-y-1.5">
              {users.map((u) => (
                <button
                  key={u.id}
                  onClick={() => pick(u.email)}
                  disabled={!!busy}
                  className="flex w-full items-center gap-3 rounded-lg border border-slate-200 dark:border-white/10 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-white/5 disabled:opacity-60"
                >
                  <Avatar name={u.name} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{u.name}</div>
                    <div className="text-xs text-slate-500 truncate">{u.email}</div>
                  </div>
                  <span className="text-xs text-slate-500">{ROLE_LABELS[u.role]}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
