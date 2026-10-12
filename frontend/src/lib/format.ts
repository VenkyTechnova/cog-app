export const STAGE_ORDER = [
  "sourced",
  "contacted",
  "interested",
  "qualified",
  "process_explained",
  "docs_requested",
  "docs_received",
  "onboarding",
  "marketing_pipeline",
];
export const OUTCOMES = ["placed", "closed", "hold", "not_interested"];
export const STAGE_LABELS: Record<string, string> = {
  sourced: "Sourced",
  contacted: "Contacted",
  interested: "Interested",
  qualified: "Qualified",
  process_explained: "Process Explained",
  docs_requested: "Docs Requested",
  docs_received: "Docs Received",
  onboarding: "Onboarding",
  marketing_pipeline: "Opportunity Pipeline",
  placed: "Placed",
  closed: "Closed",
  hold: "Hold",
  not_interested: "Not Interested",
};

export const CATEGORY_STYLE: Record<string, { dot: string; badge: string; bar: string; label: string }> = {
  Automate: { dot: "bg-automate dark:bg-automate-dark", badge: "bg-automate/10 text-[#1c5cab] dark:text-[#86b6ef] ring-automate/30", bar: "var(--series-1)", label: "Automate" },
  Delegate: { dot: "bg-delegate dark:bg-delegate-dark", badge: "bg-delegate/10 text-[#b0461b] dark:text-[#f39a75] ring-delegate/30", bar: "var(--series-2)", label: "Delegate" },
  Simplify: { dot: "bg-simplify dark:bg-simplify-dark", badge: "bg-simplify/10 text-[#0d7a53] dark:text-[#5fd4a8] ring-simplify/30", bar: "var(--series-3)", label: "Simplify" },
  "Keep Human": { dot: "bg-human dark:bg-human-dark", badge: "bg-human/15 text-[#8a5d00] dark:text-[#f5c451] ring-human/30", bar: "var(--series-4)", label: "Keep Human" },
};

export const TEAM_LABELS: Record<string, string> = {
  payroll: "Payroll",
  immigration: "Immigration / Legal",
  onboarding: "Onboarding / HR",
  marketing: "Marketing",
  coordinator: "Coordinator",
};

export function fmtDate(s?: string | null, opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" }) {
  if (!s) return "—";
  return new Date(s).toLocaleDateString(undefined, opts);
}
export function fmtDateTime(s?: string | null) {
  if (!s) return "—";
  return new Date(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
export function relTime(s?: string | null) {
  if (!s) return "never";
  const diff = (Date.now() - new Date(s).getTime()) / 1000;
  const abs = Math.abs(diff);
  const fut = diff < 0;
  const u = abs < 60 ? [Math.round(abs), "s"] : abs < 3600 ? [Math.round(abs / 60), "m"] : abs < 86400 ? [Math.round(abs / 3600), "h"] : [Math.round(abs / 86400), "d"];
  return fut ? `in ${u[0]}${u[1]}` : `${u[0]}${u[1]} ago`;
}
export function durationLabel(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const neg = seconds < 0;
  const s = Math.abs(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const txt = h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : `${h}h ${m}m`;
  return neg ? `${txt} overdue` : `${txt} left`;
}
export function initials(name?: string | null) {
  return (name || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
export const humanize = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
