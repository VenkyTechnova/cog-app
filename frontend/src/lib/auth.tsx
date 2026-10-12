import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { get, getToken, post, setToken } from "./api";

export type User = { id: number; name: string; email: string; role: string; digest_enabled: boolean; digest_prefs: Record<string, any> };

type Ctx = { user: User | null; loading: boolean; login: (email: string) => Promise<void>; logout: () => void; refresh: () => Promise<void> };
const AuthCtx = createContext<Ctx>({ user: null, loading: true, login: async () => {}, logout: () => {}, refresh: async () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await get<User>("/api/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function login(email: string) {
    const r = await post<{ token: string; user: User }>("/api/auth/login", { email });
    setToken(r.token);
    setUser(r.user);
  }
  function logout() {
    setToken(null);
    setUser(null);
  }
  return <AuthCtx.Provider value={{ user, loading, login, logout, refresh }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

export const ROLE_LABELS: Record<string, string> = {
  recruiter: "Recruiter",
  ta_lead: "TA Lead",
  coordinator: "Coordinator",
  payroll: "Payroll",
  immigration: "Immigration",
  onboarding: "Onboarding",
  marketing: "Marketing",
  admin: "Admin",
};

export const isManager = (u: User | null) => !!u && (u.role === "ta_lead" || u.role === "admin");
export const isStaff = (u: User | null) => !!u && ["recruiter", "ta_lead", "coordinator", "admin"].includes(u.role);
