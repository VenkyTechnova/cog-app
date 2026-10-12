import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, Gauge, Table2 } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../lib/auth";
import { fmtDate } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Card, ErrorBox, Loading, PageHeader, ProgressBar, Stat, cx } from "../components/ui";

// ---------------------------------------------------------------------------
// Chart helpers (shared look: recessive grid, muted ticks, text in ink tokens)
// ---------------------------------------------------------------------------
const TICK = { fill: "var(--text-muted)", fontSize: 11 };
const fmtNum = (n: number) => (Number.isFinite(n) ? n.toLocaleString() : "—");
const pct = (n: number) => `${Math.round(n * 1000) / 10}%`;

function ChartTooltip({ active, payload, label, labelFormatter }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-[#1a1a19] px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-[color:var(--text-primary)] mb-1">{labelFormatter ? labelFormatter(label) : label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-[color:var(--text-secondary)]">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color || p.fill || p.stroke }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 font-medium tabular text-[color:var(--text-primary)]">{fmtNum(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function LegendContent({ payload }: any) {
  return (
    <div className="flex flex-wrap justify-center gap-4 pt-2 text-xs text-[color:var(--text-secondary)]">
      {payload?.map((p: any) => (
        <span key={p.value} className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded-full" style={{ background: p.color, height: 2 }} />
          {p.value}
        </span>
      ))}
    </div>
  );
}

/** A card holding a chart with a Chart / Table toggle. */
function ChartCard({ title, subtitle, chart, columns, rows, className }: { title: string; subtitle?: ReactNode; chart: ReactNode; columns: string[]; rows: (string | number)[][]; className?: string }) {
  const [table, setTable] = useState(false);
  return (
    <Card
      className={className}
      title={title}
      subtitle={subtitle}
      actions={
        <button
          type="button"
          onClick={() => setTable(!table)}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10"
          aria-pressed={table}
        >
          {table ? <BarChart3 className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
          {table ? "Chart" : "Table"}
        </button>
      }
    >
      {table ? (
        <div className="max-h-72 overflow-auto scrollbar-thin rounded-lg border border-slate-200 dark:border-white/10">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-50 dark:bg-[#222220]">
              <tr>
                {columns.map((c, i) => (
                  <th key={c} className={cx("th", i > 0 && "text-right")}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-white/5">
              {rows.map((r, i) => (
                <tr key={i}>
                  {r.map((v, j) => (
                    <td key={j} className={cx("td py-1.5", j > 0 && "text-right tabular")}>
                      {typeof v === "number" ? fmtNum(v) : v}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        chart
      )}
    </Card>
  );
}

function Section({ title, children, subtitle }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h2>
        {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

const DAILY_SERIES = [
  { key: "calls", name: "Calls", color: "var(--series-1)" },
  { key: "emails", name: "Emails", color: "var(--series-2)" },
  { key: "linkedin", name: "LinkedIn", color: "var(--series-3)" },
];

const QUALITY = [
  { key: "meaningful_conversations", label: "Meaningful conversations" },
  { key: "interested", label: "Interested" },
  { key: "qualified", label: "Qualified" },
  { key: "documents_received", label: "Documents received" },
  { key: "onboarded", label: "Onboarded" },
];

const DQ_METRICS: { key: string; label: string; better: "higher" | "lower"; extra?: (m: any) => string }[] = [
  { key: "accuracy", label: "Record accuracy", better: "higher" },
  { key: "duplicate_rate", label: "Duplicate rate", better: "lower", extra: (m) => `${m.open_duplicates} open duplicate pair${m.open_duplicates === 1 ? "" : "s"}` },
  { key: "stale_rate", label: "Stale active records", better: "lower", extra: (m) => `${m.stale_records} with no activity in 30+ days` },
  { key: "follow_up_compliance", label: "Follow-up compliance (7 days)", better: "higher" },
  { key: "document_completeness", label: "Document completeness", better: "higher" },
];

export default function Analytics() {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const [uid, setUid] = useState<string>("");
  const { data: users } = useApi<any[]>("/api/users");
  const recruiters = useMemo(() => (users || []).filter((u) => u.role === "recruiter"), [users]);
  const { data, error, loading } = useApi<any>(`/api/analytics/overview?days=${days}${uid ? `&user_id=${uid}` : ""}`);

  const shortDate = (d: string) => fmtDate(d + "T12:00:00");

  return (
    <div className="space-y-8">
      <PageHeader title="Analytics" subtitle="Activity, quality, pipeline health and data quality across the team" />

      {/* Filters: one row above all charts */}
      <div className="flex flex-wrap items-center gap-3 -mt-2">
        <div className="inline-flex rounded-lg border border-slate-300 dark:border-white/15 p-0.5 bg-white dark:bg-white/5" role="group" aria-label="Date range">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={cx("px-3 py-1.5 text-sm rounded-md tabular", days === d ? "bg-brand-800 text-white dark:bg-brand-500" : "text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/10")}
            >
              {d} days
            </button>
          ))}
        </div>
        <select className="input w-auto" value={uid} onChange={(e) => setUid(e.target.value)} aria-label="Recruiter">
          <option value="">All recruiters</option>
          {recruiters.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
              {user?.id === r.id ? " (me)" : ""}
            </option>
          ))}
        </select>
        {loading && data && <span className="text-xs text-slate-500">Updating…</span>}
      </div>

      <ErrorBox error={error} />
      {!data ? (
        loading ? <Loading /> : null
      ) : (
        <AnalyticsBody data={data} shortDate={shortDate} filtered={!!uid} />
      )}
    </div>
  );
}

function AnalyticsBody({ data, shortDate, filtered }: { data: any; shortDate: (d: string) => string; filtered: boolean }) {
  const a = data.activity;
  const q = data.quality;
  const p = data.pipeline;
  const dq = data.data_quality;
  const ee = data.email_engagement;
  const stageRows = Object.keys(p.by_stage).map((k) => ({ key: k, label: p.labels[k] || k, value: p.by_stage[k] }));
  const qualityRows = QUALITY.map((x) => ({ ...x, value: q[x.key] ?? 0 }));
  const dqTrend = data.dq_trend as { date: string; score: number }[];

  return (
    <>
      <Section title="Activity" subtitle={`Last ${data.days} days`}>
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
          <Stat label="Calls" value={<span className="tabular">{fmtNum(a.calls)}</span>} />
          <Stat label="LinkedIn connections" value={<span className="tabular">{fmtNum(a.linkedin_connections)}</span>} />
          <Stat label="LinkedIn messages" value={<span className="tabular">{fmtNum(a.linkedin_messages)}</span>} />
          <Stat label="Emails sent" value={<span className="tabular">{fmtNum(a.emails_sent)}</span>} />
          <Stat label="Profiles added" value={<span className="tabular">{fmtNum(a.profiles_added)}</span>} />
          <Stat label="Unique contacts" value={<span className="tabular">{fmtNum(a.unique_contacts)}</span>} />
        </div>
        <ChartCard
          title="Daily activity"
          subtitle="Calls, candidate emails and LinkedIn touches per day"
          columns={["Date", "Calls", "Emails", "LinkedIn"]}
          rows={data.daily.map((d: any) => [shortDate(d.date), d.calls, d.emails, d.linkedin])}
          chart={
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.daily} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={shortDate} tick={TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={24} />
                  <YAxis allowDecimals={false} tick={TICK} tickLine={false} axisLine={false} />
                  <Tooltip content={<ChartTooltip labelFormatter={shortDate} />} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} />
                  <Legend content={<LegendContent />} />
                  {DAILY_SERIES.map((s) => (
                    <Line key={s.key} type="linear" dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)" }} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          }
        />
      </Section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="Quality" subtitle="Candidates reaching each milestone in the period">
          <ChartCard
            title="Conversation-to-onboarding funnel"
            columns={["Milestone", "Count"]}
            rows={qualityRows.map((r) => [r.label, r.value])}
            chart={
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={qualityRows} layout="vertical" margin={{ top: 4, right: 36, left: 0, bottom: 0 }} barCategoryGap={6}>
                    <CartesianGrid stroke="var(--grid)" horizontal={false} />
                    <XAxis type="number" allowDecimals={false} tick={TICK} tickLine={false} axisLine={false} />
                    <YAxis type="category" dataKey="label" width={170} tick={TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
                    <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--grid)", opacity: 0.4 }} />
                    <Bar dataKey="value" name="Candidates" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={28}>
                      <LabelList dataKey="value" position="right" fill="var(--text-secondary)" fontSize={11} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            }
          />
        </Section>

        <Section title="Email engagement" subtitle="Candidate emails sent in the period">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Sent" value={<span className="tabular">{fmtNum(ee.sent)}</span>} />
            <Stat label="Opened" value={<span className="tabular">{fmtNum(ee.opened)}</span>} sub={ee.sent ? `${pct(ee.opened / ee.sent)} open rate` : "—"} />
            <Stat label="Clicked" value={<span className="tabular">{fmtNum(ee.clicked)}</span>} sub={ee.sent ? `${pct(ee.clicked / ee.sent)} click rate` : "—"} />
          </div>
          {filtered && <p className="text-[11px] text-slate-500">Email engagement is shown for the whole team.</p>}
          <Link to="/impact" className="card flex items-center gap-3 px-4 py-4 hover:border-brand-300 dark:hover:border-brand-400/50 transition-colors group">
            <span className="rounded-lg bg-brand-50 dark:bg-brand-500/15 p-2 text-brand-700 dark:text-brand-200">
              <Gauge className="h-5 w-5" />
            </span>
            <span className="flex-1 min-w-0">
              <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">Automation impact</span>
              <span className="block text-xs text-slate-500 dark:text-slate-400">Estimated and measured hours saved per recruiter, by category and workflow</span>
            </span>
            <ArrowRight className="h-4 w-4 text-slate-400 group-hover:translate-x-0.5 transition-transform" />
          </Link>
        </Section>
      </div>

      <Section title="Pipeline" subtitle="Current candidates by stage">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Active" value={<span className="tabular">{fmtNum(p.active)}</span>} />
          <Stat label="In follow-up" value={<span className="tabular">{fmtNum(p.in_follow_up)}</span>} />
          <Stat label="Client interviews" value={<span className="tabular">{fmtNum(p.interviews)}</span>} />
          <Stat label="Placements" value={<span className="tabular">{fmtNum(p.placements)}</span>} />
        </div>
        <ChartCard
          title="Candidates by stage"
          columns={["Stage", "Candidates"]}
          rows={stageRows.map((r) => [r.label, r.value])}
          chart={
            <div className="h-[380px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stageRows} layout="vertical" margin={{ top: 4, right: 36, left: 0, bottom: 0 }} barCategoryGap={4}>
                  <CartesianGrid stroke="var(--grid)" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={TICK} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="label" width={190} tick={TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} interval={0} />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--grid)", opacity: 0.4 }} />
                  <Bar dataKey="value" name="Candidates" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={22}>
                    <LabelList dataKey="value" position="right" fill="var(--text-secondary)" fontSize={11} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          }
        />
      </Section>

      <Section title="Data quality" subtitle="Team-wide database health (not filtered by recruiter)">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Data quality score">
            <div className="flex items-baseline gap-1">
              <span className="text-5xl font-semibold tracking-tight text-slate-900 dark:text-white tabular">{Math.round(dq.score)}</span>
              <span className="text-lg text-slate-400">/100</span>
            </div>
            {dqTrend.length > 1 && (
              <p className="text-xs text-slate-500 mt-1">
                {(() => {
                  const delta = dq.score - dqTrend[0].score;
                  return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} since ${shortDate(dqTrend[0].date)}`;
                })()}
              </p>
            )}
            <div className="mt-4 space-y-3">
              {DQ_METRICS.map((m) => {
                const v = dq.metrics[m.key] ?? 0;
                return (
                  <div key={m.key}>
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-600 dark:text-slate-300">{m.label}</span>
                      <span className="font-medium tabular text-slate-800 dark:text-slate-100">{pct(v)}</span>
                    </div>
                    <div className="mt-1">
                      <ProgressBar value={v * 100} />
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">
                      {m.better === "lower" ? "Lower is better" : "Higher is better"}
                      {m.extra ? ` · ${m.extra(dq.metrics)}` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
          <ChartCard
            className="lg:col-span-2"
            title="Score trend"
            subtitle="Daily snapshot, last 30 days"
            columns={["Date", "Score"]}
            rows={dqTrend.map((d) => [shortDate(d.date), d.score])}
            chart={
              dqTrend.length === 0 ? (
                <p className="py-12 text-center text-sm text-slate-500">No snapshots yet — the first one is taken by the nightly job.</p>
              ) : (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={dqTrend} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                      <CartesianGrid stroke="var(--grid)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={shortDate} tick={TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={24} />
                      <YAxis
                        tick={TICK}
                        tickLine={false}
                        axisLine={false}
                        domain={[(min: number) => Math.max(0, Math.floor(min - 5)), (max: number) => Math.min(100, Math.ceil(max + 5))]}
                      />
                      <Tooltip content={<ChartTooltip labelFormatter={shortDate} />} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} />
                      <Line type="linear" dataKey="score" name="Score" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)" }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )
            }
          />
        </div>
      </Section>

      <Section title="By recruiter" subtitle={`Last ${data.days} days, active recruiters`}>
        <Card bodyClass="px-0 pb-0 pt-0">
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full min-w-[980px]">
              <thead className="border-b border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.03]">
                <tr>
                  <th className="th">Recruiter</th>
                  {["Calls", "LI conn.", "LI msgs", "Emails", "Profiles", "Contacts", "Meaningful", "Interested", "Qualified", "Docs rec'd", "Onboarded"].map((h) => (
                    <th key={h} className="th text-right">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {data.by_recruiter.map((r: any) => (
                  <tr key={r.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
                    <td className="td font-medium text-slate-800 dark:text-slate-100 whitespace-nowrap">{r.name}</td>
                    {["calls", "linkedin_connections", "linkedin_messages", "emails_sent", "profiles_added", "unique_contacts", "meaningful_conversations", "interested", "qualified", "documents_received", "onboarded"].map((k) => (
                      <td key={k} className="td text-right tabular">
                        {fmtNum(r[k] ?? 0)}
                      </td>
                    ))}
                  </tr>
                ))}
                {data.by_recruiter.length === 0 && (
                  <tr>
                    <td className="td text-center text-slate-500" colSpan={12}>
                      No active recruiters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>
    </>
  );
}
