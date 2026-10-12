import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, Info, Lock, Megaphone, Plus, ShieldAlert, TicketCheck, UserCheck } from "lucide-react";
import { ApiError, errMsg, patch, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime, humanize, relTime } from "../lib/format";
import { useApi, useInterval } from "../lib/hooks";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Tabs, cx, useToast } from "../components/ui";

const TEAM_ROLES = ["payroll", "immigration", "onboarding", "marketing", "coordinator"];
const POST_EDITORS = ["marketing", "recruiter", "ta_lead"];
const TEAM_TONE: Record<string, string> = { payroll: "blue", immigration: "violet", onboarding: "green", marketing: "amber", coordinator: "gray" };
const STATUS_TABS = [
  { key: "open", label: "Open", param: "open,in_progress" },
  { key: "resolved", label: "Resolved", param: "resolved" },
  { key: "all", label: "All", param: "all" },
];

type TeamCount = { open: number; breached: number; label: string; sla_hours: number };
type Ticket = {
  id: number;
  team: string;
  team_label: string;
  kind: string;
  subject: string;
  description: string;
  candidate_id: number | null;
  candidate_name: string | null;
  requested_by_name: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  status: string;
  sla_hours: number;
  due_at: string;
  breached: boolean;
  resolution: string;
  created_at: string;
  resolved_at: string | null;
  seconds_to_due: number | null;
};

/** Countdown text with seconds, e.g. "5h 04m 12s" or "1d 3h 12m". */
function countdown(sec: number) {
  const s = Math.abs(Math.round(sec));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (d > 0) return `${d}d ${h}h ${pad(m)}m`;
  return `${h}h ${pad(m)}m ${pad(ss)}s`;
}

function slaState(t: Ticket, remaining: number | null): "resolved" | "overdue" | "soon" | "ok" {
  if (t.status === "resolved" || remaining == null) return "resolved";
  if (remaining < 0 || t.breached) return "overdue";
  if (remaining < t.sla_hours * 3600 * 0.25) return "soon";
  return "ok";
}

function SlaTimer({ t, remaining }: { t: Ticket; remaining: number | null }) {
  const st = slaState(t, remaining);
  if (st === "resolved") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
        <CheckCircle2 className="h-3.5 w-3.5" /> Resolved {t.resolved_at ? relTime(t.resolved_at) : ""}
      </span>
    );
  }
  const cls =
    st === "overdue"
      ? "text-red-700 dark:text-red-300"
      : st === "soon"
        ? "text-amber-700 dark:text-amber-300"
        : "text-slate-700 dark:text-slate-200";
  const Icon = st === "overdue" ? AlertTriangle : Clock;
  const r = remaining ?? 0;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-medium tabular whitespace-nowrap", cls)} title={`Due ${fmtDateTime(t.due_at)} · SLA ${t.sla_hours}h`}>
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {st === "overdue" ? (
        <span>
          Overdue{r < 0 ? ` by ${countdown(r)}` : ""}
        </span>
      ) : (
        <span>
          {countdown(r)} left{st === "soon" && <span className="ml-1 font-semibold">· Due soon</span>}
        </span>
      )}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "resolved") return <Badge tone="green"><CheckCircle2 className="h-3 w-3" />Resolved</Badge>;
  if (status === "in_progress") return <Badge tone="blue"><Clock className="h-3 w-3" />In progress</Badge>;
  return <Badge tone="gray">Open</Badge>;
}

export default function Delegation() {
  const { user } = useAuth();
  const toast = useToast();
  const myTeam = user && TEAM_ROLES.includes(user.role) ? user.role : null;
  const [tab, setTab] = useState("open");
  const [team, setTeam] = useState("");
  const statusParam = STATUS_TABS.find((s) => s.key === tab)!.param;
  const path = `/api/tickets?status=${encodeURIComponent(statusParam)}${team && !myTeam ? `&team=${team}` : ""}`;
  const { data, error, loading, reload } = useApi<{ items: Ticket[]; teams: Record<string, TeamCount> }>(path);

  // Live SLA timers: remaining = seconds_to_due at fetch time minus elapsed seconds.
  const [fetchedAt, setFetchedAt] = useState(Date.now());
  const [nowMs, setNowMs] = useState(Date.now());
  useEffect(() => {
    if (data) setFetchedAt(Date.now());
  }, [data]);
  const tick = useCallback(() => setNowMs(Date.now()), []);
  useInterval(tick, 1000);
  const remainingOf = (t: Ticket) => (t.seconds_to_due == null ? null : t.seconds_to_due - (nowMs - fetchedAt) / 1000);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = data?.items.find((t) => t.id === selectedId) || null;
  const [showNew, setShowNew] = useState(false);

  const teams = data?.teams || {};
  const teamKeys = Object.keys(teams);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Delegation Center"
        subtitle={myTeam ? `Requests routed to ${teams[myTeam]?.label || humanize(myTeam)}` : "Route specialist questions to the right team, with SLA tracking"}
        actions={
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setShowNew(true)}>
            New ticket
          </Button>
        }
      />

      <div className="flex items-start gap-2 rounded-lg border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
        <Info className="h-4 w-4 shrink-0 mt-0.5 text-slate-400" />
        <span>
          Payroll, tax and immigration questions are always routed here and answered by the authorized team — recruiters never answer them directly. Candidates receive an acknowledgment when a ticket is opened.
        </span>
      </div>

      {/* Team tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
        {teamKeys.length === 0 && loading && <div className="col-span-full"><Loading /></div>}
        {teamKeys.map((k) => {
          const t = teams[k];
          const active = team === k || myTeam === k;
          const canFilter = !myTeam;
          return (
            <button
              key={k}
              type="button"
              disabled={!canFilter}
              onClick={() => canFilter && setTeam(team === k ? "" : k)}
              className={cx("card px-4 py-3 text-left transition-colors", canFilter && "hover:border-brand-300 dark:hover:border-brand-400/50", active && "ring-2 ring-brand-400/60")}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400 truncate">{t.label}</span>
                <span className="text-[11px] text-slate-400 tabular shrink-0">SLA {t.sla_hours}h</span>
              </div>
              <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white tabular">{t.open}</div>
              <div className="text-xs mt-0.5">
                {t.breached > 0 ? (
                  <span className="inline-flex items-center gap-1 text-red-700 dark:text-red-300">
                    <AlertTriangle className="h-3 w-3" /> {t.breached} breached
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-slate-500 dark:text-slate-400">
                    <CheckCircle2 className="h-3 w-3" /> None breached
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      <Card bodyClass="px-0 pb-0 pt-0">
        <div className="flex flex-wrap items-end justify-between gap-3 px-4 pt-3">
          <div className="flex-1 min-w-[220px]">
            <Tabs tabs={STATUS_TABS.map((s) => ({ key: s.key, label: s.label, count: s.key === tab ? data?.items.length : undefined }))} value={tab} onChange={setTab} />
          </div>
          {!myTeam && (
            <select className="input w-auto mb-2" value={team} onChange={(e) => setTeam(e.target.value)} aria-label="Filter by team">
              <option value="">All teams</option>
              {teamKeys.map((k) => (
                <option key={k} value={k}>
                  {teams[k].label}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="px-4 py-3">
          <ErrorBox error={error} />
        </div>
        {loading && !data ? (
          <Loading />
        ) : data && data.items.length === 0 ? (
          <Empty icon={<TicketCheck className="h-8 w-8" />} title={tab === "open" ? "No open tickets" : "No tickets"}>
            {tab === "open" ? "Everything routed to the team has been handled." : "Nothing matches this filter."}
          </Empty>
        ) : (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full min-w-[860px]">
              <thead className="border-y border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.03]">
                <tr>
                  <th className="th">Team</th>
                  <th className="th">Subject</th>
                  <th className="th">Candidate</th>
                  <th className="th">Requested by</th>
                  <th className="th">Created</th>
                  <th className="th">SLA</th>
                  <th className="th">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {data?.items.map((t) => (
                  <tr key={t.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-white/5" onClick={() => setSelectedId(t.id)}>
                    <td className="td">
                      <Badge tone={TEAM_TONE[t.team]}>{t.team_label}</Badge>
                    </td>
                    <td className="td">
                      <div className="font-medium text-slate-800 dark:text-slate-100">{t.subject}</div>
                      {t.assignee_name && <div className="text-xs text-slate-500">Assigned to {t.assignee_name}</div>}
                    </td>
                    <td className="td">
                      {t.candidate_id ? (
                        <Link to={`/candidates/${t.candidate_id}`} onClick={(e) => e.stopPropagation()} className="text-brand-700 dark:text-brand-200 hover:underline">
                          {t.candidate_name || `#${t.candidate_id}`}
                        </Link>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="td text-slate-600 dark:text-slate-300">{t.requested_by_name || "System"}</td>
                    <td className="td text-slate-600 dark:text-slate-300 whitespace-nowrap" title={fmtDateTime(t.created_at)}>
                      {relTime(t.created_at)}
                    </td>
                    <td className="td">
                      <SlaTimer t={t} remaining={remainingOf(t)} />
                    </td>
                    <td className="td">
                      <StatusBadge status={t.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <PostsSection onChanged={reload} />

      {selected && (
        <TicketDrawer
          ticket={selected}
          remaining={remainingOf(selected)}
          onClose={() => setSelectedId(null)}
          onSaved={(msg) => {
            toast("success", msg);
            reload();
          }}
        />
      )}
      <NewTicketModal
        open={showNew}
        teams={teams}
        defaultTeam={myTeam || ""}
        onClose={() => setShowNew(false)}
        onCreated={() => {
          setShowNew(false);
          toast("success", "Ticket created and routed");
          reload();
        }}
      />
    </div>
  );
}

function TicketDrawer({ ticket: t, remaining, onClose, onSaved }: { ticket: Ticket; remaining: number | null; onClose: () => void; onSaved: (msg: string) => void }) {
  const { user } = useAuth();
  const [resolution, setResolution] = useState(t.resolution || "");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const resolved = t.status === "resolved";

  async function run(key: string, body: any, msg: string) {
    setBusy(key);
    setErr(null);
    try {
      await patch(`/api/tickets/${t.id}`, body);
      onSaved(msg);
      if (key === "resolve") onClose();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal open onClose={onClose} wide title={<span className="flex items-center gap-2">Ticket #{t.id}</span>}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={TEAM_TONE[t.team]}>{t.team_label}</Badge>
          <StatusBadge status={t.status} />
          <Badge>{humanize(t.kind)}</Badge>
          <SlaTimer t={t} remaining={remaining} />
        </div>
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">{t.subject}</h3>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div>
            <dt className="label">Candidate</dt>
            <dd>
              {t.candidate_id ? (
                <Link to={`/candidates/${t.candidate_id}`} className="text-brand-700 dark:text-brand-200 hover:underline">
                  {t.candidate_name || `#${t.candidate_id}`}
                </Link>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div>
            <dt className="label">Requested by</dt>
            <dd>{t.requested_by_name || "System"}</dd>
          </div>
          <div>
            <dt className="label">Assignee</dt>
            <dd>{t.assignee_name || <span className="text-slate-400">Unassigned</span>}</dd>
          </div>
          <div>
            <dt className="label">Due</dt>
            <dd className="tabular">{fmtDateTime(t.due_at)}</dd>
          </div>
        </dl>
        <div>
          <div className="label">Description</div>
          <p className="whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-200 rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2">{t.description || "No description provided."}</p>
        </div>
        <ErrorBox error={err} />
        {resolved ? (
          <div>
            <div className="label">Resolution</div>
            <p className="whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-200">{t.resolution}</p>
            <p className="text-xs text-slate-500 mt-1">Resolved {fmtDateTime(t.resolved_at)}</p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {user && t.assignee_id !== user.id && (
                <Button icon={<UserCheck className="h-4 w-4" />} loading={busy === "assign"} onClick={() => run("assign", { assignee_id: user.id }, "Assigned to you")}>
                  Assign to me
                </Button>
              )}
              {t.status === "open" && (
                <Button icon={<Clock className="h-4 w-4" />} loading={busy === "progress"} onClick={() => run("progress", { status: "in_progress" }, "Marked in progress")}>
                  Mark in progress
                </Button>
              )}
            </div>
            <Field label="Resolution note (required to resolve)" hint="Visible to the requesting recruiter. Keep it factual; the authorized team communicates specifics to the candidate.">
              <textarea className="input min-h-[90px]" value={resolution} onChange={(e) => setResolution(e.target.value)} placeholder="What was done / answered…" />
            </Field>
            <div className="flex justify-end">
              <Button
                variant="success"
                icon={<CheckCircle2 className="h-4 w-4" />}
                disabled={!resolution.trim()}
                loading={busy === "resolve"}
                onClick={() => run("resolve", { status: "resolved", resolution: resolution.trim() }, "Ticket resolved")}
              >
                Resolve
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

function NewTicketModal({ open, teams, defaultTeam, onClose, onCreated }: { open: boolean; teams: Record<string, TeamCount>; defaultTeam: string; onClose: () => void; onCreated: () => void }) {
  const [team, setTeam] = useState(defaultTeam);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTeam(defaultTeam || Object.keys(teams)[0] || "");
      setSubject("");
      setDescription("");
      setErr(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await post("/api/tickets", { team, subject: subject.trim(), description: description.trim() });
      onCreated();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New ticket"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!team || !subject.trim()} onClick={submit}>
            Create ticket
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Team" hint={team && teams[team] ? `SLA: ${teams[team].sla_hours} hours` : undefined}>
          <select className="input" value={team} onChange={(e) => setTeam(e.target.value)}>
            {Object.entries(teams).map(([k, t]) => (
              <option key={k} value={k}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Subject">
          <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Payroll schedule question for a W-2 consultant" />
        </Field>
        <Field label="Description">
          <textarea className="input min-h-[110px]" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Context the team needs. Don't include document images or SSNs." />
        </Field>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Recruitment posts with checklist gate
// ---------------------------------------------------------------------------
type Hit = { category: string; severity: string; match: string };
type Post = {
  id: number;
  title: string;
  body: string;
  channel: string;
  status: string;
  checklist: Record<string, boolean>;
  published_at: string | null;
  created_at: string;
};

const POST_STATUS_TONE: Record<string, string> = { requested: "gray", in_review: "amber", approved: "blue", published: "green" };

function HitList({ hits }: { hits: Hit[] }) {
  if (!hits.length) return null;
  return (
    <ul className="mt-1 space-y-1">
      {hits.map((h, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2 text-xs">
          {h.severity === "block" ? (
            <Badge tone="red">
              <ShieldAlert className="h-3 w-3" />
              Block
            </Badge>
          ) : (
            <Badge tone="amber">
              <AlertTriangle className="h-3 w-3" />
              Review
            </Badge>
          )}
          <span className="text-slate-600 dark:text-slate-300">{humanize(h.category)}:</span>
          <code className="rounded bg-slate-100 dark:bg-white/10 px-1">“{h.match}”</code>
        </li>
      ))}
    </ul>
  );
}

function PostsSection({ onChanged }: { onChanged: () => void }) {
  const { user } = useAuth();
  const { data, error, loading, setData } = useApi<{ items: Post[]; checklist: Record<string, string> }>("/api/posts");
  const canEdit = !!user && POST_EDITORS.includes(user.role);

  if (loading && !data) return <Card title="Recruitment posts"><Loading /></Card>;
  return (
    <section className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Megaphone className="h-4 w-4 text-slate-400" /> Recruitment posts
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">Every post passes the checklist gate before it can be published.</p>
        </div>
        {!canEdit && (
          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
            <Lock className="h-3.5 w-3.5" /> View only
          </span>
        )}
      </div>
      <ErrorBox error={error} />
      {data && data.items.length === 0 && (
        <Card>
          <Empty icon={<Megaphone className="h-8 w-8" />} title="No recruitment posts">
            Post requests created from a requirement appear here for review.
          </Empty>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.items.map((p) => (
          <PostCard
            key={p.id}
            post={p}
            checklist={data.checklist}
            canEdit={canEdit}
            onUpdated={(np) => {
              setData({ ...data, items: data.items.map((x) => (x.id === np.id ? { ...x, ...np } : x)) });
              if (np.status === "published") onChanged();
            }}
          />
        ))}
      </div>
    </section>
  );
}

function PostCard({ post: p, checklist, canEdit, onUpdated }: { post: Post; checklist: Record<string, string>; canEdit: boolean; onUpdated: (p: Post) => void }) {
  const toast = useToast();
  const [hits, setHits] = useState<Hit[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const published = p.status === "published";
  const keys = Object.keys(checklist);
  const allChecked = keys.every((k) => p.checklist?.[k]);
  const doneCount = keys.filter((k) => p.checklist?.[k]).length;

  async function save(body: any, key: string) {
    setBusy(key);
    setErr(null);
    setMissing([]);
    try {
      const r = await patch<Post & { compliance: { hits: Hit[] } }>(`/api/posts/${p.id}`, body);
      setHits(r.compliance?.hits || []);
      const { compliance, ...rest } = r;
      onUpdated(rest);
      if (body.status === "published") toast("success", `Published on ${p.channel}`);
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === "object") {
        setErr(e.detail.message || errMsg(e));
        if (Array.isArray(e.detail.hits)) setHits(e.detail.hits);
        if (Array.isArray(e.detail.missing)) setMissing(e.detail.missing);
      } else setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card
      title={p.title}
      subtitle={
        <span className="flex flex-wrap items-center gap-2 mt-1">
          <Badge tone="brand">{p.channel}</Badge>
          <Badge tone={POST_STATUS_TONE[p.status]}>{humanize(p.status)}</Badge>
          <span>{published ? `Published ${fmtDateTime(p.published_at)}` : `Requested ${relTime(p.created_at)}`}</span>
        </span>
      }
    >
      <p className="whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-200 rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2">{p.body}</p>
      <div className="mt-3">
        <div className="flex items-center justify-between">
          <span className="label mb-0">Publishing checklist</span>
          <span className="text-xs text-slate-500 tabular">
            {doneCount}/{keys.length}
          </span>
        </div>
        <ul className="mt-1.5 space-y-1.5">
          {keys.map((k) => (
            <li key={k}>
              <label className={cx("flex items-start gap-2 text-sm", canEdit && !published ? "cursor-pointer" : "opacity-80", missing.includes(k) && "text-red-700 dark:text-red-300")}>
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-brand-700"
                  checked={!!p.checklist?.[k]}
                  disabled={!canEdit || published || busy === "check"}
                  onChange={(e) => save({ checklist: { ...(p.checklist || {}), [k]: e.target.checked } }, "check")}
                />
                <span className="text-slate-700 dark:text-slate-200">{checklist[k]}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
      {hits.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-200 dark:border-amber-400/30 bg-amber-50/60 dark:bg-amber-500/10 px-3 py-2">
          <div className="text-xs font-medium text-amber-900 dark:text-amber-200 flex items-center gap-1">
            <AlertTriangle className="h-3.5 w-3.5" /> Compliance scan found {hits.length} phrase{hits.length > 1 ? "s" : ""} to check
          </div>
          <HitList hits={hits} />
        </div>
      )}
      {err && (
        <div className="mt-3">
          <ErrorBox error={err + (missing.length ? ` — ${missing.map((m) => checklist[m] || m).join("; ")}` : "")} />
        </div>
      )}
      {!published && canEdit && (
        <div className="mt-3 flex items-center justify-end gap-2">
          {!allChecked && <span className="text-xs text-slate-500">Complete every checklist item to publish</span>}
          <Button variant="primary" disabled={!allChecked} loading={busy === "publish"} onClick={() => save({ status: "published" }, "publish")}>
            Publish
          </Button>
        </div>
      )}
    </Card>
  );
}
