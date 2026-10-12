import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, Clock, Info, Printer, TrendingDown, Users } from "lucide-react";
import { CATEGORY_STYLE } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Button, Card, CategoryBadge, Empty, ErrorBox, Loading, PageHeader, Toggle, cx } from "../components/ui";

type Bucket = { count: number; minutes_saved: number; baseline: number };
type ImpactData = {
  per_recruiter_week: { baseline_hours: number; hours_saved: number; after_hours: number; percent_reduction: number };
  team_week: { recruiters: number; hours_saved: number };
  by_category: Record<string, Bucket>;
  by_stage: Record<string, Bucket>;
  task_count: number;
  measured_last_7d: { hours_saved_team: number; hours_saved_per_recruiter: number; workflows: { name: string; runs: number; minutes: number }[] };
  top_tasks: { id: string; task_name: string; category: string; minutes: number }[];
};

const CATEGORIES = ["Automate", "Delegate", "Simplify", "Keep Human"];
const fmt = (n: number, d = 0) => n.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 });

// ---------------------------------------------------------------------------
// Chart primitives
// ---------------------------------------------------------------------------
function Tip({ title, rows }: { title: ReactNode; rows: { label: ReactNode; value: ReactNode; swatch?: string }[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-white/10 dark:bg-[#232322]">
      <div className="mb-1 font-semibold text-slate-800 dark:text-slate-100">{title}</div>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
            {r.swatch && <span className="h-2 w-2 rounded-sm" style={{ background: r.swatch }} />}
            {r.label}
          </span>
          <span className="font-medium text-slate-800 dark:text-slate-100 tabular">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

type HRow = { key: string; label: ReactNode; value: number; color: string; track?: number; valueLabel: string; tip: { label: ReactNode; value: ReactNode; swatch?: string }[] };

/** Horizontal bars in plain HTML: one row per item, thin bar with a 4px rounded end, hover tooltip. */
function HBars({ rows, max, labelWidth = "w-36 sm:w-44" }: { rows: HRow[]; max?: number; labelWidth?: string }) {
  const [hover, setHover] = useState<string | null>(null);
  const m = max ?? Math.max(1, ...rows.map((r) => Math.max(r.value, r.track ?? 0)));
  return (
    <div className="space-y-1" role="list">
      {rows.map((r) => {
        const pct = (r.value / m) * 100;
        const trackPct = r.track != null ? (r.track / m) * 100 : null;
        return (
          <div
            key={r.key}
            role="listitem"
            className={cx("relative flex items-center gap-3 rounded-md px-1 py-1", hover === r.key && "bg-slate-50 dark:bg-white/[0.04]")}
            onMouseEnter={() => setHover(r.key)}
            onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(r.key)}
            onBlur={() => setHover(null)}
            tabIndex={0}
            aria-label={`${typeof r.label === "string" ? r.label : r.key}: ${r.valueLabel}`}
          >
            <div className={cx("shrink-0 truncate text-xs text-slate-600 dark:text-slate-300", labelWidth)}>{r.label}</div>
            <div className="relative h-4 flex-1">
              {trackPct != null && <div className="absolute inset-y-0 left-0 rounded-r opacity-25" style={{ width: `${trackPct}%`, background: r.color }} />}
              <div className="absolute inset-y-0 left-0 rounded-r" style={{ width: `${Math.max(pct, r.value > 0 ? 0.8 : 0)}%`, background: r.color }} />
            </div>
            <div className="w-20 shrink-0 text-right text-xs font-medium text-slate-700 dark:text-slate-200 tabular">{r.valueLabel}</div>
            {hover === r.key && (
              <div className="pointer-events-none absolute left-1/3 top-full z-20 mt-1 min-w-[12rem]">
                <Tip title={r.label} rows={r.tip} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DataTable({ columns, rows }: { columns: string[]; rows: ReactNode[][] }) {
  return (
    <div className="relative overflow-x-auto scrollbar-thin">
      <table className="w-full min-w-[420px]">
        <thead className="border-b border-slate-200 dark:border-white/10">
          <tr>
            {columns.map((c, i) => (
              <th key={c} className={cx("th", i > 0 && "text-right")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-slate-100 dark:border-white/5">
              {r.map((c, j) => (
                <td key={j} className={cx("td", j > 0 && "text-right tabular")}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LegendItem({ color, label, faint }: { color: string; label: string; faint?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
      <span className={cx("h-2.5 w-2.5 rounded-sm", faint && "opacity-25")} style={{ background: color }} />
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function Impact() {
  const { data, error, loading } = useApi<ImpactData>("/api/analytics/impact");
  const [tables, setTables] = useState(false);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;

  const pr = data.per_recruiter_week;
  const m7 = data.measured_last_7d;
  const cats = [...CATEGORIES, ...Object.keys(data.by_category).filter((c) => !CATEGORIES.includes(c))];
  const catColor = (c: string) => CATEGORY_STYLE[c]?.bar || "var(--series-5)";
  const catData = cats.map((c) => ({ category: c, ...(data.by_category[c] || { count: 0, minutes_saved: 0, baseline: 0 }) }));
  const stageRows = Object.entries(data.by_stage);
  const maxWf = Math.max(1, ...m7.workflows.map((w) => w.minutes));
  const maxTop = Math.max(1, ...data.top_tasks.map((t) => t.minutes));

  return (
    <div className="space-y-5 print:space-y-4">
      <PageHeader
        title="Automation Impact report"
        subtitle={`Where recruiter time goes today, and how much of it the platform gives back. ${data.task_count} playbook tasks, ${data.team_week.recruiters} active recruiter${data.team_week.recruiters === 1 ? "" : "s"}.`}
        actions={
          <div className="flex items-center gap-3 print:hidden">
            <Toggle checked={tables} onChange={setTables} label={<span className="text-slate-600 dark:text-slate-300">Table view</span>} />
            <Button icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>
              Print
            </Button>
          </div>
        }
      />

      {/* Hero */}
      <section className="card overflow-hidden">
        <div className="grid divide-y divide-slate-200 dark:divide-white/10 md:grid-cols-4 md:divide-x md:divide-y-0">
          <div className="px-5 py-5 md:col-span-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
              <Clock className="h-3.5 w-3.5" /> Hours saved per recruiter, per week
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-5xl font-semibold tracking-tight text-slate-900 dark:text-white tabular">{fmt(pr.hours_saved, 1)}</span>
              <span className="text-lg text-slate-500">hours</span>
            </div>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              A {fmt(pr.baseline_hours, 1)}-hour weekly task load becomes {fmt(pr.after_hours, 1)} hours. That time goes back into conversations with candidates.
            </p>
          </div>
          <div className="px-5 py-5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
              <TrendingDown className="h-3.5 w-3.5" /> Reduction in manual task time
            </div>
            <div className="mt-1 text-3xl font-semibold text-slate-900 dark:text-white tabular">{fmt(pr.percent_reduction, 1)}%</div>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Estimated from the Task Map</p>
          </div>
          <div className="px-5 py-5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
              <Users className="h-3.5 w-3.5" /> Team hours saved per week
            </div>
            <div className="mt-1 text-3xl font-semibold text-slate-900 dark:text-white tabular">{fmt(data.team_week.hours_saved, 1)}</div>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Across {data.team_week.recruiters} recruiter{data.team_week.recruiters === 1 ? "" : "s"} · {fmt(m7.hours_saved_team, 1)} h measured last 7 days
            </p>
          </div>
        </div>
      </section>

      {/* Before vs after */}
      <Card title="A recruiter's week: before and after" subtitle="Hours of recurring playbook tasks per recruiter per week">
        {tables ? (
          <DataTable
            columns={["Scenario", "Hours / week"]}
            rows={[
              ["Before (baseline)", fmt(pr.baseline_hours, 1)],
              ["After automation", fmt(pr.after_hours, 1)],
              ["Saved", fmt(pr.hours_saved, 1)],
            ]}
          />
        ) : (
          <div className="space-y-2">
            <HBars
              max={pr.baseline_hours}
              labelWidth="w-28 sm:w-36"
              rows={[
                {
                  key: "before",
                  label: "Before (baseline)",
                  value: pr.baseline_hours,
                  color: "var(--series-1)",
                  valueLabel: `${fmt(pr.baseline_hours, 1)} h`,
                  tip: [{ label: "Manual task time", value: `${fmt(pr.baseline_hours, 1)} h / week` }],
                },
                {
                  key: "after",
                  label: "After automation",
                  value: pr.after_hours,
                  track: pr.baseline_hours,
                  color: "var(--series-1)",
                  valueLabel: `${fmt(pr.after_hours, 1)} h`,
                  tip: [
                    { label: "Remaining task time", value: `${fmt(pr.after_hours, 1)} h / week` },
                    { label: "Saved", value: `${fmt(pr.hours_saved, 1)} h (${fmt(pr.percent_reduction, 1)}%)` },
                  ],
                },
              ]}
            />
            <p className="pl-1 text-xs text-slate-500 dark:text-slate-400">
              The faint segment on the “after” bar is the {fmt(pr.hours_saved, 1)} hours the platform takes off the recruiter's plate.
            </p>
          </div>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Task counts by category */}
        <Card title="Tasks by category" subtitle="Number of playbook tasks in each category">
          {tables ? (
            <DataTable columns={["Category", "Tasks"]} rows={catData.map((c) => [<CategoryBadge key={c.category} category={c.category} />, c.count])} />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={catData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }} barCategoryGap="30%">
                  <CartesianGrid vertical={false} stroke="var(--grid)" />
                  <XAxis dataKey="category" tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} axisLine={{ stroke: "var(--axis)" }} interval={0} />
                  <YAxis allowDecimals={false} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} axisLine={false} />
                  <Tooltip
                    cursor={{ fill: "var(--grid)", opacity: 0.4 }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <Tip
                          title={payload[0].payload.category}
                          rows={[
                            { label: "Tasks", value: payload[0].payload.count, swatch: catColor(payload[0].payload.category) },
                            { label: "Saved", value: `${fmt(payload[0].payload.minutes_saved)} min / wk` },
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={48} isAnimationActive={false}>
                    {catData.map((c) => (
                      <Cell key={c.category} fill={catColor(c.category)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        {/* Minutes saved by category */}
        <Card
          title="Minutes saved by category"
          subtitle="Per recruiter per week, against each category's baseline workload"
          actions={
            !tables && (
              <div className="hidden flex-wrap gap-3 sm:flex">
                <LegendItem color="var(--text-muted)" label="Saved" />
                <LegendItem color="var(--text-muted)" label="Baseline" faint />
              </div>
            )
          }
        >
          {tables ? (
            <DataTable
              columns={["Category", "Baseline min", "Saved min", "% saved"]}
              rows={catData.map((c) => [
                <CategoryBadge key={c.category} category={c.category} />,
                fmt(c.baseline),
                fmt(c.minutes_saved),
                c.baseline ? `${fmt((100 * c.minutes_saved) / c.baseline)}%` : "—",
              ])}
            />
          ) : (
            <>
              <div className="mb-2 flex flex-wrap gap-3 sm:hidden">
                <LegendItem color="var(--text-muted)" label="Saved" />
                <LegendItem color="var(--text-muted)" label="Baseline" faint />
              </div>
              <HBars
                labelWidth="w-24 sm:w-28"
                rows={catData.map((c) => ({
                  key: c.category,
                  label: c.category,
                  value: c.minutes_saved,
                  track: c.baseline,
                  color: catColor(c.category),
                  valueLabel: `${fmt(c.minutes_saved)} min`,
                  tip: [
                    { label: "Saved", value: `${fmt(c.minutes_saved)} min / wk`, swatch: catColor(c.category) },
                    { label: "Baseline", value: `${fmt(c.baseline)} min / wk` },
                    { label: "Share saved", value: c.baseline ? `${fmt((100 * c.minutes_saved) / c.baseline)}%` : "—" },
                  ],
                }))}
              />
              <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                Keep Human tasks save little by design: the system supports those conversations rather than replacing them.
              </p>
            </>
          )}
        </Card>
      </div>

      {/* By stage */}
      <Card title="Minutes saved by playbook stage" subtitle="Per recruiter per week">
        {tables ? (
          <DataTable
            columns={["Stage", "Tasks", "Baseline min", "Saved min"]}
            rows={stageRows.map(([s, b]) => [s, b.count, fmt(b.baseline), fmt(b.minutes_saved)])}
          />
        ) : (
          <HBars
            rows={stageRows.map(([s, b]) => ({
              key: s,
              label: s,
              value: b.minutes_saved,
              color: "var(--series-1)",
              valueLabel: `${fmt(b.minutes_saved)} min`,
              tip: [
                { label: "Saved", value: `${fmt(b.minutes_saved)} min / wk` },
                { label: "Baseline", value: `${fmt(b.baseline)} min / wk` },
                { label: "Tasks", value: b.count },
              ],
            }))}
          />
        )}
      </Card>

      {/* Measured */}
      <Card
        title="Measured in the last 7 days"
        subtitle="Completed workflow runs × minutes saved per run"
        actions={
          <Link to="/workflows" className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-200 print:hidden">
            Workflow Builder →
          </Link>
        }
      >
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-slate-200 px-3 py-2 dark:border-white/10">
            <div className="text-xs text-slate-500 dark:text-slate-400">Team hours saved</div>
            <div className="text-xl font-semibold text-slate-900 dark:text-white tabular">{fmt(m7.hours_saved_team, 1)}</div>
          </div>
          <div className="rounded-lg border border-slate-200 px-3 py-2 dark:border-white/10">
            <div className="text-xs text-slate-500 dark:text-slate-400">Per recruiter</div>
            <div className="text-xl font-semibold text-slate-900 dark:text-white tabular">{fmt(m7.hours_saved_per_recruiter, 1)} h</div>
          </div>
          <div className="col-span-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-white/10 sm:col-span-1">
            <div className="text-xs text-slate-500 dark:text-slate-400">Completed runs</div>
            <div className="text-xl font-semibold text-slate-900 dark:text-white tabular">{fmt(m7.workflows.reduce((a, w) => a + w.runs, 0))}</div>
          </div>
        </div>
        {m7.workflows.length === 0 ? (
          <Empty icon={<Activity className="h-8 w-8" />} title="No completed workflow runs in the last 7 days" />
        ) : (
          <div className="relative -mx-4 overflow-x-auto scrollbar-thin">
            <table className="w-full min-w-[560px]">
              <thead className="border-y border-slate-200 dark:border-white/10">
                <tr>
                  <th className="th pl-4">Workflow</th>
                  <th className="th text-right">Runs</th>
                  <th className="th text-right">Minutes saved</th>
                  <th className="th w-40 pr-4">
                    <span className="sr-only">Share</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {m7.workflows.map((w) => (
                  <tr key={w.name} className="border-b border-slate-100 dark:border-white/5">
                    <td className="td pl-4 text-slate-800 dark:text-slate-100">{w.name}</td>
                    <td className="td text-right tabular">{fmt(w.runs)}</td>
                    <td className="td text-right tabular">
                      {fmt(w.minutes)} <span className="text-xs text-slate-500">({fmt(w.minutes / 60, 1)} h)</span>
                    </td>
                    <td className="td pr-4 align-middle" title={`${fmt(w.minutes)} minutes`}>
                      <div className="h-2 w-full">
                        <div className="h-2 rounded-r" style={{ width: `${(w.minutes / maxWf) * 100}%`, background: "var(--series-1)" }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Top tasks */}
      <Card title="Top tasks by time saved" subtitle="Estimated minutes saved per recruiter per week" actions={<Link to="/tasks" className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-200 print:hidden">Task Map →</Link>}>
        <div className="relative -mx-4 overflow-x-auto scrollbar-thin">
          <table className="w-full min-w-[620px]">
            <thead className="border-y border-slate-200 dark:border-white/10">
              <tr>
                <th className="th pl-4">ID</th>
                <th className="th">Task</th>
                <th className="th">Category</th>
                <th className="th text-right">Min / wk</th>
                <th className="th w-36 pr-4">
                  <span className="sr-only">Share</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.top_tasks.map((t) => (
                <tr key={t.id} className="border-b border-slate-100 dark:border-white/5">
                  <td className="td pl-4 font-mono text-xs text-slate-500">{t.id}</td>
                  <td className="td text-slate-800 dark:text-slate-100">{t.task_name}</td>
                  <td className="td">
                    <CategoryBadge category={t.category} />
                  </td>
                  <td className="td text-right font-medium tabular">{fmt(t.minutes)}</td>
                  <td className="td pr-4 align-middle" title={`${t.minutes} minutes per week`}>
                    <div className="h-2 w-full">
                      <div className="h-2 rounded-r" style={{ width: `${(t.minutes / maxTop) * 100}%`, background: catColor(t.category) }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Methodology */}
      <section className="card flex gap-3 px-4 py-4">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        <div className="space-y-1.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">Methodology</p>
          <p>
            <strong className="font-semibold">Estimates</strong> come from the <Link to="/tasks" className="text-brand-700 hover:underline dark:text-brand-200">Task Map</Link>: each task
            carries a baseline (manual minutes per recruiter per week) and an estimated minutes saved. Totals are the sums across all {data.task_count} tasks; team figures multiply by
            the number of active recruiters. TA leads can edit these estimates, and this report updates immediately.
          </p>
          <p>
            <strong className="font-semibold">Measured</strong> figures count completed workflow runs in the last 7 days, multiplied by each workflow's minutes saved per run. They cover
            event-driven and scheduled automations only. Built-in one-click features and drafts are not counted, so measured savings typically run below the estimate.
          </p>
        </div>
      </section>
    </div>
  );
}
