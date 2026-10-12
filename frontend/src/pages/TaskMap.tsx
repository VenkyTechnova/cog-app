import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Clock,
  Columns3,
  Lock,
  MousePointerClick,
  PauseCircle,
  Pencil,
  Plus,
  Search,
  Settings2,
  Table2,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import { errMsg, patch, post } from "../lib/api";
import { isManager, useAuth } from "../lib/auth";
import { CATEGORY_STYLE, TEAM_LABELS } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Badge, Button, CategoryBadge, Empty, ErrorBox, Field, Loading, Modal, PageHeader, ProgressBar, cx, useToast } from "../components/ui";

type Impl =
  | { type: "workflow"; label: string; workflow_id: number; enabled: boolean }
  | { type: "guardrail"; label: string; description: string }
  | { type: "builtin"; label: string }
  | null;

type Task = {
  id: string;
  playbook_section: string;
  stage: string;
  task_name: string;
  frequency: string;
  current_owner: string;
  category: string;
  rationale: string | null;
  trigger: string | null;
  automation_action: string | null;
  delegate_to: string | null;
  sla_hours: number | null;
  est_minutes_saved_per_week: number;
  baseline_minutes_per_week: number;
  status: string;
  workflow_key: string | null;
  implementation: Impl;
};

type TasksResponse = {
  items: Task[];
  categories: string[];
  category_rules: Record<string, string>;
  statuses: string[];
  teams: Record<string, string>;
  stages: string[];
  summary: any;
};

const STATUS_META: Record<string, { tone: string; icon: ReactNode; label: string }> = {
  live: { tone: "green", icon: <CheckCircle2 className="h-3 w-3" />, label: "Live" },
  configured: { tone: "blue", icon: <Settings2 className="h-3 w-3" />, label: "Configured" },
  planned: { tone: "gray", icon: <CircleDashed className="h-3 w-3" />, label: "Planned" },
  paused: { tone: "amber", icon: <PauseCircle className="h-3 w-3" />, label: "Paused" },
};

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] || { tone: "gray", icon: null, label: status };
  return (
    <Badge tone={m.tone}>
      {m.icon}
      {m.label}
    </Badge>
  );
}

function ImplementationCell({ impl }: { impl: Impl }) {
  if (!impl) return <span className="text-xs text-slate-400">—</span>;
  if (impl.type === "workflow")
    return (
      <Link
        to={`/workflows/${impl.workflow_id}`}
        onClick={(e) => e.stopPropagation()}
        className="group inline-flex max-w-[15rem] items-start gap-1.5 text-xs text-brand-700 hover:underline dark:text-brand-200"
        title={impl.label}
      >
        <WorkflowIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0">
          <span className="line-clamp-2">{impl.label}</span>
          <span className={cx("mt-0.5 block text-[11px] no-underline", impl.enabled ? "text-slate-500 dark:text-slate-400" : "text-amber-700 dark:text-amber-300")}>
            Workflow · {impl.enabled ? "enabled" : "disabled"}
          </span>
        </span>
      </Link>
    );
  if (impl.type === "guardrail")
    return (
      <span className="inline-flex max-w-[15rem] items-start gap-1.5 text-xs text-slate-700 dark:text-slate-200" title={impl.description}>
        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
        <span className="min-w-0">
          <span className="line-clamp-2">{impl.label}</span>
          <span className="mt-0.5 block text-[11px] text-slate-500 dark:text-slate-400">Guardrail · always on</span>
        </span>
      </span>
    );
  return (
    <span className="inline-flex max-w-[15rem] items-start gap-1.5 text-xs text-slate-700 dark:text-slate-200">
      <MousePointerClick className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
      <span className="min-w-0">
        <span className="line-clamp-2">{impl.label}</span>
        <span className="mt-0.5 block text-[11px] text-slate-500 dark:text-slate-400">Built-in feature</span>
      </span>
    </span>
  );
}

function MinutesCell({ t }: { t: Task }) {
  const color = CATEGORY_STYLE[t.category]?.bar || "var(--series-1)";
  return (
    <div className="w-28">
      <div className="text-sm tabular">
        <span className="text-slate-400">{t.baseline_minutes_per_week}</span>
        <span className="mx-1 text-slate-400">→</span>
        <span className="font-semibold text-slate-900 dark:text-white">{t.est_minutes_saved_per_week}</span>
        <span className="ml-1 text-[11px] text-slate-500">saved</span>
      </div>
      <div className="mt-1" title={`${t.est_minutes_saved_per_week} of ${t.baseline_minutes_per_week} baseline minutes/week saved`}>
        <ProgressBar value={t.est_minutes_saved_per_week} max={t.baseline_minutes_per_week || 1} color={color} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------
type Draft = {
  id: string;
  stage: string;
  task_name: string;
  playbook_section: string;
  category: string;
  rationale: string;
  trigger: string;
  automation_action: string;
  delegate_to: string;
  sla_hours: string;
  est_minutes_saved_per_week: string;
  baseline_minutes_per_week: string;
  status: string;
  frequency: string;
  current_owner: string;
};

const FREQUENCIES = ["Per candidate", "Daily", "Weekly", "Monthly", "Per requirement", "As needed"];

function toDraft(t: Task | null, stages: string[]): Draft {
  return {
    id: t?.id ?? "",
    stage: t?.stage ?? stages[0] ?? "",
    task_name: t?.task_name ?? "",
    playbook_section: t?.playbook_section ?? "",
    category: t?.category ?? "Automate",
    rationale: t?.rationale ?? "",
    trigger: t?.trigger ?? "",
    automation_action: t?.automation_action ?? "",
    delegate_to: t?.delegate_to ?? "",
    sla_hours: t?.sla_hours != null ? String(t.sla_hours) : "",
    est_minutes_saved_per_week: String(t?.est_minutes_saved_per_week ?? 0),
    baseline_minutes_per_week: String(t?.baseline_minutes_per_week ?? 0),
    status: t?.status ?? "planned",
    frequency: t?.frequency ?? "Weekly",
    current_owner: t?.current_owner ?? "Recruiter",
  };
}

function TaskEditor({ task, meta, onClose, onSaved }: { task: Task | null; meta: TasksResponse; onClose: () => void; onSaved: () => void }) {
  const isNew = !task;
  const [d, setD] = useState<Draft>(() => toDraft(task, meta.stages));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const set = (k: keyof Draft, v: string) => setD((x) => ({ ...x, [k]: v }));

  const saved = parseInt(d.est_minutes_saved_per_week || "0", 10);
  const baseline = parseInt(d.baseline_minutes_per_week || "0", 10);
  const freqOptions = FREQUENCIES.includes(d.frequency) || !d.frequency ? FREQUENCIES : [d.frequency, ...FREQUENCIES];

  async function save() {
    setError(null);
    if (isNew && (!d.id.trim() || !d.task_name.trim() || !d.stage.trim())) return setError("ID, task name and stage are required.");
    if (d.category === "Delegate" && !d.delegate_to) return setError("Delegate tasks need a team to delegate to.");
    const num = (s: string) => (s.trim() === "" ? null : parseInt(s, 10));
    if ([d.sla_hours, d.est_minutes_saved_per_week, d.baseline_minutes_per_week].some((s) => s.trim() !== "" && !/^\d+$/.test(s.trim())))
      return setError("Minutes and SLA hours must be whole numbers.");
    const body: Record<string, any> = {
      stage: d.stage.trim(),
      task_name: d.task_name.trim(),
      playbook_section: d.playbook_section.trim(),
      category: d.category,
      rationale: d.rationale,
      trigger: d.trigger,
      automation_action: d.automation_action,
      delegate_to: d.category === "Delegate" ? d.delegate_to : null,
      sla_hours: num(d.sla_hours),
      est_minutes_saved_per_week: num(d.est_minutes_saved_per_week) ?? 0,
      baseline_minutes_per_week: num(d.baseline_minutes_per_week) ?? 0,
      status: d.status,
      frequency: d.frequency,
      current_owner: d.current_owner,
    };
    setSaving(true);
    try {
      if (isNew) await post("/api/tasks", { id: d.id.trim(), ...body });
      else await patch(`/api/tasks/${task!.id}`, body);
      toast("success", isNew ? `Task ${d.id.trim()} added` : `Task ${task!.id} updated`);
      onSaved();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={isNew ? "Add task" : `Edit ${task!.id} · ${task!.task_name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={saving} onClick={save}>
            {isNew ? "Add task" : "Save changes"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <ErrorBox error={error} />
        <div className="grid gap-3 sm:grid-cols-4">
          {isNew && (
            <Field label="ID" hint="Unique, e.g. A20">
              <input className="input" value={d.id} onChange={(e) => set("id", e.target.value)} maxLength={10} />
            </Field>
          )}
          <div className={isNew ? "sm:col-span-3" : "sm:col-span-4"}>
            <Field label="Task">
              <input className="input" value={d.task_name} onChange={(e) => set("task_name", e.target.value)} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="Stage">
              <input className="input" list="taskmap-stages" value={d.stage} onChange={(e) => set("stage", e.target.value)} />
              <datalist id="taskmap-stages">
                {meta.stages.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </Field>
          </div>
          <Field label="Playbook section">
            <input className="input" value={d.playbook_section} onChange={(e) => set("playbook_section", e.target.value)} placeholder="§2.1" />
          </Field>
          <Field label="Status">
            <select className="input" value={d.status} onChange={(e) => set("status", e.target.value)}>
              {meta.statuses.map((s) => (
                <option key={s} value={s}>
                  {STATUS_META[s]?.label || s}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div>
          <span className="label">Category</span>
          <div className="grid gap-2 sm:grid-cols-4" role="radiogroup">
            {meta.categories.map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={d.category === c}
                onClick={() => set("category", c)}
                className={cx(
                  "rounded-lg border px-3 py-2 text-left transition-colors",
                  d.category === c ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500 dark:border-brand-300 dark:bg-brand-500/10 dark:ring-brand-300" : "border-slate-200 hover:bg-slate-50 dark:border-white/10 dark:hover:bg-white/5",
                )}
              >
                <CategoryBadge category={c} />
                <span className="mt-1 block text-[11px] leading-snug text-slate-500 dark:text-slate-400 line-clamp-3">{meta.category_rules[c]}</span>
              </button>
            ))}
          </div>
        </div>

        <Field label={`Why ${d.category}?`} hint="The rationale shown in the Task Map's “Why” panel.">
          <textarea className="input min-h-[64px]" value={d.rationale} onChange={(e) => set("rationale", e.target.value)} />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Trigger">
            <input className="input" value={d.trigger} onChange={(e) => set("trigger", e.target.value)} placeholder="e.g. Candidate created" />
          </Field>
          <Field label="Automation / action">
            <input className="input" value={d.automation_action} onChange={(e) => set("automation_action", e.target.value)} />
          </Field>
        </div>

        {d.category === "Delegate" && (
          <div className="grid gap-3 sm:grid-cols-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 dark:border-white/10 dark:bg-white/5">
            <Field label="Delegate to (required)">
              <select className="input" value={d.delegate_to} onChange={(e) => set("delegate_to", e.target.value)}>
                <option value="">Select a team…</option>
                {Object.entries(meta.teams).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="SLA (hours)">
              <input className="input tabular" inputMode="numeric" value={d.sla_hours} onChange={(e) => set("sla_hours", e.target.value)} placeholder="24" />
            </Field>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Baseline min/wk" hint="Manual time today">
            <input className="input tabular" inputMode="numeric" value={d.baseline_minutes_per_week} onChange={(e) => set("baseline_minutes_per_week", e.target.value)} />
          </Field>
          <Field
            label="Saved min/wk"
            hint={saved > baseline ? <span className="text-amber-700 dark:text-amber-300">Exceeds the baseline</span> : "Per recruiter"}
          >
            <input className="input tabular" inputMode="numeric" value={d.est_minutes_saved_per_week} onChange={(e) => set("est_minutes_saved_per_week", e.target.value)} />
          </Field>
          <Field label="Frequency">
            <select className="input" value={d.frequency} onChange={(e) => set("frequency", e.target.value)}>
              {freqOptions.map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
          </Field>
          <Field label="Current owner">
            <input className="input" value={d.current_owner} onChange={(e) => set("current_owner", e.target.value)} />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function TaskMap() {
  const { user } = useAuth();
  const canEdit = isManager(user);
  const { data, error, loading, reload } = useApi<TasksResponse>("/api/tasks");
  const [q, setQ] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const [stage, setStage] = useState("");
  const [view, setView] = useState<"table" | "kanban">("table");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [rulesOpen, setRulesOpen] = useState(true);
  const [editing, setEditing] = useState<Task | "new" | null>(null);

  const filtered = useMemo(() => {
    if (!data) return [];
    const ql = q.trim().toLowerCase();
    return data.items.filter(
      (t) =>
        (!cats.length || cats.includes(t.category)) &&
        (!stage || t.stage === stage) &&
        (!ql ||
          [t.id, t.task_name, t.rationale, t.trigger, t.automation_action, t.implementation?.label]
            .filter(Boolean)
            .some((s) => String(s).toLowerCase().includes(ql))),
    );
  }, [data, q, cats, stage]);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;

  const s = data.summary;
  const pr = s.per_recruiter_week;
  const toggleCat = (c: string) => setCats((x) => (x.includes(c) ? x.filter((y) => y !== c) : [...x, c]));
  const toggleRow = (id: string) =>
    setExpanded((x) => {
      const n = new Set(x);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const hasFilters = !!(q || cats.length || stage);
  const teamLabel = (k: string | null) => (k ? data.teams[k] || TEAM_LABELS[k] || k : "");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Task Map"
        subtitle="Every recurring playbook task, the category it belongs to, and how the platform handles it."
        actions={
          canEdit && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>
              Add task
            </Button>
          )
        }
      />

      {/* Summary tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="card col-span-2 px-4 py-3 sm:col-span-3 lg:col-span-1">
          <div className="flex items-center justify-between text-xs font-medium text-slate-500 dark:text-slate-400">
            <span>Hours saved / recruiter / week</span>
            <Clock className="h-4 w-4 text-slate-400" />
          </div>
          <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">{pr.hours_saved} h</div>
          <div className="text-xs text-slate-500 dark:text-slate-400 tabular">
            of {pr.baseline_hours} h baseline · {pr.percent_reduction}% less
          </div>
        </div>
        {data.categories.map((c) => {
          const bc = s.by_category[c] || { count: 0, minutes_saved: 0 };
          const active = cats.includes(c);
          return (
            <button
              key={c}
              type="button"
              onClick={() => toggleCat(c)}
              aria-pressed={active}
              title={`Filter to ${c}`}
              className={cx("card px-4 py-3 text-left transition-shadow hover:shadow-md", active && "ring-2 ring-brand-500 dark:ring-brand-300")}
            >
              <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                <span className={cx("h-2 w-2 rounded-full", CATEGORY_STYLE[c]?.dot)} />
                {c}
              </div>
              <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">{bc.count}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400 tabular">{bc.minutes_saved} min/wk saved</div>
            </button>
          );
        })}
      </div>

      {/* Rule of thumb */}
      <section className="card">
        <button type="button" className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left" onClick={() => setRulesOpen(!rulesOpen)} aria-expanded={rulesOpen}>
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">Rule of thumb: how tasks are categorized</span>
          {rulesOpen ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        </button>
        {rulesOpen && (
          <div className="grid gap-3 px-4 pb-4 sm:grid-cols-2 xl:grid-cols-4">
            {data.categories.map((c) => (
              <div key={c} className="rounded-lg border border-slate-200 p-3 dark:border-white/10">
                <CategoryBadge category={c} />
                <p className="mt-1.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{data.category_rules[c]}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input className="input pl-8" placeholder="Search tasks, triggers, rationale…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search tasks" />
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by category">
          {data.categories.map((c) => {
            const active = cats.includes(c);
            return (
              <button
                key={c}
                type="button"
                aria-pressed={active}
                onClick={() => toggleCat(c)}
                className={cx(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                  active
                    ? "border-slate-800 bg-slate-800 text-white dark:border-white/80 dark:bg-white/90 dark:text-slate-900"
                    : "border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-white/15 dark:text-slate-300 dark:hover:bg-white/10",
                )}
              >
                <span className={cx("h-2 w-2 rounded-full", CATEGORY_STYLE[c]?.dot)} />
                {c}
              </button>
            );
          })}
        </div>
        <select className="input w-auto" value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Filter by stage">
          <option value="">All stages</option>
          {data.stages.map((st) => (
            <option key={st} value={st}>
              {st}
            </option>
          ))}
        </select>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            icon={<X className="h-3.5 w-3.5" />}
            onClick={() => {
              setQ("");
              setCats([]);
              setStage("");
            }}
          >
            Clear
          </Button>
        )}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-slate-500 tabular">
            {filtered.length} of {data.items.length} tasks
          </span>
          <div className="inline-flex rounded-lg border border-slate-300 p-0.5 dark:border-white/15" role="group" aria-label="View">
            {(
              [
                ["table", "Table", <Table2 key="t" className="h-3.5 w-3.5" />],
                ["kanban", "Kanban", <Columns3 key="k" className="h-3.5 w-3.5" />],
              ] as const
            ).map(([k, label, icon]) => (
              <button
                key={k}
                type="button"
                aria-pressed={view === k}
                onClick={() => setView(k)}
                className={cx(
                  "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium",
                  view === k ? "bg-slate-800 text-white dark:bg-white/90 dark:text-slate-900" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/10",
                )}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="card">
          <Empty icon={<Search className="h-8 w-8" />} title="No tasks match these filters">
            Try a different search or clear the category and stage filters.
          </Empty>
        </div>
      ) : view === "table" ? (
        <div className="card overflow-hidden">
          <div className="relative overflow-x-auto scrollbar-thin">
            <table className="w-full min-w-[1240px]">
              <thead className="border-b border-slate-200 dark:border-white/10">
                <tr>
                  <th className="th w-8" aria-label="Expand" />
                  <th className="th">ID</th>
                  <th className="th">Task</th>
                  <th className="th">Category</th>
                  <th className="th">Trigger → Action</th>
                  <th className="th">Delegate / SLA</th>
                  <th className="th">Frequency</th>
                  <th className="th">Min/wk</th>
                  <th className="th">Implementation</th>
                  <th className="th">Status</th>
                  {canEdit && <th className="th w-10" aria-label="Edit" />}
                </tr>
              </thead>
              <tbody>
                {data.stages
                  .map((st) => [st, filtered.filter((t) => t.stage === st)] as const)
                  .concat([["Other", filtered.filter((t) => !data.stages.includes(t.stage))] as const])
                  .filter(([, rows]) => rows.length > 0)
                  .map(([st, rows]) => {
                    const saved = rows.reduce((a, t) => a + t.est_minutes_saved_per_week, 0);
                    return (
                      <Fragment key={st}>
                        <tr className="bg-slate-50 dark:bg-white/[0.03] border-y border-slate-200 dark:border-white/10">
                          <td colSpan={canEdit ? 11 : 10} className="px-3 py-1.5">
                            <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">{st}</span>
                            <span className="ml-2 text-[11px] text-slate-500 tabular">
                              {rows.length} task{rows.length === 1 ? "" : "s"} · {saved} min/wk saved
                            </span>
                          </td>
                        </tr>
                        {rows.map((t) => {
                          const open = expanded.has(t.id);
                          return (
                            <Fragment key={t.id}>
                              <tr
                                className={cx("cursor-pointer border-b border-slate-100 hover:bg-slate-50/70 dark:border-white/5 dark:hover:bg-white/[0.03]", open && "bg-slate-50/70 dark:bg-white/[0.03]")}
                                onClick={() => toggleRow(t.id)}
                              >
                                <td className="td pr-0">
                                  <button
                                    type="button"
                                    aria-expanded={open}
                                    aria-label={open ? `Hide rationale for ${t.id}` : `Show rationale for ${t.id}`}
                                    className="rounded p-0.5 text-slate-400 hover:bg-slate-200 dark:hover:bg-white/10"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      toggleRow(t.id);
                                    }}
                                  >
                                    {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                                  </button>
                                </td>
                                <td className="td font-mono text-xs text-slate-500 whitespace-nowrap">{t.id}</td>
                                <td className="td min-w-[13rem] max-w-[18rem] font-medium text-slate-800 dark:text-slate-100">{t.task_name}</td>
                                <td className="td">
                                  <CategoryBadge category={t.category} />
                                </td>
                                <td className="td min-w-[14rem] max-w-[20rem] text-xs">
                                  <div className="text-slate-700 dark:text-slate-200">{t.trigger || <span className="text-slate-400">—</span>}</div>
                                  {t.automation_action && <div className="mt-0.5 text-slate-500 dark:text-slate-400">→ {t.automation_action}</div>}
                                </td>
                                <td className="td text-xs whitespace-nowrap">
                                  {t.delegate_to ? (
                                    <>
                                      <div className="text-slate-700 dark:text-slate-200">{teamLabel(t.delegate_to)}</div>
                                      {t.sla_hours != null && <div className="text-slate-500 tabular">{t.sla_hours}h SLA</div>}
                                    </>
                                  ) : (
                                    <span className="text-slate-400">—</span>
                                  )}
                                </td>
                                <td className="td text-xs text-slate-600 dark:text-slate-300 whitespace-nowrap">{t.frequency}</td>
                                <td className="td">
                                  <MinutesCell t={t} />
                                </td>
                                <td className="td">
                                  <ImplementationCell impl={t.implementation} />
                                </td>
                                <td className="td">
                                  <StatusBadge status={t.status} />
                                </td>
                                {canEdit && (
                                  <td className="td">
                                    <button
                                      type="button"
                                      className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-slate-200"
                                      aria-label={`Edit ${t.id}`}
                                      title="Edit task"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setEditing(t);
                                      }}
                                    >
                                      <Pencil className="h-4 w-4" />
                                    </button>
                                  </td>
                                )}
                              </tr>
                              {open && (
                                <tr className="border-b border-slate-100 dark:border-white/5 bg-slate-50/70 dark:bg-white/[0.03]">
                                  <td />
                                  <td colSpan={canEdit ? 10 : 9} className="px-3 pb-3 pt-0">
                                    <WhyPanel t={t} rule={data.category_rules[t.category]} />
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })}
                      </Fragment>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {data.categories.map((c) => {
            const col = filtered.filter((t) => t.category === c);
            const mins = col.reduce((a, t) => a + t.est_minutes_saved_per_week, 0);
            return (
              <section key={c} className="card flex flex-col overflow-hidden border-t-4" style={{ borderTopColor: CATEGORY_STYLE[c]?.bar }}>
                <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2.5 dark:border-white/10">
                  <div className="flex items-center gap-2">
                    <span className={cx("h-2.5 w-2.5 rounded-full", CATEGORY_STYLE[c]?.dot)} />
                    <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{c}</h2>
                    <span className="rounded-full bg-slate-100 px-1.5 text-[11px] text-slate-600 tabular dark:bg-white/10 dark:text-slate-300">{col.length}</span>
                  </div>
                  <span className="text-[11px] text-slate-500 tabular">{mins} min/wk</span>
                </header>
                <div className="flex-1 space-y-2 bg-slate-50/60 p-2 dark:bg-white/[0.02] min-h-[80px]">
                  {col.length === 0 && <p className="px-2 py-6 text-center text-xs text-slate-400">No tasks</p>}
                  {col.map((t) => {
                    const open = expanded.has(t.id);
                    return (
                      <article key={t.id} className="rounded-lg border border-slate-200 bg-white p-2.5 dark:border-white/10 dark:bg-[#1a1a19]">
                        <button type="button" className="block w-full text-left" onClick={() => toggleRow(t.id)} aria-expanded={open}>
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-sm font-medium leading-snug text-slate-800 dark:text-slate-100">{t.task_name}</span>
                            <span className="font-mono text-[11px] text-slate-400">{t.id}</span>
                          </div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            <Badge>{t.stage}</Badge>
                            <span className="text-[11px] text-slate-500 tabular">
                              <span className="font-semibold text-slate-700 dark:text-slate-200">{t.est_minutes_saved_per_week}</span> min/wk saved
                            </span>
                          </div>
                        </button>
                        {open && (
                          <div className="mt-2 border-t border-slate-100 pt-2 dark:border-white/5">
                            <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300">{t.rationale || "No rationale recorded."}</p>
                            <div className="mt-2 flex items-center justify-between gap-2">
                              <StatusBadge status={t.status} />
                              {canEdit && (
                                <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(t)}>
                                  Edit
                                </Button>
                              )}
                            </div>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {!canEdit && <p className="text-xs text-slate-500">Read-only view. TA leads and admins can edit categories, rationale and time estimates.</p>}

      {editing && (
        <TaskEditor
          task={editing === "new" ? null : editing}
          meta={data}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function WhyPanel({ t, rule }: { t: Task; rule?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-[#1a1a19]">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="md:col-span-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Why {t.category}</div>
          <p className="mt-1 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{t.rationale || "No rationale recorded."}</p>
          {rule && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Rule of thumb: {rule}</p>}
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <dt className="text-slate-500">Playbook</dt>
          <dd className="text-slate-700 dark:text-slate-200">{t.playbook_section || "—"}</dd>
          <dt className="text-slate-500">Current owner</dt>
          <dd className="text-slate-700 dark:text-slate-200">{t.current_owner || "—"}</dd>
          <dt className="text-slate-500">Recruiter time left</dt>
          <dd className="text-slate-700 dark:text-slate-200 tabular">{Math.max(0, t.baseline_minutes_per_week - t.est_minutes_saved_per_week)} min/wk</dd>
          {t.implementation?.type === "guardrail" && (
            <>
              <dt className="text-slate-500">Guardrail</dt>
              <dd className="text-slate-700 dark:text-slate-200">{t.implementation.description}</dd>
            </>
          )}
        </dl>
      </div>
    </div>
  );
}
