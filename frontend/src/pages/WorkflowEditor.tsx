import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Filter,
  FlaskConical,
  Loader2,
  Play,
  Plus,
  Save,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { del, errMsg, patch, post } from "../lib/api";
import { isManager, useAuth } from "../lib/auth";
import { fmtDateTime, humanize, relTime } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Badge, Button, Card, CategoryBadge, Empty, ErrorBox, Field, Loading, PageHeader, Toggle, cx, useToast } from "../components/ui";
import { cronError, describeCron } from "./Workflows";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type Cond = { _k: string; field: string; op: string; value?: any };
type Act = { _k: string; type: string; params: Record<string, any>; delay_minutes?: number | ""; conditions: Cond[]; showIf: boolean };
type Form = {
  key?: string;
  name: string;
  description: string;
  task_id: string;
  trigger_event: string;
  schedule: string;
  conditions: Cond[];
  actions: Act[];
  enabled: boolean;
  minutes_saved_per_run: string;
};
type Catalog = {
  events: Record<string, string>;
  actions: Record<string, { label: string; params: Record<string, string>; category: string }>;
  operators: string[];
  condition_fields: Record<string, { type: string; options?: string[] }>;
  stages: Record<string, string>;
  teams: Record<string, string>;
  templates: Record<string, { name: string; auto_send_allowed: boolean }>;
  draft_kinds: string[];
  workflow_templates: any[];
  guardrails: any[];
};

const ROLES: Record<string, string> = {
  recruiter: "Recruiter",
  ta_lead: "TA Lead",
  onboarding: "Onboarding / HR",
  payroll: "Payroll",
  immigration: "Immigration / Legal",
  marketing: "Marketing",
  coordinator: "Coordinator",
};
const NO_VALUE_OPS = ["exists", "not_exists", "is_true", "is_false"];
const OP_LABELS: Record<string, string> = {
  eq: "equals",
  neq: "does not equal",
  in: "is one of",
  not_in: "is not one of",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  exists: "is set",
  not_exists: "is empty",
  contains: "contains",
  is_true: "is true",
  is_false: "is false",
};
const OPS_BY_TYPE: Record<string, string[]> = {
  bool: ["is_true", "is_false", "exists", "not_exists"],
  number: ["eq", "neq", "gt", "gte", "lt", "lte", "exists", "not_exists"],
  enum: ["eq", "neq", "in", "not_in", "exists", "not_exists"],
  str: ["eq", "neq", "in", "not_in", "contains", "exists", "not_exists"],
  list: ["contains", "exists", "not_exists"],
};
const ACTION_CATEGORIES = ["Automate", "Simplify", "Delegate"];

let seq = 0;
const k = () => `k${++seq}`;

// ---------------------------------------------------------------------------
// Conversion between API shape and form state
// ---------------------------------------------------------------------------
const toConds = (cs: any[] | undefined): Cond[] => (cs || []).map((c) => ({ _k: k(), field: c.field || "", op: c.op || "eq", value: c.value }));

function toForm(w: any): Form {
  return {
    key: w.key,
    name: w.name || "",
    description: w.description || "",
    task_id: w.task_id || "",
    trigger_event: w.trigger_event || "candidate.created",
    schedule: w.schedule || "",
    conditions: toConds(w.conditions),
    actions: (w.actions || []).map((a: any) => ({
      _k: k(),
      type: a.type,
      params: { ...(a.params || {}) },
      delay_minutes: a.delay_minutes ?? "",
      conditions: toConds(a.conditions),
      showIf: !!(a.conditions && a.conditions.length),
    })),
    enabled: w.enabled ?? true,
    minutes_saved_per_run: w.minutes_saved_per_run != null ? String(w.minutes_saved_per_run) : "0",
  };
}

type Fields = Catalog["condition_fields"];

/** Normalise condition values: comma text → list for in/not_in, numbers for numeric fields. */
function cleanConds(cs: Cond[], fields: Fields) {
  return cs.map(({ field, op, value }) => {
    if (NO_VALUE_OPS.includes(op)) return { field, op };
    const numeric = fields[field]?.type === "number";
    if (op === "in" || op === "not_in") {
      const parts: any[] = (Array.isArray(value) ? value : String(value ?? "").split(",")).map((x) => (typeof x === "string" ? x.trim() : x)).filter((x) => x !== "" && x != null);
      return { field, op, value: numeric ? parts.map(Number) : parts };
    }
    return { field, op, value: value === undefined ? "" : value };
  });
}

function cleanParams(p: Record<string, any>) {
  const out: Record<string, any> = {};
  for (const [key, v] of Object.entries(p)) if (v !== "" && v !== undefined && v !== null) out[key] = v;
  return out;
}

function toPayload(f: Form, fields: Fields) {
  return {
    name: f.name.trim(),
    description: f.description,
    task_id: f.task_id || null,
    trigger_event: f.trigger_event,
    schedule: f.trigger_event === "schedule" ? f.schedule.trim() : null,
    conditions: cleanConds(f.conditions, fields),
    actions: f.actions.map((a) => {
      const out: Record<string, any> = { type: a.type };
      const params = cleanParams(a.params);
      if (Object.keys(params).length) out.params = params;
      const d = Number(a.delay_minutes);
      if (a.delay_minutes !== "" && d > 0) out.delay_minutes = d;
      if (a.conditions.length) out.conditions = cleanConds(a.conditions, fields);
      return out;
    }),
    enabled: f.enabled,
    minutes_saved_per_run: Number(f.minutes_saved_per_run) || 0,
  };
}

const BLANK: any = { name: "", description: "", trigger_event: "candidate.created", conditions: [], actions: [], enabled: false, minutes_saved_per_run: 0 };

// ---------------------------------------------------------------------------
// Flow chrome
// ---------------------------------------------------------------------------
function Connector() {
  return (
    <div className="flex flex-col items-center py-0.5" aria-hidden>
      <div className="h-4 w-px bg-slate-300 dark:bg-white/20" />
      <ChevronDown className="-mt-1.5 h-4 w-4 text-slate-400 dark:text-slate-500" />
    </div>
  );
}

function Node({ icon, step, title, subtitle, actions, children, tone = "brand" }: { icon: ReactNode; step: string; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode; tone?: "brand" | "slate" }) {
  return (
    <section className="card relative">
      <header className="flex items-start justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-white/10">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={cx(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
              tone === "brand" ? "bg-brand-100 text-brand-800 dark:bg-brand-500/20 dark:text-brand-100" : "bg-slate-100 text-slate-600 dark:bg-white/10 dark:text-slate-300",
            )}
          >
            {icon}
          </span>
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{step}</div>
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</div>
            {subtitle && <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</div>}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-0.5">{actions}</div>}
      </header>
      {children && <div className="px-4 py-3">{children}</div>}
    </section>
  );
}

function IconBtn({ label, onClick, disabled, children, danger }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode; danger?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "rounded-md p-1.5 text-slate-400 disabled:cursor-not-allowed disabled:opacity-40",
        danger ? "hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10" : "hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-slate-200",
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Conditions editor
// ---------------------------------------------------------------------------
function fieldGroups(fields: Catalog["condition_fields"]) {
  const g: Record<string, string[]> = {};
  for (const f of Object.keys(fields)) (g[f.split(".")[0]] ||= []).push(f);
  return g;
}

function ValueInput({ cond, meta, catalog, disabled, onChange }: { cond: Cond; meta?: { type: string; options?: string[] }; catalog: Catalog; disabled: boolean; onChange: (v: any) => void }) {
  const type = meta?.type || "str";
  const optLabel = (o: string) => catalog.stages[o] || humanize(o);
  if (NO_VALUE_OPS.includes(cond.op)) return <div className="input flex items-center border-dashed text-xs text-slate-400">No value needed</div>;
  if (cond.op === "in" || cond.op === "not_in") {
    // Kept as raw text while editing; converted to a list on save.
    const text = Array.isArray(cond.value) ? cond.value.join(", ") : cond.value ?? "";
    return (
      <div>
        <input
          className="input"
          disabled={disabled}
          value={text}
          placeholder={meta?.options ? meta.options.slice(0, 3).join(", ") : "value1, value2"}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Values (comma separated)"
        />
        {meta?.options && <p className="mt-1 text-[11px] text-slate-500">Comma separated. Options: {meta.options.join(", ")}</p>}
      </div>
    );
  }
  if (type === "enum" && meta?.options)
    return (
      <select className="input" disabled={disabled} value={cond.value ?? ""} onChange={(e) => onChange(e.target.value)} aria-label="Value">
        <option value="">Select…</option>
        {meta.options.map((o) => (
          <option key={o} value={o}>
            {optLabel(o)}
          </option>
        ))}
      </select>
    );
  if (type === "number")
    return (
      <input
        className="input tabular"
        type="number"
        disabled={disabled}
        value={cond.value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        aria-label="Value"
      />
    );
  if (type === "bool")
    return (
      <select className="input" disabled={disabled} value={String(cond.value ?? "true")} onChange={(e) => onChange(e.target.value === "true")} aria-label="Value">
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  return <input className="input" disabled={disabled} value={cond.value ?? ""} onChange={(e) => onChange(e.target.value)} aria-label="Value" />;
}

function ConditionsEditor({ conds, onChange, catalog, ro, emptyText }: { conds: Cond[]; onChange: (c: Cond[]) => void; catalog: Catalog; ro: boolean; emptyText: string }) {
  const groups = useMemo(() => fieldGroups(catalog.condition_fields), [catalog]);
  const update = (i: number, patchC: Partial<Cond>) => onChange(conds.map((c, j) => (j === i ? { ...c, ...patchC } : c)));
  const firstField = Object.keys(catalog.condition_fields)[0] || "candidate.stage";
  return (
    <div className="space-y-2">
      {conds.length === 0 && <p className="text-xs text-slate-500 dark:text-slate-400">{emptyText}</p>}
      {conds.map((c, i) => {
        const meta = catalog.condition_fields[c.field];
        const allowed = meta ? OPS_BY_TYPE[meta.type] || catalog.operators : catalog.operators;
        const ops = allowed.includes(c.op) ? allowed : [c.op, ...allowed];
        return (
          <div key={c._k} className="grid items-start gap-2 rounded-lg border border-slate-200 p-2 dark:border-white/10 sm:grid-cols-[auto_minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,1.2fr)_auto]">
            <span className="hidden pt-2 text-[11px] font-semibold uppercase text-slate-400 sm:block">{i === 0 ? "If" : "and"}</span>
            <select
              className="input"
              disabled={ro}
              value={c.field}
              aria-label="Field"
              onChange={(e) => {
                const m = catalog.condition_fields[e.target.value];
                const nextOps = m ? OPS_BY_TYPE[m.type] || catalog.operators : catalog.operators;
                update(i, { field: e.target.value, op: nextOps.includes(c.op) ? c.op : nextOps[0], value: undefined });
              }}
            >
              {!catalog.condition_fields[c.field] && <option value={c.field}>{c.field}</option>}
              {Object.entries(groups).map(([g, fs]) => (
                <optgroup key={g} label={humanize(g)}>
                  {fs.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <select className="input" disabled={ro} value={c.op} onChange={(e) => update(i, { op: e.target.value })} aria-label="Operator">
              {ops.map((o) => (
                <option key={o} value={o}>
                  {OP_LABELS[o] || o}
                </option>
              ))}
            </select>
            <ValueInput cond={c} meta={meta} catalog={catalog} disabled={ro} onChange={(v) => update(i, { value: v })} />
            {!ro && (
              <div className="flex justify-end sm:pt-1">
                <IconBtn label="Remove condition" danger onClick={() => onChange(conds.filter((_, j) => j !== i))}>
                  <Trash2 className="h-4 w-4" />
                </IconBtn>
              </div>
            )}
          </div>
        );
      })}
      {!ro && (
        <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => onChange([...conds, { _k: k(), field: firstField, op: OPS_BY_TYPE[catalog.condition_fields[firstField]?.type]?.[0] || "eq", value: undefined }])}>
          Add condition
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Action params
// ---------------------------------------------------------------------------
function ParamInput({ name, kind, value, onChange, catalog, ro }: { name: string; kind: string; value: any; onChange: (v: any) => void; catalog: Catalog; ro: boolean }) {
  const label = humanize(name);
  const sel = (opts: [string, string][], placeholder = "Select…") => (
    <select className="input" disabled={ro} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {value && !opts.some(([v]) => v === value) && <option value={value}>{value}</option>}
      {opts.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
  switch (kind) {
    case "int":
      return (
        <Field label={label}>
          <input className="input tabular" type="number" step={1} disabled={ro} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : parseInt(e.target.value, 10))} />
        </Field>
      );
    case "bool":
      return (
        <div>
          <span className="label">{label}</span>
          <div className="py-1.5">
            <Toggle checked={!!value} disabled={ro} onChange={onChange} label={<span className="text-xs text-slate-600 dark:text-slate-300">{value ? "Yes" : "No"}</span>} />
          </div>
        </div>
      );
    case "stage":
      return <Field label={label}>{sel(Object.entries(catalog.stages))}</Field>;
    case "team":
      return <Field label={label}>{sel(Object.entries(catalog.teams))}</Field>;
    case "draft_kind":
      return <Field label={label}>{sel(catalog.draft_kinds.map((d) => [d, humanize(d)]))}</Field>;
    case "role":
      return <Field label={label}>{sel(Object.entries(ROLES))}</Field>;
    case "owner|role":
      return (
        <Field label={label}>
          {sel(
            [
              ["owner", "Candidate owner"],
              ["role", "Everyone with a role"],
            ],
            "Candidate owner (default)",
          )}
        </Field>
      );
    case "template_key": {
      const all = Object.entries(catalog.templates);
      const allowed = all.filter(([, t]) => t.auto_send_allowed);
      const hidden = all.length - allowed.length;
      return (
        <Field
          label={label}
          hint={
            hidden > 0
              ? `${hidden} personalized template${hidden === 1 ? " is" : "s are"} hidden. Outreach written for one candidate must be approved by a recruiter, so use “Create a draft” for those.`
              : undefined
          }
        >
          {sel(allowed.map(([key, t]) => [key, t.name]))}
        </Field>
      );
    }
    default:
      return (
        <Field label={label} hint={name === "title" || name === "subject" ? "{candidate} is replaced with the candidate's name" : undefined}>
          <input className="input" disabled={ro} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
        </Field>
      );
  }
}

function ActionNode({
  a,
  idx,
  count,
  catalog,
  ro,
  onChange,
  onMove,
  onRemove,
}: {
  a: Act;
  idx: number;
  count: number;
  catalog: Catalog;
  ro: boolean;
  onChange: (a: Act) => void;
  onMove: (dir: -1 | 1) => void;
  onRemove: () => void;
}) {
  const meta = catalog.actions[a.type];
  const schema = meta?.params || {};
  const extra = Object.keys(a.params).filter((p) => !(p in schema));
  const setParam = (p: string, v: any) => onChange({ ...a, params: { ...a.params, [p]: v } });
  const visibleParams = Object.entries(schema).filter(([p]) => !(p === "role" && "to" in schema && a.params.to !== "role"));
  const grouped = ACTION_CATEGORIES.map((c) => [c, Object.entries(catalog.actions).filter(([, m]) => m.category === c)] as const);
  const otherCats = Object.entries(catalog.actions).filter(([, m]) => !ACTION_CATEGORIES.includes(m.category));

  return (
    <Node
      icon={<Play className="h-4 w-4" />}
      step={idx === 0 ? "Then" : "And then"}
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span>
            Action {idx + 1}: {meta?.label || a.type}
          </span>
          {meta && <CategoryBadge category={meta.category} />}
          {Number(a.delay_minutes) > 0 && (
            <Badge>
              <Clock className="h-3 w-3" /> after {a.delay_minutes} min
            </Badge>
          )}
        </span>
      }
      actions={
        !ro && (
          <>
            <IconBtn label="Move up" disabled={idx === 0} onClick={() => onMove(-1)}>
              <ArrowUp className="h-4 w-4" />
            </IconBtn>
            <IconBtn label="Move down" disabled={idx === count - 1} onClick={() => onMove(1)}>
              <ArrowDown className="h-4 w-4" />
            </IconBtn>
            <IconBtn label="Remove action" danger onClick={onRemove}>
              <Trash2 className="h-4 w-4" />
            </IconBtn>
          </>
        )
      }
    >
      <div className="space-y-3">
        <Field label="Action">
          <select
            className="input"
            disabled={ro}
            value={a.type}
            onChange={(e) => {
              const nextSchema = catalog.actions[e.target.value]?.params || {};
              const kept = Object.fromEntries(Object.entries(a.params).filter(([p]) => p in nextSchema));
              onChange({ ...a, type: e.target.value, params: kept });
            }}
          >
            {!meta && <option value={a.type}>{a.type}</option>}
            {grouped.map(([c, items]) =>
              items.length ? (
                <optgroup key={c} label={c}>
                  {items.map(([key, m]) => (
                    <option key={key} value={key}>
                      {m.label}
                    </option>
                  ))}
                </optgroup>
              ) : null,
            )}
            {otherCats.length > 0 && (
              <optgroup label="Other">
                {otherCats.map(([key, m]) => (
                  <option key={key} value={key}>
                    {m.label}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </Field>

        {(visibleParams.length > 0 || extra.length > 0) && (
          <div className="grid gap-3 sm:grid-cols-2">
            {visibleParams.map(([p, kind]) => (
              <ParamInput key={p} name={p} kind={kind} value={a.params[p]} onChange={(v) => setParam(p, v)} catalog={catalog} ro={ro} />
            ))}
            {extra.map((p) => (
              <ParamInput key={p} name={p} kind={typeof a.params[p] === "number" ? "int" : typeof a.params[p] === "boolean" ? "bool" : "str"} value={a.params[p]} onChange={(v) => setParam(p, v)} catalog={catalog} ro={ro} />
            ))}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Delay (minutes)" hint="Blank or 0 runs immediately. Delayed actions are queued and re-check their “only if” conditions when they run.">
            <input
              className="input tabular"
              type="number"
              min={0}
              disabled={ro}
              value={a.delay_minutes ?? ""}
              onChange={(e) => onChange({ ...a, delay_minutes: e.target.value === "" ? "" : Math.max(0, Number(e.target.value)) })}
            />
          </Field>
        </div>

        <div className="rounded-lg border border-slate-200 dark:border-white/10">
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium text-slate-600 dark:text-slate-300"
            onClick={() => onChange({ ...a, showIf: !a.showIf })}
            aria-expanded={a.showIf}
          >
            <span className="flex items-center gap-1.5">
              <Filter className="h-3.5 w-3.5" /> Only if…
              {a.conditions.length > 0 && <Badge tone="brand">{a.conditions.length}</Badge>}
            </span>
            {a.showIf ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
          {a.showIf && (
            <div className="border-t border-slate-200 px-3 py-2 dark:border-white/10">
              <ConditionsEditor conds={a.conditions} onChange={(cs) => onChange({ ...a, conditions: cs })} catalog={catalog} ro={ro} emptyText="No extra conditions. This action runs whenever the workflow matches." />
            </div>
          )}
        </div>
      </div>
    </Node>
  );
}

// ---------------------------------------------------------------------------
// Trigger
// ---------------------------------------------------------------------------
function TriggerNode({ form, set, catalog, ro }: { form: Form; set: (p: Partial<Form>) => void; catalog: Catalog; ro: boolean }) {
  const [time, setTime] = useState("07:30");
  const isSched = form.trigger_event === "schedule";
  const err = isSched ? cronError(form.schedule) : null;
  const cronAt = (dow: string) => {
    const [h, m] = time.split(":").map((x) => parseInt(x, 10));
    return `${Number.isFinite(m) ? m : 0} ${Number.isFinite(h) ? h : 7} * * ${dow}`;
  };
  const presets: [string, string][] = [
    ["Hourly", "0 * * * *"],
    ["Every 15 min", "*/15 * * * *"],
    ["Nightly 2:00", "0 2 * * *"],
    ["Weekly · Monday 8:00", "0 8 * * mon"],
  ];
  return (
    <Node icon={isSched ? <CalendarClock className="h-4 w-4" /> : <Zap className="h-4 w-4" />} step="When" title={isSched ? `On a schedule: ${form.schedule ? describeCron(form.schedule) : "not set"}` : catalog.events[form.trigger_event] || form.trigger_event}>
      <div className="space-y-3">
        <Field label="Trigger">
          <select className="input" disabled={ro} value={form.trigger_event} onChange={(e) => set({ trigger_event: e.target.value })}>
            {!catalog.events[form.trigger_event] && <option value={form.trigger_event}>{form.trigger_event}</option>}
            <optgroup label="Events">
              {Object.entries(catalog.events)
                .filter(([key]) => key !== "schedule")
                .map(([key, d]) => (
                  <option key={key} value={key}>
                    {d}
                  </option>
                ))}
            </optgroup>
            <optgroup label="Time">
              <option value="schedule">{catalog.events.schedule || "Runs on a cron schedule"}</option>
            </optgroup>
          </select>
          <span className="mt-1 block text-[11px] text-slate-500">
            Event key: <code>{form.trigger_event}</code>
          </span>
        </Field>
        {isSched && (
          <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
            <Field label="Cron expression (minute hour day month weekday, server local time)">
              <input className={cx("input font-mono", err && form.schedule && "border-red-400 focus:ring-red-400/50")} disabled={ro} value={form.schedule} placeholder="30 7 * * mon-fri" onChange={(e) => set({ schedule: e.target.value })} />
            </Field>
            <p className={cx("flex items-center gap-1.5 text-xs", err ? "text-red-700 dark:text-red-300" : "text-slate-600 dark:text-slate-300")}>
              {err ? <XCircle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5 text-[var(--status-good)]" />}
              {err ? (form.schedule ? err : "Enter a schedule or pick a preset") : `Valid: ${describeCron(form.schedule)}`}
            </p>
            {!ro && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-[11px] font-medium text-slate-500">Presets:</span>
                <span className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white py-0.5 pl-2 pr-0.5 dark:border-white/15 dark:bg-white/5">
                  <input type="time" className="bg-transparent text-xs outline-none tabular" value={time} onChange={(e) => setTime(e.target.value)} aria-label="Preset time" />
                  <Button size="sm" variant="ghost" onClick={() => set({ schedule: cronAt("mon-fri") })}>
                    Weekdays
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => set({ schedule: cronAt("*") })}>
                    Daily
                  </Button>
                </span>
                {presets.map(([l, c]) => (
                  <Button key={c} size="sm" onClick={() => set({ schedule: c })}>
                    {l}
                  </Button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Node>
  );
}

// ---------------------------------------------------------------------------
// Runs / jobs
// ---------------------------------------------------------------------------
function RunStatus({ status }: { status: string }) {
  if (status === "completed")
    return (
      <Badge tone="green">
        <CheckCircle2 className="h-3 w-3" /> Completed
      </Badge>
    );
  if (status === "failed")
    return (
      <Badge tone="red">
        <XCircle className="h-3 w-3" /> Failed
      </Badge>
    );
  return <Badge tone="blue">{humanize(status)}</Badge>;
}

function JobStatus({ status }: { status: string }) {
  const map: Record<string, [string, ReactNode]> = {
    queued: ["blue", <Clock key="q" className="h-3 w-3" />],
    running: ["blue", <Loader2 key="r" className="h-3 w-3 animate-spin" />],
    done: ["green", <CheckCircle2 key="d" className="h-3 w-3" />],
    failed: ["red", <XCircle key="f" className="h-3 w-3" />],
    cancelled: ["gray", <XCircle key="c" className="h-3 w-3" />],
  };
  const [tone, icon] = map[status] || ["gray", null];
  return (
    <Badge tone={tone}>
      {icon}
      {humanize(status)}
    </Badge>
  );
}

function RunActions({ detail, catalog }: { detail: any; catalog: Catalog }) {
  if (detail?.seeded) return <span className="text-xs text-slate-400">Seeded history</span>;
  const acts: any[] = detail?.actions || [];
  if (!acts.length) return <span className="text-xs text-slate-400">No actions</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {acts.map((a, i) => {
        const tone = a.status === "done" ? "green" : a.status === "retrying" ? "red" : a.status === "skipped" ? "gray" : "blue";
        const extra = Object.entries(a)
          .filter(([key]) => !["type", "status", "reasons"].includes(key))
          .map(([key, v]) => `${key}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
          .join(" · ");
        return (
          <Badge key={i} tone={tone} title={[a.reasons?.join("; "), extra].filter(Boolean).join(" — ") || undefined}>
            {catalog.actions[a.type]?.label ? shorten(catalog.actions[a.type].label) : a.type}: {a.status}
          </Badge>
        );
      })}
    </div>
  );
}
const shorten = (s: string) => (s.length > 32 ? s.slice(0, 30) + "…" : s);

// ---------------------------------------------------------------------------
// Dry run
// ---------------------------------------------------------------------------
function DryRun({ wid, disabledReason, dirty }: { wid: number | null; disabledReason?: string; dirty: boolean }) {
  const { data: cands } = useApi<any>("/api/candidates?limit=50");
  const [cid, setCid] = useState("");
  const [payload, setPayload] = useState("");
  const [showPayload, setShowPayload] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const list: any[] = Array.isArray(cands) ? cands : cands?.items || [];

  async function run() {
    if (!wid) return;
    setErr(null);
    let pl: any = {};
    if (payload.trim()) {
      try {
        pl = JSON.parse(payload);
      } catch {
        return setErr("Event payload must be valid JSON, e.g. {\"reply_class\": \"interested\"}");
      }
    }
    setBusy(true);
    try {
      setRes(await post(`/api/workflows/${wid}/test`, { candidate_id: cid ? Number(cid) : null, payload: pl }));
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Test (dry run)" subtitle="Evaluates the conditions against a real candidate. No action is executed.">
      {disabledReason ? (
        <p className="text-xs text-slate-500">{disabledReason}</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-[minmax(0,1fr)_5.5rem] gap-2">
            <Field label="Candidate">
              <select className="input" value={list.some((c) => String(c.id) === cid) ? cid : ""} onChange={(e) => setCid(e.target.value)}>
                <option value="">{list.length ? "Pick a recent candidate…" : "No candidates loaded"}</option>
                {list.map((c) => (
                  <option key={c.id} value={c.id}>
                    #{c.id} {c.full_name} · {c.stage_label || c.stage}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="or ID">
              <input className="input tabular" inputMode="numeric" value={cid} onChange={(e) => setCid(e.target.value.replace(/\D/g, ""))} placeholder="42" />
            </Field>
          </div>
          <div>
            <button type="button" className="flex items-center gap-1 text-xs font-medium text-slate-600 dark:text-slate-300" onClick={() => setShowPayload(!showPayload)} aria-expanded={showPayload}>
              {showPayload ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Event payload (optional)
            </button>
            {showPayload && (
              <textarea
                className="input mt-1 min-h-[64px] font-mono text-xs"
                value={payload}
                onChange={(e) => setPayload(e.target.value)}
                placeholder='{"reply_class": "interested", "connected": true}'
                aria-label="Event payload JSON"
              />
            )}
          </div>
          {dirty && <p className="text-[11px] text-amber-700 dark:text-amber-300">The dry run uses the saved version. Save first to test your changes.</p>}
          <Button icon={<FlaskConical className="h-4 w-4" />} loading={busy} onClick={run} className="w-full">
            Run dry test
          </Button>
          <ErrorBox error={err} />
          {res && (
            <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-white/10">
              <div className="flex items-center gap-2 text-sm font-medium">
                {res.matched ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-[var(--status-good)]" /> <span className="text-slate-800 dark:text-slate-100">Matched: conditions pass</span>
                  </>
                ) : (
                  <>
                    <XCircle className="h-4 w-4 text-[var(--status-critical)]" /> <span className="text-slate-800 dark:text-slate-100">Not matched</span>
                  </>
                )}
              </div>
              {res.reasons?.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600 dark:text-slate-300">
                  {res.reasons.map((r: string, i: number) => (
                    <li key={i} className="font-mono">
                      {r}
                    </li>
                  ))}
                </ul>
              )}
              <ul className="space-y-1">
                {res.actions?.map((a: any, i: number) => (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    {a.would_run ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--status-good)]" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />}
                    <span className="min-w-0">
                      <span className="text-slate-700 dark:text-slate-200">{a.label}</span>
                      <span className="ml-1 text-slate-500">
                        {a.would_run ? "would run" : "would not run"}
                        {a.delay_minutes ? ` after ${a.delay_minutes} min` : ""}
                      </span>
                      {a.reasons?.length > 0 && <span className="block font-mono text-[11px] text-slate-500">{a.reasons.join("; ")}</span>}
                    </span>
                  </li>
                ))}
              </ul>
              <details className="text-xs">
                <summary className="cursor-pointer text-slate-500">Evaluation context</summary>
                <pre className="mt-1 max-h-64 overflow-auto rounded bg-slate-50 p-2 text-[11px] dark:bg-white/5">{JSON.stringify(res.context, null, 2)}</pre>
              </details>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function WorkflowEditor() {
  const { id = "new" } = useParams();
  const [search] = useSearchParams();
  const templateKey = search.get("template");
  const isNew = id === "new";
  const nav = useNavigate();
  const toast = useToast();
  const { user } = useAuth();
  const canEdit = isManager(user);
  const isAdmin = user?.role === "admin";

  const { data: catalog, error: catErr } = useApi<Catalog>("/api/workflows/catalog");
  const { data: wf, error: wfErr, setData: setWf, reload } = useApi<any>(isNew ? null : `/api/workflows/${id}`);
  const { data: tasks } = useApi<any>("/api/tasks");

  const [form, setForm] = useState<Form | null>(null);
  const [initial, setInitial] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedFor = useRef<string | null>(null);

  // Initialise the form for an existing workflow (once per id).
  useEffect(() => {
    if (!isNew && wf && catalog && loadedFor.current !== `id:${wf.id}`) {
      loadedFor.current = `id:${wf.id}`;
      const f = toForm(wf);
      setForm(f);
      setInitial(JSON.stringify(toPayload(f, catalog.condition_fields)));
      setError(null);
    }
  }, [isNew, wf, catalog]);

  // Initialise a new workflow, optionally from a template.
  useEffect(() => {
    if (!isNew || !catalog) return;
    const tag = `new:${templateKey || ""}`;
    if (loadedFor.current === tag) return;
    loadedFor.current = tag;
    const tpl = templateKey ? catalog.workflow_templates.find((t) => t.key === templateKey) : null;
    const f = toForm(tpl ? { ...tpl, enabled: false } : BLANK);
    setForm(f);
    setInitial(JSON.stringify(toPayload(toForm(BLANK), catalog.condition_fields)));
    setError(templateKey && !tpl ? `Template “${templateKey}” was not found; starting from a blank workflow.` : null);
  }, [isNew, catalog, templateKey]);

  const dirty = !!form && !!catalog && JSON.stringify(toPayload(form, catalog.condition_fields)) !== initial;

  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  if (catErr || wfErr) return <ErrorBox error={catErr || wfErr} />;
  if (!catalog || !form || (!isNew && !wf)) return <Loading />;

  const ro = !canEdit;
  const set = (p: Partial<Form>) => setForm((f) => (f ? { ...f, ...p } : f));
  const setAction = (i: number, a: Act) => set({ actions: form.actions.map((x, j) => (j === i ? a : x)) });
  const moveAction = (i: number, dir: -1 | 1) => {
    const arr = [...form.actions];
    const j = i + dir;
    if (j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    set({ actions: arr });
  };
  const addAction = () => set({ actions: [...form.actions, { _k: k(), type: "notify", params: { to: "owner", title: "" }, delay_minutes: "", conditions: [], showIf: false }] });
  const taskItems: any[] = tasks?.items || [];
  const isSched = form.trigger_event === "schedule";

  function validate(): string | null {
    if (!form) return "Nothing to save";
    if (!form.name.trim()) return "Give the workflow a name.";
    if (!form.actions.length) return "Add at least one action.";
    if (isSched) {
      const e = cronError(form.schedule);
      if (e) return `Schedule: ${e}`;
    }
    for (const [i, a] of form.actions.entries()) {
      if (a.type === "send_template" && !a.params.template) return `Action ${i + 1}: choose an approved template.`;
      const schema = catalog!.actions[a.type]?.params || {};
      for (const [p, kind] of Object.entries(schema)) if ((kind === "stage" || kind === "team") && !a.params[p]) return `Action ${i + 1}: choose a ${humanize(p).toLowerCase()}.`;
      if (a.type === "notify" && a.params.to === "role" && !a.params.role) return `Action ${i + 1}: choose which role to notify.`;
    }
    const allConds = cleanConds([...form.conditions, ...form.actions.flatMap((a) => a.conditions)], catalog!.condition_fields);
    for (const c of allConds) {
      if (!("value" in c)) continue;
      const v: any = c.value;
      if (v === "" || v == null || (Array.isArray(v) && v.length === 0) || (typeof v === "number" && Number.isNaN(v))) return `Condition on ${c.field} needs a value.`;
      if (Array.isArray(v) && v.some((x) => typeof x === "number" && Number.isNaN(x))) return `Condition on ${c.field}: values must be numbers.`;
    }
    const m = Number(form.minutes_saved_per_run);
    if (!Number.isFinite(m) || m < 0) return "Minutes saved per run must be zero or more.";
    return null;
  }

  async function save() {
    if (!form) return;
    const v = validate();
    if (v) return setError(v);
    setError(null);
    setSaving(true);
    const body = toPayload(form, catalog!.condition_fields);
    try {
      if (isNew) {
        const created = await post("/api/workflows", { ...body, key: form.key });
        toast("success", `Created “${created.name}”`);
        nav(`/workflows/${created.id}`, { replace: true });
      } else {
        const updated = await patch(`/api/workflows/${wf.id}`, body);
        setWf((w: any) => ({ ...w, ...updated }));
        const f = toForm(updated);
        setForm(f);
        setInitial(JSON.stringify(toPayload(f, catalog!.condition_fields)));
        toast("success", "Workflow saved");
      }
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  async function runNow() {
    setRunning(true);
    try {
      const r = await post(`/api/workflows/${wf.id}/run-now`);
      toast(r.last_run?.status === "failed" ? "warning" : "success", r.last_run ? `Run finished: ${r.last_run.status}` : "Run queued");
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setRunning(false);
    }
  }

  async function remove() {
    if (!confirm(`Delete “${wf.name}”? Its run history is deleted too. This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await del(`/api/workflows/${wf.id}`);
      toast("success", "Workflow deleted");
      nav("/workflows");
    } catch (e) {
      toast("error", errMsg(e));
      setDeleting(false);
    }
  }

  const runs: any[] = wf?.runs || [];
  const jobs: any[] = wf?.jobs || [];
  const openJobs = jobs.filter((j) => ["queued", "running", "failed"].includes(j.status));

  return (
    <div className="space-y-5">
      <div>
        <Link to="/workflows" className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          <ArrowLeft className="h-3.5 w-3.5" /> Workflow Builder
        </Link>
      </div>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {isNew ? (form.name ? form.name : "New workflow") : form.name || wf.name}
            {!isNew && wf.system && <Badge title="System workflow: can be disabled but not deleted">System</Badge>}
            {!isNew && (
              <Badge tone={wf.enabled ? "green" : "gray"}>
                {wf.enabled ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {wf.enabled ? "Enabled" : "Disabled"}
              </Badge>
            )}
            {dirty && canEdit && <Badge tone="amber">Unsaved changes</Badge>}
          </span>
        }
        subtitle={isNew ? (templateKey ? "Starting from a template. Review each step, then save." : "Build a trigger → conditions → actions flow.") : wf.description || undefined}
        actions={
          canEdit && (
            <>
              {!isNew && isSched && (
                <Button icon={<Play className="h-4 w-4" />} loading={running} onClick={runNow} disabled={dirty} title={dirty ? "Save your changes first" : "Run this scheduled workflow now"}>
                  Run now
                </Button>
              )}
              {!isNew && isAdmin && !wf.system && (
                <Button variant="ghost" icon={<Trash2 className="h-4 w-4" />} loading={deleting} onClick={remove} className="text-red-700 dark:text-red-300">
                  Delete
                </Button>
              )}
              <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={saving} onClick={save} disabled={!isNew && !dirty}>
                {isNew ? "Create workflow" : "Save"}
              </Button>
            </>
          )
        }
      />

      {ro && <div className="card px-4 py-2.5 text-xs text-slate-600 dark:text-slate-300">Read-only view. Only TA leads and admins can edit, test or run workflows.</div>}
      <ErrorBox error={error} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* Flow */}
        <div className="min-w-0">
          <TriggerNode form={form} set={set} catalog={catalog} ro={ro} />
          <Connector />
          <Node
            icon={<Filter className="h-4 w-4" />}
            step="Only if"
            title={form.conditions.length ? `${form.conditions.length} condition${form.conditions.length === 1 ? "" : "s"}` : "No conditions"}
            subtitle="All conditions must match (AND)."
            tone="slate"
          >
            <ConditionsEditor
              conds={form.conditions}
              onChange={(c) => set({ conditions: c })}
              catalog={catalog}
              ro={ro}
              emptyText={isSched ? "Runs every time the schedule fires." : "Runs every time this event happens."}
            />
          </Node>
          {form.actions.map((a, i) => (
            <div key={a._k}>
              <Connector />
              <ActionNode
                a={a}
                idx={i}
                count={form.actions.length}
                catalog={catalog}
                ro={ro}
                onChange={(na) => setAction(i, na)}
                onMove={(d) => moveAction(i, d)}
                onRemove={() => set({ actions: form.actions.filter((_, j) => j !== i) })}
              />
            </div>
          ))}
          {!ro && (
            <>
              <Connector />
              <button
                type="button"
                onClick={addAction}
                className="flex w-full items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-slate-300 py-3 text-sm font-medium text-slate-600 hover:border-brand-400 hover:bg-brand-50/50 hover:text-brand-800 dark:border-white/15 dark:text-slate-300 dark:hover:border-brand-300 dark:hover:bg-brand-500/10 dark:hover:text-brand-100"
              >
                <Plus className="h-4 w-4" /> Add action
              </button>
            </>
          )}
          {ro && form.actions.length === 0 && (
            <div className="card mt-2">
              <Empty title="No actions" />
            </div>
          )}
        </div>

        {/* Side panel */}
        <div className="min-w-0 space-y-5">
          <Card title="Details">
            <div className="space-y-3">
              <Field label="Name">
                <input className="input" disabled={ro} value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. Notify owner on hot reply" />
              </Field>
              <Field label="Description">
                <textarea className="input min-h-[72px]" disabled={ro} value={form.description} onChange={(e) => set({ description: e.target.value })} />
              </Field>
              <Field label="Linked task" hint="The Task Map row this workflow implements.">
                <select className="input" disabled={ro} value={form.task_id} onChange={(e) => set({ task_id: e.target.value })}>
                  <option value="">None</option>
                  {form.task_id && !taskItems.some((t) => t.id === form.task_id) && <option value={form.task_id}>{form.task_id}</option>}
                  {taskItems.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.id} · {t.task_name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Minutes saved per run" hint="Used for measured impact: runs × minutes.">
                <input className="input tabular" type="number" min={0} step={0.5} disabled={ro} value={form.minutes_saved_per_run} onChange={(e) => set({ minutes_saved_per_run: e.target.value })} />
              </Field>
              <Toggle checked={form.enabled} disabled={ro} onChange={(v) => set({ enabled: v })} label={<span className="text-slate-700 dark:text-slate-200">{form.enabled ? "Enabled" : "Disabled"}</span>} />
              {isNew && !form.enabled && <p className="text-[11px] text-slate-500">New workflows start disabled. Save, run a dry test, then enable.</p>}
              {!isNew && (
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-slate-200 pt-3 text-xs dark:border-white/10">
                  <dt className="text-slate-500">Key</dt>
                  <dd className="truncate font-mono text-slate-700 dark:text-slate-200" title={wf.key}>
                    {wf.key}
                  </dd>
                  <dt className="text-slate-500">Runs</dt>
                  <dd className="text-slate-700 dark:text-slate-200 tabular">{wf.run_count?.toLocaleString()}</dd>
                  <dt className="text-slate-500">Last run</dt>
                  <dd className="text-slate-700 dark:text-slate-200">{relTime(wf.last_run_at)}</dd>
                  <dt className="text-slate-500">Created</dt>
                  <dd className="text-slate-700 dark:text-slate-200">{fmtDateTime(wf.created_at)}</dd>
                </dl>
              )}
            </div>
          </Card>
          {canEdit && <DryRun wid={isNew ? null : wf.id} dirty={dirty} disabledReason={isNew ? "Save the workflow first, then test it against a candidate." : undefined} />}
        </div>
      </div>

      {!isNew && (
        <>
          <Card title="Recent runs" subtitle="Last 50 runs. Only runs whose conditions matched are logged.">
            {runs.length === 0 ? (
              <Empty icon={<Play className="h-8 w-8" />} title="No runs yet">
                {isSched ? "This workflow runs on its schedule, or use Run now." : "This workflow runs the next time its trigger event happens."}
              </Empty>
            ) : (
              <div className="relative -mx-4 max-h-[28rem] overflow-auto scrollbar-thin">
                <table className="w-full min-w-[640px]">
                  <thead className="sticky top-0 border-y border-slate-200 bg-white dark:border-white/10 dark:bg-[#1a1a19]">
                    <tr>
                      <th className="th pl-4">When</th>
                      <th className="th">Status</th>
                      <th className="th">Candidate</th>
                      <th className="th pr-4">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.id} className="border-b border-slate-100 dark:border-white/5">
                        <td className="td whitespace-nowrap pl-4 text-xs">
                          <div className="text-slate-700 dark:text-slate-200">{fmtDateTime(r.at)}</div>
                          <div className="text-slate-500">{relTime(r.at)}</div>
                        </td>
                        <td className="td">
                          <RunStatus status={r.status} />
                        </td>
                        <td className="td text-xs">
                          {r.candidate_id ? (
                            <Link to={`/candidates/${r.candidate_id}`} className="text-brand-700 hover:underline dark:text-brand-200">
                              #{r.candidate_id}
                            </Link>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="td pr-4">
                          <RunActions detail={r.detail} catalog={catalog} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Queued & failed jobs" subtitle={`Delayed actions and retries for this workflow${jobs.length > openJobs.length ? ` · ${jobs.length - openJobs.length} finished job${jobs.length - openJobs.length === 1 ? "" : "s"} hidden` : ""}`}>
            {openJobs.length === 0 ? (
              <p className="text-xs text-slate-500">Nothing queued or failed.</p>
            ) : (
              <div className="relative -mx-4 overflow-x-auto scrollbar-thin">
                <table className="w-full min-w-[640px]">
                  <thead className="border-y border-slate-200 dark:border-white/10">
                    <tr>
                      <th className="th pl-4">Job</th>
                      <th className="th">Status</th>
                      <th className="th">Run at</th>
                      <th className="th text-right">Attempts</th>
                      <th className="th pr-4">Last error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {openJobs.map((j) => (
                      <tr key={j.id} className="border-b border-slate-100 dark:border-white/5">
                        <td className="td pl-4 text-xs">
                          <span className="font-mono text-slate-500">#{j.id}</span> <span className="text-slate-700 dark:text-slate-200">{humanize(j.type)}</span>
                          {j.payload?.action_index != null && <span className="text-slate-500"> · action {j.payload.action_index + 1}</span>}
                        </td>
                        <td className="td">
                          <JobStatus status={j.status} />
                        </td>
                        <td className="td whitespace-nowrap text-xs text-slate-600 dark:text-slate-300">
                          {fmtDateTime(j.run_at)} <span className="text-slate-500">({relTime(j.run_at)})</span>
                        </td>
                        <td className="td text-right text-xs tabular">
                          {j.attempts}/{j.max_attempts}
                        </td>
                        <td className="td max-w-[20rem] pr-4 text-xs text-red-700 dark:text-red-300">{j.last_error || <span className="text-slate-400">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
