import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, FileLock2, Flag, GraduationCap, History, MinusCircle, ShieldAlert, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { errMsg, post } from "../lib/api";
import { isManager, useAuth } from "../lib/auth";
import { fmtDate, fmtDateTime, humanize, relTime, STAGE_LABELS } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, StageBadge, Tabs, cx, useToast } from "../components/ui";

const ALL_TABS = [
  { key: "consent", label: "Consent log", managerOnly: false },
  { key: "flags", label: "Flagged keywords", managerOnly: true },
  { key: "habits", label: "Habits review", managerOnly: false },
  { key: "retention", label: "Data retention", managerOnly: true },
  { key: "audit", label: "Access & audit log", managerOnly: true },
];

function CandLink({ id, name }: { id?: number | null; name?: string | null }) {
  if (!id) return <span className="text-slate-400">—</span>;
  return (
    <Link to={`/candidates/${id}`} className="text-brand-700 dark:text-brand-200 hover:underline">
      {name || `#${id}`}
    </Link>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  if (severity === "block")
    return (
      <Badge tone="red">
        <ShieldAlert className="h-3 w-3" />
        Block
      </Badge>
    );
  return (
    <Badge tone="amber">
      <AlertTriangle className="h-3 w-3" />
      Review
    </Badge>
  );
}

function ReviewStatus({ status }: { status: string }) {
  const map: Record<string, [string, JSX.Element, string]> = {
    open: ["gray", <Clock className="h-3 w-3" />, "Open"],
    reviewed: ["green", <CheckCircle2 className="h-3 w-3" />, "Reviewed"],
    coached: ["green", <GraduationCap className="h-3 w-3" />, "Coached"],
    dismissed: ["gray", <MinusCircle className="h-3 w-3" />, "Dismissed"],
  };
  const [tone, icon, label] = map[status] || ["gray", null, humanize(status)];
  return (
    <Badge tone={tone}>
      {icon}
      {label}
    </Badge>
  );
}

function StatusFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-300 dark:border-white/15 p-0.5 bg-white dark:bg-white/5">
      {[
        ["open", "Open"],
        ["all", "All"],
      ].map(([k, l]) => (
        <button key={k} type="button" onClick={() => onChange(k)} className={cx("px-3 py-1 text-xs rounded-md", value === k ? "bg-brand-800 text-white dark:bg-brand-500" : "text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/10")}>
          {l}
        </button>
      ))}
    </div>
  );
}

function TableCard({ children, minWidth = 760, actions, title, subtitle }: { children: ReactNode; minWidth?: number; actions?: ReactNode; title?: string; subtitle?: string }) {
  return (
    <Card title={title} subtitle={subtitle} actions={actions} bodyClass="px-0 pb-0 pt-0">
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full" style={{ minWidth }}>
          {children}
        </table>
      </div>
    </Card>
  );
}

const THEAD = "border-y border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.03]";
const TBODY = "divide-y divide-slate-100 dark:divide-white/5";

export default function Compliance() {
  const { user } = useAuth();
  const manager = isManager(user);
  const allowed = user?.role === "recruiter" || manager;
  const tabs = ALL_TABS.filter((t) => manager || !t.managerOnly);
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab = tabs.find((t) => t.key === requested)?.key || (manager ? "consent" : "habits");
  const ordered = manager ? tabs : [...tabs].sort((a, b) => (a.key === "habits" ? -1 : b.key === "habits" ? 1 : 0));

  if (!allowed) {
    return (
      <div>
        <PageHeader title="Compliance & Audit" />
        <Card>
          <Empty icon={<ShieldCheck className="h-8 w-8" />} title="Not available for your role">
            Compliance review is handled by TA leads and administrators.
          </Empty>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Compliance & Audit"
        subtitle={manager ? "Consent, advice-keyword flags, coaching, retention and access history" : "Your coaching items and the candidate consent log"}
      />
      <Tabs tabs={ordered.map((t) => ({ key: t.key, label: manager || t.key !== "habits" ? t.label : "My coaching" }))} value={tab} onChange={(k) => setParams({ tab: k }, { replace: true })} />
      {tab === "consent" && <ConsentTab />}
      {tab === "flags" && manager && <FlagsTab />}
      {tab === "habits" && <HabitsTab manager={manager} />}
      {tab === "retention" && manager && <RetentionTab />}
      {tab === "audit" && manager && <AuditTab />}
    </div>
  );
}

// ---------------------------------------------------------------------------
function ConsentStatus({ status }: { status: string }) {
  if (status === "granted") return <Badge tone="green"><CheckCircle2 className="h-3 w-3" />Granted</Badge>;
  if (status === "declined") return <Badge tone="gray"><MinusCircle className="h-3 w-3" />Declined</Badge>;
  if (status === "revoked") return <Badge tone="red"><XCircle className="h-3 w-3" />Revoked</Badge>;
  return <Badge tone="amber"><Clock className="h-3 w-3" />Pending</Badge>;
}

function ConsentTab() {
  const { data, error, loading } = useApi<any[]>("/api/compliance/consent");
  const [status, setStatus] = useState("");
  const rows = (data || []).filter((r) => !status || r.status === status);
  if (loading && !data) return <Loading />;
  return (
    <div className="space-y-3">
      <ErrorBox error={error} />
      <TableCard
        title="E-consent records"
        subtitle="Every consent is captured with timestamp, IP and text version. Tokens and full text are never shown here."
        actions={
          <select className="input w-auto py-1 text-xs" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="granted">Granted</option>
            <option value="declined">Declined</option>
            <option value="revoked">Revoked</option>
          </select>
        }
      >
        <thead className={THEAD}>
          <tr>
            <th className="th">Candidate</th>
            <th className="th">Type</th>
            <th className="th">Status</th>
            <th className="th">Method</th>
            <th className="th">Requested</th>
            <th className="th">Recorded</th>
            <th className="th">IP</th>
            <th className="th">Version</th>
          </tr>
        </thead>
        <tbody className={TBODY}>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="td">
                <CandLink id={r.candidate_id} name={r.candidate_name} />
              </td>
              <td className="td">{humanize(r.consent_type)}</td>
              <td className="td">
                <ConsentStatus status={r.status} />
              </td>
              <td className="td text-slate-600 dark:text-slate-300">{r.method}</td>
              <td className="td whitespace-nowrap tabular">{fmtDateTime(r.requested_at)}</td>
              <td className="td whitespace-nowrap tabular">{fmtDateTime(r.recorded_at)}</td>
              <td className="td font-mono text-xs text-slate-500">{r.ip || "—"}</td>
              <td className="td text-xs text-slate-500">{r.text_version}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8}>
                <Empty icon={<FileLock2 className="h-8 w-8" />} title="No consent records" />
              </td>
            </tr>
          )}
        </tbody>
      </TableCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
function ReviewModal({
  open,
  title,
  context,
  actions,
  onClose,
  onSubmit,
  noteLabel,
}: {
  open: boolean;
  title: string;
  context: ReactNode;
  actions: { status: string; label: string; variant: "primary" | "secondary" | "success" }[];
  noteLabel: string;
  onClose: () => void;
  onSubmit: (status: string, note: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setNote("");
      setErr(null);
    }
  }, [open]);
  async function go(status: string) {
    setBusy(status);
    setErr(null);
    try {
      await onSubmit(status, note.trim());
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {actions.map((a) => (
            <Button key={a.status} variant={a.variant} loading={busy === a.status} disabled={!!busy} onClick={() => go(a.status)}>
              {a.label}
            </Button>
          ))}
        </>
      }
    >
      <div className="space-y-3">
        {context}
        <Field label={noteLabel}>
          <textarea className="input min-h-[100px]" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function FlagsTab() {
  const toast = useToast();
  const [status, setStatus] = useState("open");
  const { data, error, loading, reload } = useApi<any[]>(`/api/compliance/flags?status=${status}`);
  const [sel, setSel] = useState<any | null>(null);
  return (
    <div className="space-y-3">
      <ErrorBox error={error} />
      <TableCard
        title="Advice-keyword flags"
        subtitle="Pay, tax, immigration and pressure language detected in notes, drafts, emails and posts. Block = sending was stopped; Review = check the context."
        actions={<StatusFilter value={status} onChange={setStatus} />}
        minWidth={900}
      >
        <thead className={THEAD}>
          <tr>
            <th className="th">When</th>
            <th className="th">Severity</th>
            <th className="th">Category</th>
            <th className="th">Matched text</th>
            <th className="th">Source</th>
            <th className="th">Recruiter</th>
            <th className="th">Candidate</th>
            <th className="th">Status</th>
            <th className="th" />
          </tr>
        </thead>
        <tbody className={TBODY}>
          {loading && !data && (
            <tr>
              <td colSpan={9}>
                <Loading />
              </td>
            </tr>
          )}
          {data?.map((f) => (
            <tr key={f.id}>
              <td className="td whitespace-nowrap text-slate-600 dark:text-slate-300" title={fmtDateTime(f.created_at)}>
                {relTime(f.created_at)}
              </td>
              <td className="td">
                <SeverityBadge severity={f.severity} />
              </td>
              <td className="td">{humanize(f.category)}</td>
              <td className="td">
                <code className="rounded bg-slate-100 dark:bg-white/10 px-1.5 py-0.5 text-xs">“{f.matched_text}”</code>
              </td>
              <td className="td text-slate-600 dark:text-slate-300">{humanize(f.source_type)}</td>
              <td className="td">{f.user_name || "—"}</td>
              <td className="td">
                <CandLink id={f.candidate_id} name={f.candidate_name} />
              </td>
              <td className="td">
                <ReviewStatus status={f.status} />
              </td>
              <td className="td text-right">
                {f.status === "open" && (
                  <Button size="sm" onClick={() => setSel(f)}>
                    Review
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {data && data.length === 0 && (
            <tr>
              <td colSpan={9}>
                <Empty icon={<Flag className="h-8 w-8" />} title={status === "open" ? "No open flags" : "No flags"}>
                  Flags appear when a message contains advice-type phrases.
                </Empty>
              </td>
            </tr>
          )}
        </tbody>
      </TableCard>
      <ReviewModal
        open={!!sel}
        title="Review flag"
        noteLabel="Review note (recorded in the audit log)"
        context={
          sel && (
            <div className="rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2 text-sm space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={sel.severity} />
                <span>{humanize(sel.category)}</span>
                <span className="text-slate-500">· {humanize(sel.source_type)} by {sel.user_name || "unknown"}</span>
              </div>
              <code className="text-xs">“{sel.matched_text}”</code>
            </div>
          )
        }
        actions={[
          { status: "dismissed", label: "Dismiss", variant: "secondary" },
          { status: "reviewed", label: "Mark reviewed", variant: "primary" },
        ]}
        onClose={() => setSel(null)}
        onSubmit={async (st, note) => {
          await post(`/api/compliance/flags/${sel.id}`, { status: st, note });
          toast("success", st === "reviewed" ? "Flag marked reviewed" : "Flag dismissed");
          setSel(null);
          reload();
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
function HabitsTab({ manager }: { manager: boolean }) {
  const toast = useToast();
  const [status, setStatus] = useState("open");
  const { data, error, loading, reload } = useApi<{ items: any[]; habits: Record<string, string>; by_recruiter: Record<string, Record<string, number>> }>(`/api/compliance/habits?status=${status}`);
  const [sel, setSel] = useState<any | null>(null);

  const heat = useMemo(() => {
    if (!data) return null;
    const people = Object.keys(data.by_recruiter).sort();
    const habitKeys = Object.keys(data.habits).filter((h) => people.some((p) => data.by_recruiter[p][h]));
    const max = Math.max(1, ...people.flatMap((p) => Object.values(data.by_recruiter[p])));
    return { people, habitKeys, max };
  }, [data]);

  if (loading && !data) return <Loading />;
  return (
    <div className="space-y-4">
      <ErrorBox error={error} />
      {manager && heat && (
        <Card title="Open items by recruiter" subtitle="Darker cells mean more open items for that habit. Use it to plan coaching, not to rank people.">
          {heat.people.length === 0 ? (
            <Empty icon={<GraduationCap className="h-8 w-8" />} title="No open habit flags" />
          ) : (
            <div className="overflow-x-auto scrollbar-thin -mx-4 px-4">
              <table className="border-separate" style={{ borderSpacing: 2 }}>
                <thead>
                  <tr>
                    <th className="th pl-0">Recruiter</th>
                    {heat.habitKeys.map((h) => (
                      <th key={h} className="px-1 pb-2 align-bottom text-[11px] font-medium text-slate-500 dark:text-slate-400 max-w-[96px]" title={data!.habits[h]}>
                        <span className="block leading-tight">{humanize(h)}</span>
                      </th>
                    ))}
                    <th className="th text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {heat.people.map((p) => {
                    const row = data!.by_recruiter[p];
                    const total = Object.values(row).reduce((a, b) => a + b, 0);
                    return (
                      <tr key={p}>
                        <td className="pr-3 py-1 text-sm font-medium whitespace-nowrap text-slate-700 dark:text-slate-200">{p}</td>
                        {heat.habitKeys.map((h) => {
                          const n = row[h] || 0;
                          const strength = n ? 25 + Math.round((n / heat.max) * 75) : 0;
                          return (
                            <td
                              key={h}
                              title={`${p} · ${data!.habits[h]}: ${n} open`}
                              className={cx("h-9 min-w-[64px] rounded text-center text-xs tabular font-medium", n ? (strength > 60 ? "text-white" : "text-slate-800 dark:text-white") : "text-slate-300 dark:text-slate-600 bg-slate-50 dark:bg-white/[0.03]")}
                              style={n ? { background: `color-mix(in srgb, var(--seq-450) ${strength}%, transparent)` } : undefined}
                            >
                              {n || "·"}
                            </td>
                          );
                        })}
                        <td className="pl-3 text-right text-sm tabular font-semibold">{total}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <TableCard
        title={manager ? "Review queue" : "My coaching items"}
        subtitle={manager ? "Detected automatically from activity. Coach with a short, specific note." : "Items the system noticed in your recent activity, with notes from your TA lead."}
        actions={<StatusFilter value={status} onChange={setStatus} />}
        minWidth={820}
      >
        <thead className={THEAD}>
          <tr>
            <th className="th">Habit</th>
            {manager && <th className="th">Recruiter</th>}
            <th className="th">Candidate</th>
            <th className="th">Detail</th>
            <th className="th">Detected</th>
            <th className="th">Status</th>
            <th className="th" />
          </tr>
        </thead>
        <tbody className={TBODY}>
          {data?.items.map((h) => (
            <tr key={h.id}>
              <td className="td">
                <div className="font-medium text-slate-800 dark:text-slate-100">{humanize(h.habit)}</div>
                <div className="text-xs text-slate-500">{h.label}</div>
              </td>
              {manager && <td className="td whitespace-nowrap">{h.user_name || "—"}</td>}
              <td className="td">
                <CandLink id={h.candidate_id} name={h.candidate_name} />
              </td>
              <td className="td text-slate-600 dark:text-slate-300">
                {h.detail}
                {h.coaching_note && (
                  <div className="mt-1 rounded bg-brand-50 dark:bg-brand-500/10 px-2 py-1 text-xs text-brand-900 dark:text-brand-100">
                    <GraduationCap className="inline h-3 w-3 mr-1" />
                    {h.coaching_note}
                  </div>
                )}
              </td>
              <td className="td whitespace-nowrap text-slate-600 dark:text-slate-300" title={fmtDateTime(h.created_at)}>
                {relTime(h.created_at)}
              </td>
              <td className="td">
                <ReviewStatus status={h.status} />
              </td>
              <td className="td text-right">
                {manager && h.status === "open" && (
                  <Button size="sm" icon={<GraduationCap className="h-3.5 w-3.5" />} onClick={() => setSel(h)}>
                    Coach
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {data && data.items.length === 0 && (
            <tr>
              <td colSpan={7}>
                <Empty icon={<GraduationCap className="h-8 w-8" />} title={status === "open" ? "Nothing open" : "No items"}>
                  {manager ? "No habit flags need review." : "No coaching items — nice work."}
                </Empty>
              </td>
            </tr>
          )}
        </tbody>
      </TableCard>

      <ReviewModal
        open={!!sel}
        title="Coaching note"
        noteLabel="Coaching note (visible to the recruiter)"
        context={
          sel && (
            <div className="rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2 text-sm">
              <div className="font-medium">
                {humanize(sel.habit)} · {sel.user_name}
              </div>
              <div className="text-xs text-slate-500">{sel.label}</div>
              <div className="text-xs text-slate-600 dark:text-slate-300 mt-1">{sel.detail}</div>
            </div>
          )
        }
        actions={[
          { status: "dismissed", label: "Dismiss", variant: "secondary" },
          { status: "coached", label: "Mark coached", variant: "primary" },
        ]}
        onClose={() => setSel(null)}
        onSubmit={async (st, note) => {
          await post(`/api/compliance/habits/${sel.id}`, { status: st, note });
          toast("success", st === "coached" ? "Coaching recorded" : "Item dismissed");
          setSel(null);
          reload();
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
function RetentionTab() {
  const toast = useToast();
  const { data, error, loading, reload } = useApi<{ due: any[]; upcoming: any[] }>("/api/compliance/retention");
  const [extendC, setExtendC] = useState<any | null>(null);
  const [purgeC, setPurgeC] = useState<any | null>(null);
  const [days, setDays] = useState(365);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function openExtend(c: any) {
    setExtendC(c);
    setDays(365);
    setReason("");
    setErr(null);
  }
  function openPurge(c: any) {
    setPurgeC(c);
    setAck(false);
    setErr(null);
  }
  async function doExtend() {
    setBusy(true);
    setErr(null);
    try {
      await post(`/api/compliance/retention/${extendC.id}/extend`, { days, reason: reason.trim() });
      toast("success", `Retention extended by ${days} days`);
      setExtendC(null);
      reload();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }
  async function doPurge() {
    setBusy(true);
    setErr(null);
    try {
      await post(`/api/compliance/retention/${purgeC.id}/purge`);
      toast("success", "Personal data purged");
      setPurgeC(null);
      reload();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  const rowsFor = (list: any[], due: boolean) =>
    list.map((c) => (
      <tr key={c.id}>
        <td className="td">
          <CandLink id={c.id} name={c.full_name} />
        </td>
        <td className="td">
          <StageBadge stage={c.stage} />
        </td>
        <td className="td whitespace-nowrap tabular">{fmtDate(c.last_contact_at, { month: "short", day: "numeric", year: "numeric" })}</td>
        <td className="td whitespace-nowrap tabular">
          {due ? (
            <span className="inline-flex items-center gap-1 text-red-700 dark:text-red-300">
              <AlertTriangle className="h-3.5 w-3.5" /> Expired {fmtDate(c.retention_expires_at, { month: "short", day: "numeric", year: "numeric" })}
            </span>
          ) : (
            fmtDate(c.retention_expires_at, { month: "short", day: "numeric", year: "numeric" })
          )}
        </td>
        <td className="td text-right whitespace-nowrap">
          <div className="inline-flex gap-2">
            <Button size="sm" icon={<History className="h-3.5 w-3.5" />} onClick={() => openExtend(c)}>
              Extend
            </Button>
            {due && (
              <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => openPurge(c)}>
                Purge
              </Button>
            )}
          </div>
        </td>
      </tr>
    ));

  const head = (
    <thead className={THEAD}>
      <tr>
        <th className="th">Candidate</th>
        <th className="th">Stage</th>
        <th className="th">Last contact</th>
        <th className="th">Retention expires</th>
        <th className="th" />
      </tr>
    </thead>
  );

  if (loading && !data) return <Loading />;
  return (
    <div className="space-y-4">
      <ErrorBox error={error} />
      <TableCard title="Due for review" subtitle="Records past their retention date. Extend with a documented reason, or purge personal data (aggregate metrics are kept)." minWidth={680}>
        {head}
        <tbody className={TBODY}>
          {rowsFor(data?.due || [], true)}
          {data && data.due.length === 0 && (
            <tr>
              <td colSpan={5}>
                <Empty icon={<ShieldCheck className="h-8 w-8" />} title="Nothing due">
                  No records are past their retention date.
                </Empty>
              </td>
            </tr>
          )}
        </tbody>
      </TableCard>
      <TableCard title="Coming up" subtitle="The next 20 records to reach their retention date." minWidth={680}>
        {head}
        <tbody className={TBODY}>{rowsFor(data?.upcoming || [], false)}</tbody>
      </TableCard>

      <Modal
        open={!!extendC}
        onClose={() => setExtendC(null)}
        title={`Extend retention — ${extendC?.full_name || ""}`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setExtendC(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} disabled={!reason.trim() || days < 1} onClick={doExtend}>
              Extend
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Extend by (days from today)">
            <input type="number" min={1} className="input" value={days} onChange={(e) => setDays(Number(e.target.value))} />
          </Field>
          <Field label="Reason (required, recorded in the audit log)">
            <textarea className="input min-h-[80px]" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Candidate re-engaged and asked us to keep their profile on file" />
          </Field>
          <ErrorBox error={err} />
        </div>
      </Modal>

      <Modal
        open={!!purgeC}
        onClose={() => setPurgeC(null)}
        title="Purge personal data"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPurgeC(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} disabled={!ack} onClick={doPurge} icon={<Trash2 className="h-4 w-4" />}>
              Purge permanently
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm">
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-800 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-200">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>
              This is <strong>irreversible</strong>. {purgeC?.full_name}'s contact details, résumé, notes and message bodies will be anonymised and all stored documents deleted. Only aggregate metrics are kept.
            </span>
          </div>
          <p className="text-slate-600 dark:text-slate-300">
            Stage: {STAGE_LABELS[purgeC?.stage] || purgeC?.stage} · Last contact {fmtDate(purgeC?.last_contact_at)}
          </p>
          <label className="flex items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-red-600" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            I understand this cannot be undone.
          </label>
          <ErrorBox error={err} />
        </div>
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
function AuditTab() {
  const [action, setAction] = useState("");
  const [debounced, setDebounced] = useState("");
  const [entity, setEntity] = useState("");
  const [uid, setUid] = useState("");
  const { data: users } = useApi<any[]>("/api/users");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(action.trim()), 350);
    return () => clearTimeout(t);
  }, [action]);
  const qs = new URLSearchParams({ limit: "300" });
  if (debounced) qs.set("action", debounced);
  if (entity) qs.set("entity_type", entity);
  if (uid) qs.set("user_id", uid);
  const { data, error, loading } = useApi<any[]>(`/api/compliance/audit?${qs.toString()}`);
  const [entityTypes, setEntityTypes] = useState<string[]>([]);
  useEffect(() => {
    if (data) setEntityTypes((prev) => Array.from(new Set([...prev, ...data.map((a) => a.entity_type)])).sort());
  }, [data]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Action prefix">
          <input className="input w-56" value={action} onChange={(e) => setAction(e.target.value)} placeholder="e.g. candidate. or document." />
        </Field>
        <Field label="Entity type">
          <select className="input w-44" value={entity} onChange={(e) => setEntity(e.target.value)}>
            <option value="">All</option>
            {Array.from(new Set([...entityTypes, entity].filter(Boolean))).map((t) => (
              <option key={t} value={t}>
                {humanize(t)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="User">
          <select className="input w-48" value={uid} onChange={(e) => setUid(e.target.value)}>
            <option value="">Anyone</option>
            {(users || []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </Field>
        {(action || entity || uid) && (
          <Button
            variant="ghost"
            onClick={() => {
              setAction("");
              setEntity("");
              setUid("");
            }}
          >
            Clear
          </Button>
        )}
      </div>
      <ErrorBox error={error} />
      <TableCard minWidth={900}>
        <thead className={THEAD}>
          <tr>
            <th className="th">When</th>
            <th className="th">User</th>
            <th className="th">Action</th>
            <th className="th">Entity</th>
            <th className="th">Detail</th>
            <th className="th">IP</th>
          </tr>
        </thead>
        <tbody className={TBODY}>
          {loading && !data && (
            <tr>
              <td colSpan={6}>
                <Loading />
              </td>
            </tr>
          )}
          {data?.map((a) => {
            const detail = a.detail && Object.keys(a.detail).length ? JSON.stringify(a.detail) : "";
            return (
              <tr key={a.id}>
                <td className="td whitespace-nowrap tabular text-slate-600 dark:text-slate-300">{fmtDateTime(a.at)}</td>
                <td className="td whitespace-nowrap">{a.user_name || <span className="text-slate-400">System / public</span>}</td>
                <td className="td">
                  <code className="text-xs rounded bg-slate-100 dark:bg-white/10 px-1.5 py-0.5">{a.action}</code>
                </td>
                <td className="td whitespace-nowrap text-slate-600 dark:text-slate-300">
                  {a.entity_type === "candidate" && a.entity_id ? (
                    <CandLink id={Number(a.entity_id)} name={`Candidate #${a.entity_id}`} />
                  ) : (
                    <>
                      {humanize(a.entity_type)}
                      {a.entity_id ? ` #${a.entity_id}` : ""}
                    </>
                  )}
                </td>
                <td className="td max-w-[360px]">
                  <span className="block truncate font-mono text-[11px] text-slate-500" title={detail}>
                    {detail || "—"}
                  </span>
                </td>
                <td className="td font-mono text-xs text-slate-500">{a.ip || "—"}</td>
              </tr>
            );
          })}
          {data && data.length === 0 && (
            <tr>
              <td colSpan={6}>
                <Empty icon={<History className="h-8 w-8" />} title="No matching events" />
              </td>
            </tr>
          )}
        </tbody>
      </TableCard>
      {data && data.length >= 300 && <p className="text-xs text-slate-500">Showing the 300 most recent events. Narrow the filters to see older ones.</p>}
    </div>
  );
}
