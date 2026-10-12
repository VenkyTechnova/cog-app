import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { CalendarClock, Lock, Plus, Search, ShieldCheck, Sparkles, Workflow as WorkflowIcon, Zap } from "lucide-react";
import { errMsg, patch } from "../lib/api";
import { isManager, useAuth } from "../lib/auth";
import { relTime } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, Tabs, Toggle, cx, useToast } from "../components/ui";

// ---------------------------------------------------------------------------
// Cron helpers (shared with the Workflow editor)
// ---------------------------------------------------------------------------
const DOW_NAMES: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const DOW_LABEL = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"];
const DOW_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CRON_FIELDS: [string, number, number, Record<string, number>?][] = [
  ["minute", 0, 59],
  ["hour", 0, 23],
  ["day of month", 1, 31],
  ["month", 1, 12],
  ["day of week", 0, 7, DOW_NAMES],
];

/** Returns an error message, or null when the 5-field cron expression is valid. */
export function cronError(expr: string): string | null {
  const parts = (expr || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length !== 5) return `Expected 5 fields (minute hour day month weekday), got ${parts.length}`;
  for (let i = 0; i < 5; i++) {
    const [name, lo, hi, names] = CRON_FIELDS[i];
    const num = (s: string) => {
      const v = names && s in names ? names[s] : /^\d+$/.test(s) ? parseInt(s, 10) : NaN;
      return v;
    };
    for (const item of parts[i].toLowerCase().split(",")) {
      const [range, step, extra] = item.split("/");
      if (extra !== undefined || (step !== undefined && !/^[1-9]\d*$/.test(step))) return `Invalid step in ${name}: “${item}”`;
      if (range === "*" || range === "") continue;
      const [a, b, more] = range.split("-");
      if (more !== undefined) return `Invalid range in ${name}: “${item}”`;
      const va = num(a);
      const vb = b === undefined ? va : num(b);
      if (Number.isNaN(va) || Number.isNaN(vb)) return `Invalid value in ${name}: “${item}”`;
      if (va < lo || vb > hi || va > vb) return `${name[0].toUpperCase() + name.slice(1)} must be between ${lo} and ${hi}: “${item}”`;
    }
  }
  return null;
}

function dowText(dow: string): string | null {
  const d = dow.toLowerCase();
  if (d === "*") return "Daily";
  if (d === "mon-fri" || d === "1-5") return "Weekdays";
  if (["sat,sun", "sun,sat", "0,6", "6,0", "6-7", "sat-sun"].includes(d)) return "Weekends";
  const idx = (s: string) => (s in DOW_NAMES ? DOW_NAMES[s] : /^\d$/.test(s) ? parseInt(s, 10) : -1);
  if (!d.includes(",") && !d.includes("-") && idx(d) >= 0) return DOW_LABEL[idx(d)];
  const list = d.split(",").map(idx);
  if (list.every((x) => x >= 0 && x <= 7)) return list.map((x) => DOW_SHORT[x]).join(", ");
  if (/^[a-z0-9]+-[a-z0-9]+$/.test(d)) {
    const [a, b] = d.split("-").map(idx);
    if (a >= 0 && b >= 0) return `${DOW_SHORT[a]}–${DOW_SHORT[b]}`;
  }
  return null;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Human-friendly rendering of a cron expression, e.g. "30 7 * * mon-fri" → "Weekdays 7:30". Falls back to the raw expression. */
export function describeCron(expr?: string | null): string {
  if (!expr) return "No schedule";
  if (cronError(expr)) return expr;
  const [min, hour, dom, mon, dow] = expr.trim().split(/\s+/);
  const days = dowText(dow);
  if (!days) return expr;
  const dayPart = days === "Daily" ? "" : ` · ${days}`;
  const extra = (dom !== "*" ? ` · day ${dom}` : "") + (mon !== "*" ? ` · month ${mon}` : "");
  const hourRange = (h: string) => {
    const m = /^(\d+)-(\d+)$/.exec(h);
    if (m) return `, ${m[1]}:00–${m[2]}:59`;
    return h === "*" ? "" : null;
  };
  // Every N minutes
  const stepMin = /^\*\/(\d+)$/.exec(min);
  if (stepMin) {
    const hr = hourRange(hour);
    if (hr !== null) return `Every ${stepMin[1]} min${hr}${dayPart}${extra}`;
    return expr;
  }
  if (/^\d+$/.test(min)) {
    const m = parseInt(min, 10);
    if (hour === "*") return `Hourly${m ? ` at :${pad(m)}` : ""}${dayPart}${extra}`;
    const stepHour = /^\*\/(\d+)$/.exec(hour);
    if (stepHour) return `Every ${stepHour[1]} h at :${pad(m)}${dayPart}${extra}`;
    if (/^\d+$/.test(hour)) return `${days} ${parseInt(hour, 10)}:${pad(m)}${extra}`;
    if (/^\d+(,\d+)+$/.test(hour)) return `${days} at ${hour.split(",").map((h) => `${parseInt(h, 10)}:${pad(m)}`).join(", ")}${extra}`;
  }
  return expr;
}

/** Short label for an event key, derived from the catalog description. */
export function eventLabel(events: Record<string, string> | undefined, key: string): string {
  return events?.[key] || key;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
type Wf = {
  id: number;
  key: string;
  name: string;
  description: string;
  task_id: string | null;
  trigger_event: string;
  schedule: string | null;
  conditions: any[];
  actions: { type: string; params?: Record<string, any> }[];
  enabled: boolean;
  system: boolean;
  minutes_saved_per_run: number;
  run_count: number;
  last_run_at: string | null;
};

function ActionChips({ actions, catalog }: { actions: { type: string }[]; catalog: any }) {
  return (
    <div className="flex flex-wrap gap-1">
      {actions.map((a, i) => {
        const meta = catalog?.actions?.[a.type];
        return (
          <span
            key={i}
            title={meta?.label || a.type}
            className="inline-flex max-w-[16rem] items-center gap-1 truncate rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-200"
          >
            <span className="text-slate-400 tabular">{i + 1}.</span>
            <span className="truncate">{meta?.label || a.type}</span>
          </span>
        );
      })}
    </div>
  );
}

function TriggerCell({ w, catalog }: { w: { trigger_event: string; schedule?: string | null }; catalog: any }) {
  if (w.trigger_event === "schedule")
    return (
      <div className="text-xs">
        <div className="flex items-center gap-1 font-medium text-slate-700 dark:text-slate-200">
          <CalendarClock className="h-3.5 w-3.5 text-slate-400" />
          {describeCron(w.schedule)}
        </div>
        <code className="text-[11px] text-slate-500">{w.schedule}</code>
      </div>
    );
  return (
    <div className="text-xs">
      <div className="flex items-start gap-1 text-slate-700 dark:text-slate-200">
        <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span>{eventLabel(catalog?.events, w.trigger_event)}</span>
      </div>
      <code className="text-[11px] text-slate-500">{w.trigger_event}</code>
    </div>
  );
}

function WorkflowTable({
  rows,
  catalog,
  canEdit,
  busy,
  onToggle,
}: {
  rows: Wf[];
  catalog: any;
  canEdit: boolean;
  busy: Set<number>;
  onToggle: (w: Wf, v: boolean) => void;
}) {
  const nav = useNavigate();
  return (
    <div className="relative -mx-4 overflow-x-auto scrollbar-thin">
      <table className="w-full min-w-[980px]">
        <thead className="border-y border-slate-200 dark:border-white/10">
          <tr>
            <th className="th pl-4">Workflow</th>
            <th className="th">Trigger</th>
            <th className="th">Actions</th>
            <th className="th">Task</th>
            <th className="th text-right">Runs</th>
            <th className="th">Last run</th>
            <th className="th pr-4">Enabled</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((w) => (
            <tr
              key={w.id}
              className={cx("cursor-pointer border-b border-slate-100 hover:bg-slate-50/70 dark:border-white/5 dark:hover:bg-white/[0.03]", !w.enabled && "opacity-70")}
              onClick={() => nav(`/workflows/${w.id}`)}
            >
              <td className="td max-w-[20rem] pl-4">
                <Link to={`/workflows/${w.id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-slate-800 hover:underline dark:text-slate-100">
                  {w.name}
                </Link>
                {w.system && (
                  <Badge className="ml-1.5 align-middle" title="System workflow: can be disabled but not deleted">
                    System
                  </Badge>
                )}
                {w.description && <p className="mt-0.5 text-xs text-slate-500 line-clamp-2 dark:text-slate-400">{w.description}</p>}
                {w.conditions?.length > 0 && (
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    {w.conditions.length} condition{w.conditions.length === 1 ? "" : "s"}
                  </p>
                )}
              </td>
              <td className="td max-w-[14rem]">
                <TriggerCell w={w} catalog={catalog} />
              </td>
              <td className="td max-w-[18rem]">
                <ActionChips actions={w.actions || []} catalog={catalog} />
              </td>
              <td className="td">{w.task_id ? <span className="font-mono text-xs text-slate-600 dark:text-slate-300">{w.task_id}</span> : <span className="text-xs text-slate-400">—</span>}</td>
              <td className="td text-right tabular">{w.run_count.toLocaleString()}</td>
              <td className="td whitespace-nowrap text-xs text-slate-600 dark:text-slate-300" title={w.last_run_at ? new Date(w.last_run_at).toLocaleString() : undefined}>
                {w.last_run_at ? relTime(w.last_run_at) : <span className="text-slate-400">Never</span>}
              </td>
              <td className="td pr-4" onClick={(e) => e.stopPropagation()}>
                <Toggle
                  checked={w.enabled}
                  disabled={!canEdit || busy.has(w.id)}
                  onChange={(v) => onToggle(w, v)}
                  label={<span className="sr-only">{w.enabled ? `Disable ${w.name}` : `Enable ${w.name}`}</span>}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Workflows() {
  const { user } = useAuth();
  const canEdit = isManager(user);
  const toast = useToast();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "workflows";
  const { data: list, error, loading, setData } = useApi<Wf[]>("/api/workflows");
  const { data: catalog, error: catErr, loading: catLoading } = useApi<any>("/api/workflows/catalog");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<Set<number>>(new Set());

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (list || []).filter(
      (w) =>
        !ql ||
        [w.name, w.description, w.key, w.task_id, w.trigger_event, eventLabel(catalog?.events, w.trigger_event), ...(w.actions || []).map((a) => catalog?.actions?.[a.type]?.label || a.type)]
          .filter(Boolean)
          .some((s) => String(s).toLowerCase().includes(ql)),
    );
  }, [list, q, catalog]);

  if ((loading && !list) || (catLoading && !catalog)) return <Loading />;
  if (error || catErr) return <ErrorBox error={error || catErr} />;
  if (!list || !catalog) return null;

  const eventRows = filtered.filter((w) => w.trigger_event !== "schedule");
  const schedRows = filtered.filter((w) => w.trigger_event === "schedule");
  const installed = new Set(list.map((w) => w.key));
  const templates: any[] = catalog.workflow_templates || [];
  const guardrails: any[] = catalog.guardrails || [];

  async function toggle(w: Wf, enabled: boolean) {
    setBusy((b) => new Set(b).add(w.id));
    setData((xs) => (xs || []).map((x) => (x.id === w.id ? { ...x, enabled } : x)));
    try {
      await patch(`/api/workflows/${w.id}`, { enabled });
      toast("success", `${w.name} ${enabled ? "enabled" : "disabled"}`);
    } catch (e) {
      setData((xs) => (xs || []).map((x) => (x.id === w.id ? { ...x, enabled: !enabled } : x)));
      toast("error", errMsg(e));
    } finally {
      setBusy((b) => {
        const n = new Set(b);
        n.delete(w.id);
        return n;
      });
    }
  }

  const enabledCount = list.filter((w) => w.enabled).length;
  const setTab = (k: string) => setParams(k === "workflows" ? {} : { tab: k }, { replace: true });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Workflow Builder"
        subtitle="Trigger → conditions → actions. Every Automate task in the Task Map runs on one of these."
        actions={
          canEdit && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => nav("/workflows/new")}>
              New workflow
            </Button>
          )
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="card px-4 py-3">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Enabled</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">
            {enabledCount}
            <span className="text-sm font-normal text-slate-500"> / {list.length}</span>
          </div>
        </div>
        <div className="card px-4 py-3">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Event-driven</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">{list.filter((w) => w.trigger_event !== "schedule").length}</div>
        </div>
        <div className="card px-4 py-3">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Scheduled</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">{list.filter((w) => w.trigger_event === "schedule").length}</div>
        </div>
        <div className="card px-4 py-3">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Total runs</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">{list.reduce((a, w) => a + (w.run_count || 0), 0).toLocaleString()}</div>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "workflows", label: "Workflows", count: list.length },
          { key: "templates", label: "Templates", count: templates.length },
          { key: "guardrails", label: "Guardrails", count: guardrails.length },
        ]}
      />

      {tab === "workflows" && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
              <input className="input pl-8" placeholder="Search workflows, triggers, actions…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search workflows" />
            </div>
            {!canEdit && <span className="text-xs text-slate-500">Read-only. TA leads and admins can enable, disable and edit workflows.</span>}
          </div>
          {filtered.length === 0 ? (
            <div className="card">
              <Empty icon={<WorkflowIcon className="h-8 w-8" />} title="No workflows match your search" />
            </div>
          ) : (
            <>
              {eventRows.length > 0 && (
                <Card title={`Event-driven (${eventRows.length})`} subtitle="Run the moment something happens: a record is created, a reply arrives, a stage changes.">
                  <WorkflowTable rows={eventRows} catalog={catalog} canEdit={canEdit} busy={busy} onToggle={toggle} />
                </Card>
              )}
              {schedRows.length > 0 && (
                <Card title={`Scheduled (${schedRows.length})`} subtitle="Run on a cron schedule in server local time, e.g. call lists before the workday starts.">
                  <WorkflowTable rows={schedRows} catalog={catalog} canEdit={canEdit} busy={busy} onToggle={toggle} />
                </Card>
              )}
            </>
          )}
        </div>
      )}

      {tab === "templates" && (
        <div className="space-y-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Pre-built flows from the playbook. Start from one and adjust the trigger, conditions or actions.
          </p>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {templates.map((t) => (
              <section key={t.key} className="card flex flex-col p-4">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t.name}</h3>
                  {installed.has(t.key) && (
                    <Badge tone="green" title="A workflow with this key already exists">
                      In use
                    </Badge>
                  )}
                </div>
                {t.description && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t.description}</p>}
                <div className="mt-3 space-y-2">
                  <TriggerCell w={t} catalog={catalog} />
                  <ActionChips actions={t.actions || []} catalog={catalog} />
                </div>
                <div className="mt-auto flex items-center justify-between gap-2 pt-4">
                  <span className="text-[11px] text-slate-500">
                    {t.task_id && <span className="font-mono">{t.task_id} · </span>}
                    <span className="tabular">{t.minutes_saved_per_run ?? 0}</span> min saved / run
                  </span>
                  {canEdit ? (
                    <Button size="sm" icon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => nav(`/workflows/new?template=${encodeURIComponent(t.key)}`)}>
                      Use template
                    </Button>
                  ) : null}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}

      {tab === "guardrails" && (
        <div className="space-y-4">
          <div className="card flex items-start gap-3 px-4 py-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" />
            <div className="text-sm text-slate-600 dark:text-slate-300">
              <p className="font-medium text-slate-800 dark:text-slate-100">Guardrails are enforced in code</p>
              <p className="mt-0.5 text-xs">
                They are not workflows. They run on every relevant request whatever workflows are enabled, and nobody can switch them off from the UI, including admins.
              </p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {guardrails.map((g) => (
              <section key={g.key} className="card p-4">
                <div className="flex items-start gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-white/10 dark:text-slate-300">
                    <Lock className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{g.name}</h3>
                      <Badge>
                        <Lock className="h-3 w-3" /> Always on
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{g.description}</p>
                    {g.task_id && (
                      <p className="mt-2 text-[11px] text-slate-500">
                        Implements task <span className="font-mono">{g.task_id}</span>
                      </p>
                    )}
                  </div>
                </div>
              </section>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            Related: a workflow can only auto-send templates approved for auto-send. Personalized outreach is always drafted for a recruiter to review and send.
          </p>
        </div>
      )}
    </div>
  );
}
