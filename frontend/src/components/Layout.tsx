import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Bell,
  Briefcase,
  ClipboardList,
  Gauge,
  Home,
  KanbanSquare,
  LogOut,
  Menu,
  Moon,
  Settings as SettingsIcon,
  ShieldCheck,
  Sun,
  TicketCheck,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { get, post } from "../lib/api";
import { ROLE_LABELS, isStaff, useAuth } from "../lib/auth";
import { relTime } from "../lib/format";
import { useInterval } from "../lib/hooks";
import { Avatar, cx } from "./ui";

type NavItem = { to: string; label: string; icon: ReactNode; show: (role: string) => boolean };
const staff = (r: string) => ["recruiter", "ta_lead", "coordinator", "admin"].includes(r);
const manager = (r: string) => ["ta_lead", "admin"].includes(r);
const NAV: NavItem[] = [
  { to: "/", label: "Recruiter Home", icon: <Home className="h-4 w-4" />, show: staff },
  { to: "/candidates", label: "Candidates", icon: <Users className="h-4 w-4" />, show: staff },
  { to: "/pipeline", label: "Pipeline", icon: <KanbanSquare className="h-4 w-4" />, show: staff },
  { to: "/requirements", label: "Requirements", icon: <Briefcase className="h-4 w-4" />, show: staff },
  { to: "/delegation", label: "Delegation Center", icon: <TicketCheck className="h-4 w-4" />, show: () => true },
  { to: "/tasks", label: "Task Map", icon: <ClipboardList className="h-4 w-4" />, show: () => true },
  { to: "/workflows", label: "Workflow Builder", icon: <Workflow className="h-4 w-4" />, show: staff },
  { to: "/analytics", label: "Analytics", icon: <BarChart3 className="h-4 w-4" />, show: staff },
  { to: "/impact", label: "Automation Impact", icon: <Gauge className="h-4 w-4" />, show: () => true },
  { to: "/compliance", label: "Compliance & Audit", icon: <ShieldCheck className="h-4 w-4" />, show: (r) => manager(r) || r === "recruiter" },
  { to: "/settings", label: "Settings", icon: <SettingsIcon className="h-4 w-4" />, show: () => true },
];

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {}
  }, [dark]);
  return [dark, setDark] as const;
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [dark, setDark] = useTheme();
  const [open, setOpen] = useState(false);
  const [notif, setNotif] = useState<{ unread: number; items: any[] }>({ unread: 0, items: [] });
  const [showNotif, setShowNotif] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();

  const loadNotif = useCallback(() => {
    get("/api/notifications").then(setNotif).catch(() => {});
  }, []);
  useEffect(loadNotif, [loadNotif, loc.pathname]);
  useInterval(loadNotif, 30000);
  useEffect(() => setOpen(false), [loc.pathname]);

  const items = NAV.filter((n) => user && n.show(user.role));

  const sidebar = (
    <nav className="flex h-full flex-col">
      <Link to={isStaff(user) ? "/" : "/delegation"} className="flex items-center gap-2.5 px-4 py-4">
        <img src="/favicon.svg" className="h-8 w-8" alt="" />
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">Cognitech</div>
          <div className="text-[11px] text-brand-200">Recruiter Workflow</div>
        </div>
      </Link>
      <div className="flex-1 space-y-0.5 px-2 overflow-y-auto">
        {items.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            className={({ isActive }) =>
              cx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm", isActive ? "bg-white/15 text-white font-medium" : "text-brand-100 hover:bg-white/10 hover:text-white")
            }
          >
            {n.icon}
            {n.label}
          </NavLink>
        ))}
      </div>
      <div className="px-4 py-3 text-[11px] leading-snug text-brand-200 border-t border-white/10">
        <span className="italic">“Standardize, so the conversation can be human.”</span>
      </div>
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden lg:block w-60 shrink-0 bg-brand-800 dark:bg-[#0b2233]">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside className="absolute left-0 top-0 h-full w-64 bg-brand-800 dark:bg-[#0b2233]" onClick={(e) => e.stopPropagation()}>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-slate-200 dark:border-white/10 bg-white/90 dark:bg-[#141413]/90 backdrop-blur px-4">
          <button className="lg:hidden rounded p-1.5 hover:bg-slate-100 dark:hover:bg-white/10" onClick={() => setOpen(true)} aria-label="Menu">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex-1" />
          <button className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10" onClick={() => setDark(!dark)} aria-label="Toggle dark mode">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <div className="relative">
            <button className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10" onClick={() => setShowNotif(!showNotif)} aria-label="Notifications">
              <Bell className="h-4 w-4" />
              {notif.unread > 0 && <span className="absolute right-1 top-1 h-4 min-w-4 rounded-full bg-red-600 px-1 text-[10px] font-semibold leading-4 text-white tabular">{notif.unread}</span>}
            </button>
            {showNotif && (
              <div className="absolute right-0 mt-2 w-80 card shadow-lg z-50" onMouseLeave={() => setShowNotif(false)}>
                <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 dark:border-white/10">
                  <span className="text-sm font-semibold">Notifications</span>
                  <button className="text-xs text-brand-700 dark:text-brand-200 hover:underline" onClick={() => post("/api/notifications/read").then(loadNotif)}>
                    Mark all read
                  </button>
                </div>
                <div className="max-h-96 overflow-y-auto">
                  {notif.items.length === 0 && <div className="p-4 text-sm text-slate-500">You're all caught up.</div>}
                  {notif.items.map((n) => (
                    <button
                      key={n.id}
                      onClick={() => {
                        setShowNotif(false);
                        if (n.link) nav(n.link);
                      }}
                      className={cx("block w-full text-left px-3 py-2 border-b border-slate-100 dark:border-white/5 hover:bg-slate-50 dark:hover:bg-white/5", !n.read && "bg-brand-50/60 dark:bg-brand-500/10")}
                    >
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-100">{n.title}</div>
                      {n.body && <div className="text-xs text-slate-500 line-clamp-2">{n.body}</div>}
                      <div className="text-[11px] text-slate-400 mt-0.5">{relTime(n.created_at)}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 pl-2 border-l border-slate-200 dark:border-white/10">
            <Avatar name={user?.name} />
            <div className="hidden sm:block leading-tight">
              <div className="text-sm font-medium">{user?.name}</div>
              <div className="text-[11px] text-slate-500">{ROLE_LABELS[user?.role || ""]}</div>
            </div>
            <button
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10"
              onClick={() => {
                logout();
                nav("/login");
              }}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
