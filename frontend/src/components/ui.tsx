import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import { CATEGORY_STYLE, STAGE_LABELS } from "../lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" | "success"; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode };
export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }: BtnProps) {
  const v = {
    primary: "bg-brand-800 text-white hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-400",
    secondary: "bg-white dark:bg-white/5 text-slate-700 dark:text-slate-200 border border-slate-300 dark:border-white/15 hover:bg-slate-50 dark:hover:bg-white/10",
    ghost: "text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/10",
    danger: "bg-red-600 text-white hover:bg-red-700",
    success: "bg-emerald-600 text-white hover:bg-emerald-700",
  }[variant];
  const s = size === "sm" ? "px-2.5 py-1 text-xs gap-1" : "px-3.5 py-2 text-sm gap-1.5";
  return (
    <button
      className={cx("inline-flex items-center justify-center rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap", v, s, className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className, bodyClass, subtitle }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-2">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>}
            {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </header>
      )}
      <div className={cx("px-4 pb-4", !title && !actions && "pt-4", bodyClass)}>{children}</div>
    </section>
  );
}

const BADGE_TONES: Record<string, string> = {
  gray: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-white/10 dark:text-slate-200 dark:ring-white/10",
  blue: "bg-blue-50 text-blue-800 ring-blue-200 dark:bg-blue-500/15 dark:text-blue-200 dark:ring-blue-400/20",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-200 dark:ring-emerald-400/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-400/20",
  red: "bg-red-50 text-red-800 ring-red-200 dark:bg-red-500/15 dark:text-red-200 dark:ring-red-400/20",
  violet: "bg-violet-50 text-violet-800 ring-violet-200 dark:bg-violet-500/15 dark:text-violet-200 dark:ring-violet-400/20",
  brand: "bg-brand-50 text-brand-800 ring-brand-200 dark:bg-brand-500/15 dark:text-brand-100 dark:ring-brand-400/20",
};
export function Badge({ tone = "gray", children, className, title }: { tone?: keyof typeof BADGE_TONES | string; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap", BADGE_TONES[tone] || BADGE_TONES.gray, className)}>
      {children}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  const s = CATEGORY_STYLE[category];
  if (!s) return <Badge>{category}</Badge>;
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset whitespace-nowrap", s.badge)}>
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

const STAGE_TONE: Record<string, string> = {
  sourced: "gray",
  contacted: "blue",
  interested: "blue",
  qualified: "brand",
  process_explained: "brand",
  docs_requested: "violet",
  docs_received: "violet",
  onboarding: "green",
  marketing_pipeline: "green",
  placed: "green",
  closed: "gray",
  hold: "amber",
  not_interested: "gray",
};
export function StageBadge({ stage }: { stage: string }) {
  return <Badge tone={STAGE_TONE[stage]}>{STAGE_LABELS[stage] || stage}</Badge>;
}

export function ScoreBadge({ score }: { score?: number | null }) {
  if (score == null) return <span className="text-xs text-slate-400">—</span>;
  const tone = score >= 75 ? "green" : score >= 55 ? "amber" : "gray";
  return (
    <Badge tone={tone} className="tabular">
      {Math.round(score)}%
    </Badge>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-5 w-5 animate-spin text-slate-400", className)} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-200">
      <XCircle className="h-4 w-4 mt-0.5 shrink-0" /> <span>{error}</span>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-8 px-4 text-slate-500 dark:text-slate-400">
      {icon && <div className="mb-2 text-slate-300 dark:text-slate-600">{icon}</div>}
      <div className="text-sm font-medium text-slate-600 dark:text-slate-300">{title}</div>
      {children && <div className="text-xs mt-1 max-w-sm">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" | "neutral"; icon?: ReactNode }) {
  return (
    <div className="card px-4 py-3">
      <div className="flex items-center justify-between text-xs font-medium text-slate-500 dark:text-slate-400">
        <span>{label}</span>
        {icon && <span className="text-slate-400">{icon}</span>}
      </div>
      <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{value}</div>
      {sub && <div className={cx("text-xs mt-0.5", tone === "good" ? "text-[#006300] dark:text-[#0ca30c]" : tone === "bad" ? "text-red-700 dark:text-red-300" : "text-slate-500 dark:text-slate-400")}>{sub}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start sm:items-center justify-center bg-slate-900/40 p-4 overflow-y-auto" onMouseDown={onClose}>
      <div className={cx("card w-full my-8", wide ? "max-w-3xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal>
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 px-5 py-3">
          <h3 className="font-semibold text-slate-900 dark:text-white">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-4 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-200 dark:border-white/10 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: ReactNode; count?: number }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-slate-200 dark:border-white/10 overflow-x-auto scrollbar-thin">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={cx(
            "px-3 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap",
            value === t.key ? "border-brand-700 text-brand-800 dark:border-brand-300 dark:text-brand-100" : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-200",
          )}
        >
          {t.label}
          {t.count != null && <span className="ml-1.5 rounded-full bg-slate-100 dark:bg-white/10 px-1.5 text-[11px] tabular">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-slate-500 mt-1">{hint}</span>}
    </label>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Avatar({ name, size = 8 }: { name?: string | null; size?: number }) {
  const init = (name || "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <span className={cx("inline-flex items-center justify-center rounded-full bg-brand-100 text-brand-800 dark:bg-brand-500/20 dark:text-brand-100 font-semibold shrink-0", size === 8 ? "h-8 w-8 text-xs" : size === 10 ? "h-10 w-10 text-sm" : "h-6 w-6 text-[10px]")}>
      {init}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------
type Toast = { id: number; kind: "success" | "error" | "info" | "warning"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  const icon = { success: <CheckCircle2 className="h-4 w-4 text-emerald-500" />, error: <XCircle className="h-4 w-4 text-red-500" />, info: <Info className="h-4 w-4 text-blue-500" />, warning: <AlertTriangle className="h-4 w-4 text-amber-500" /> };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 max-w-sm">
        {items.map((t) => (
          <div key={t.id} className="card flex items-start gap-2 px-3 py-2 text-sm shadow-lg">
            {icon[t.kind]}
            <span className="text-slate-700 dark:text-slate-200">{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cx("inline-flex items-center gap-2 text-sm", disabled ? "opacity-50" : "cursor-pointer")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx("relative h-5 w-9 rounded-full transition-colors", checked ? "bg-brand-700 dark:bg-brand-400" : "bg-slate-300 dark:bg-white/20")}
      >
        <span className={cx("absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-4" : "translate-x-0.5")} />
      </button>
      {label}
    </label>
  );
}

export function ProgressBar({ value, max = 100, color = "var(--series-1)" }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className="h-1.5 w-full rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}
