// Thin fetch wrapper. The token is kept in localStorage (per-viewer convenience only).
const BASE = (import.meta as any).env?.VITE_API_URL || "";

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem("token");
  } catch {
    return null;
  }
}
export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem("token", t);
    else localStorage.removeItem("token");
  } catch {}
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; auth?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token && opts.auth !== false) headers["Authorization"] = `Bearer ${token}`;
  let body: any;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(BASE + path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && opts.auth !== false) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) location.href = "/login";
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, (data as any)?.detail ?? data);
  return data as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: any) => api<T>(p, { method: "POST", body: body ?? {} });
export const patch = <T = any>(p: string, body: any) => api<T>(p, { method: "PATCH", body });
export const put = <T = any>(p: string, body: any) => api<T>(p, { method: "PUT", body });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });

export function errMsg(e: any): string {
  if (e instanceof ApiError) {
    const d = e.detail;
    if (typeof d === "string") return d;
    if (d?.message) return d.message + (d.missing ? `: ${d.missing.join(", ")}` : "");
    if (Array.isArray(d)) return d.map((x: any) => x.msg).join("; ");
    return JSON.stringify(d);
  }
  return String(e?.message || e);
}
