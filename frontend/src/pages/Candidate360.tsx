import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRightLeft,
  BellPlus,
  Check,
  CheckCircle2,
  Circle,
  Download,
  ExternalLink,
  FileText,
  Flame,
  Headphones,
  Linkedin,
  Lock,
  Mail,
  MessageSquare,
  Moon,
  Phone,
  Send,
  ShieldCheck,
  Upload,
  Sparkles,
  TicketCheck,
  XCircle,
} from "lucide-react";
import { DraftCard } from "../components/DraftCard";
import { Avatar, Badge, Button, Card, cx, Empty, ErrorBox, Field, Loading, Modal, ScoreBadge, StageBadge, Tabs, useToast } from "../components/ui";
import { api, errMsg, getToken, patch, post } from "../lib/api";
import { isStaff, useAuth } from "../lib/auth";
import { fmtDate, fmtDateTime, humanize, OUTCOMES, relTime, STAGE_LABELS, STAGE_ORDER, TEAM_LABELS } from "../lib/format";
import { useApi } from "../lib/hooks";
import { formatPhone } from "./Home";

const WORK_AUTH = ["US Citizen", "Green Card", "GC EAD", "H-1B", "H-4 EAD", "L-2 EAD", "OPT EAD", "STEM OPT EAD", "TN", "Other"];
const TYPES = ["W-2", "C2C", "Either"];
const ARRANGEMENTS = ["Remote", "Hybrid", "Onsite", "Flexible"];
const SOURCES = ["LinkedIn", "Job Posting", "Cold Call", "Cold Email", "Recruitment Post", "Referral", "Database", "Other"];

export default function Candidate360() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useApi<any>(`/api/candidates/${id}`, [id]);
  const { data: meta } = useApi<any>("/api/candidates/meta");
  const { data: users } = useApi<any[]>("/api/users");
  const [tab, setTab] = useState(params.get("tab") || "overview");
  const [modal, setModal] = useState<null | "call" | "stage" | "delegate" | "followup">(null);
  const staff = isStaff(user);

  // Deep links from the daily digest and Recruiter Home.
  useEffect(() => {
    const action = params.get("action");
    const done = params.get("done");
    if (done === "snooze") toast("success", "Snoozed until tomorrow");
    if (done === "not_fit") toast("success", "Marked not a fit for that requirement");
    if (action === "call") {
      setTab("call");
      setModal("call");
    }
    if (action === "draft" && staff) {
      const kind = params.get("kind") || "cold_email";
      const rq = params.get("requirement");
      setTab("outreach");
      post(`/api/candidates/${id}/drafts`, { kind, requirement_id: rq ? Number(rq) : null })
        .then(() => {
          toast("success", "Draft created — review it below");
          reload();
        })
        .catch((e) => toast("error", errMsg(e)));
    }
    if (action || done) {
      params.delete("action");
      params.delete("done");
      params.delete("kind");
      params.delete("requirement");
      setParams(params, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data || !meta) return <Loading />;
  const c = data.candidate;

  async function act(fn: () => Promise<any>, ok: string) {
    try {
      await fn();
      toast("success", ok);
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }

  const draftKinds = [
    ["linkedin_note", "LinkedIn connection note"],
    ["cold_email", "Cold email"],
    ["follow_up", "Follow-up"],
    ["reengagement", "Re-engagement"],
    ["offer_explainer", "Offer / documentation explainer"],
    ["check_in", "Nurture check-in"],
  ];

  return (
    <>
      {/* Header */}
      <div className="card p-4 mb-4">
        <div className="flex flex-wrap items-start gap-4">
          <Avatar name={c.full_name} size={10} />
          <div className="flex-1 min-w-[16rem]">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold">{c.full_name}</h1>
              <StageBadge stage={c.stage} />
              {c.hot_reply && (
                <Badge tone="red">
                  <Flame className="h-3 w-3" /> Hot reply
                </Badge>
              )}
              {c.email_opt_out && <Badge tone="gray">Unsubscribed</Badge>}
              {c.vendor_conflict?.conflict && (
                <Badge tone="red" title={(c.vendor_conflict.details || []).join("\n")}>
                  <AlertTriangle className="h-3 w-3" /> Vendor conflict
                </Badge>
              )}
            </div>
            <div className="text-sm text-slate-600 dark:text-slate-300 mt-0.5">{c.headline || (c.skills || []).join(", ")}</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-slate-500">
              {c.email && (
                <span className="inline-flex items-center gap-1">
                  <Mail className="h-3.5 w-3.5" /> {c.email}
                </span>
              )}
              {c.phone && (
                <span className="inline-flex items-center gap-1">
                  <Phone className="h-3.5 w-3.5" /> {formatPhone(c.phone)}
                </span>
              )}
              {c.linkedin_url && (
                <a className="inline-flex items-center gap-1 hover:underline" href={`https://${c.linkedin_url}`} target="_blank" rel="noreferrer">
                  <Linkedin className="h-3.5 w-3.5" /> LinkedIn <ExternalLink className="h-3 w-3" />
                </a>
              )}
              <span>Owner: {data.owner || "Unassigned"}</span>
              <span>Last contact: {relTime(c.last_contact_at)}</span>
              <span>Next follow-up: {c.next_follow_up_at ? fmtDateTime(c.next_follow_up_at) : "—"}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">Suggested fit</div>
            <div className="text-2xl font-semibold">{c.fit_score != null ? `${Math.round(c.fit_score)}%` : "—"}</div>
          </div>
        </div>
        {staff && (
          <div className="flex flex-wrap gap-2 mt-4">
            <Button variant="primary" icon={<Phone className="h-4 w-4" />} onClick={() => setModal("call")}>
              Log call
            </Button>
            <DraftMenu kinds={draftKinds} onPick={(k) => act(() => post(`/api/candidates/${id}/drafts`, { kind: k }), "Draft created").then(() => setTab("outreach"))} />
            <Button icon={<Send className="h-4 w-4" />} disabled={!c.email || c.email_opt_out} onClick={() => act(() => post(`/api/candidates/${id}/sequence`, {}), "Sequence drafted — approve it in Outreach").then(() => setTab("outreach"))}>
              Start email sequence
            </Button>
            <Button icon={<TicketCheck className="h-4 w-4" />} onClick={() => setModal("delegate")}>
              Delegate
            </Button>
            <Button icon={<BellPlus className="h-4 w-4" />} onClick={() => setModal("followup")}>
              Follow-up
            </Button>
            <Button icon={<Moon className="h-4 w-4" />} variant="ghost" onClick={() => act(() => post(`/api/candidates/${id}/snooze?days=1`), "Snoozed until tomorrow")}>
              Snooze
            </Button>
            <Button icon={<ArrowRightLeft className="h-4 w-4" />} variant="ghost" onClick={() => setModal("stage")}>
              Move stage
            </Button>
          </div>
        )}
      </div>

      <StageProgress stage={c.stage} gates={data.gates} transitions={data.transitions} />

      <div className="mt-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "overview", label: "Overview" },
            { key: "call", label: "Call guide" },
            { key: "qualification", label: "Qualification" },
            { key: "process", label: "Process & consent" },
            { key: "documents", label: "Documents", count: data.documents.items.length || undefined },
            { key: "offer", label: "Offer letter", count: data.offer_letters?.filter((o: any) => o.status === "pending_approval").length || undefined },
            { key: "outreach", label: "Outreach", count: data.drafts.filter((d: any) => ["pending_approval", "blocked", "manual_send"].includes(d.status)).length || undefined },
            { key: "timeline", label: "Timeline", count: data.timeline.length },
            { key: "tickets", label: "Tickets", count: data.tickets.length || undefined },
          ]}
        />
      </div>
      <div className="mt-4">
        {tab === "overview" && <Overview data={data} meta={meta} users={users || []} staff={staff} reload={reload} />}
        {tab === "call" && <CallGuide meta={meta} onLog={() => setModal("call")} staff={staff} />}
        {tab === "qualification" && <Qualification data={data} meta={meta} staff={staff} reload={reload} />}
        {tab === "process" && <ProcessConsent data={data} meta={meta} staff={staff} reload={reload} />}
        {tab === "documents" && <Documents data={data} reload={reload} />}
        {tab === "offer" && <OfferLetter data={data} reload={reload} />}
        {tab === "outreach" && <Outreach data={data} reload={reload} />}
        {tab === "timeline" && <Timeline items={data.timeline} />}
        {tab === "tickets" && <Tickets items={data.tickets} />}
      </div>

      <CallModal open={modal === "call"} onClose={() => setModal(null)} candidate={c} meta={meta} onDone={reload} calllist={params.get("calllist")} />
      <StageModal open={modal === "stage"} onClose={() => setModal(null)} candidate={c} onDone={reload} />
      <DelegateModal open={modal === "delegate"} onClose={() => setModal(null)} candidateId={c.id} onDone={reload} />
      <FollowUpModal open={modal === "followup"} onClose={() => setModal(null)} candidateId={c.id} onDone={reload} />
    </>
  );
}

// ---------------------------------------------------------------------------
function DraftMenu({ kinds, onPick }: { kinds: string[][]; onPick: (k: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <Button icon={<Sparkles className="h-4 w-4" />} onClick={() => setOpen(!open)}>
        Draft message
      </Button>
      {open && (
        <div className="absolute z-20 mt-1 w-64 card shadow-lg py-1" onMouseLeave={() => setOpen(false)}>
          {kinds.map(([k, label]) => (
            <button
              key={k}
              className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-white/5"
              onClick={() => {
                setOpen(false);
                onPick(k);
              }}
            >
              {label}
            </button>
          ))}
          <div className="px-3 py-1.5 text-[11px] text-slate-500 border-t border-slate-100 dark:border-white/5">AI drafts in the playbook tone. You approve everything.</div>
        </div>
      )}
    </div>
  );
}

function StageProgress({ stage, gates, transitions }: { stage: string; gates: any; transitions: any[] }) {
  const idx = STAGE_ORDER.indexOf(stage);
  const isOutcome = OUTCOMES.includes(stage);
  const reached = new Set(transitions.map((t) => t.to_stage));
  const steps = [...STAGE_ORDER, "outcome"];
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">Pipeline progress</h2>
        <div className="flex flex-wrap gap-2 text-xs">
          <Gate ok={gates.comfort_check_complete} label="Comfort check" />
          <Gate ok={gates.consent_granted} label="Consent" />
          <Gate ok={gates.documents_verified} label="Docs verified" />
        </div>
      </div>
      <ol className="flex items-start gap-1 overflow-x-auto scrollbar-thin pb-1">
        {steps.map((s, i) => {
          const done = s === "outcome" ? isOutcome : isOutcome ? reached.has(s) : i < idx;
          const current = s === "outcome" ? isOutcome : i === idx;
          const label = s === "outcome" ? (isOutcome ? STAGE_LABELS[stage] : "Placed / Closed / Hold") : STAGE_LABELS[s];
          const gated = ["docs_requested", "docs_received", "onboarding", "marketing_pipeline"].includes(s);
          return (
            <li key={s} className="flex-1 min-w-[84px]">
              <div className={cx("h-1.5 rounded-full", current ? "bg-brand-700 dark:bg-brand-300" : done ? "bg-brand-400/70" : "bg-slate-200 dark:bg-white/10")} />
              <div className={cx("mt-1.5 text-[11px] leading-tight flex items-center gap-1", current ? "font-semibold text-brand-800 dark:text-brand-100" : done ? "text-slate-600 dark:text-slate-300" : "text-slate-400")}>
                {gated && !gates.consent_granted && <Lock className="h-3 w-3 shrink-0" />}
                <span>
                  {i + 1}. {label}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Gate({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset", ok ? "text-[#006300] ring-emerald-200 bg-emerald-50 dark:text-[#0ca30c] dark:bg-emerald-500/10 dark:ring-emerald-400/20" : "text-slate-500 ring-slate-200 dark:ring-white/10")}>
      {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />} {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
function Overview({ data, meta, users, staff, reload }: any) {
  const c = data.candidate;
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<any>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm({ ...c, skills: (c.skills || []).join(", ") }), [c.id, c.updated_at]);

  async function save() {
    setBusy(true);
    try {
      const body: any = {};
      for (const [k] of meta.database_fields as [string, string][]) {
        if (["stage", "last_contact_at", "next_follow_up_at"].includes(k)) continue;
        if (form[k] !== c[k]) body[k] = k === "years_experience" ? (form[k] === "" ? null : Number(form[k])) : k === "owner_id" ? (form[k] ? Number(form[k]) : null) : form[k];
      }
      if (body.skills === (c.skills || []).join(", ")) delete body.skills;
      await patch(`/api/candidates/${c.id}`, body);
      toast("success", "Saved — match scores refreshed");
      setEditing(false);
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  const input = (k: string) => {
    const v = form[k] ?? "";
    const set = (val: any) => setForm({ ...form, [k]: val });
    if (k === "work_authorization") return <Select value={v} onChange={set} options={WORK_AUTH} />;
    if (k === "preferred_type") return <Select value={v} onChange={set} options={TYPES} />;
    if (k === "work_arrangement") return <Select value={v} onChange={set} options={ARRANGEMENTS} />;
    if (k === "source") return <Select value={v} onChange={set} options={SOURCES} />;
    if (k === "owner_id")
      return (
        <select className="input" value={v || ""} onChange={(e) => set(e.target.value)}>
          <option value="">Unassigned</option>
          {users.filter((u: any) => u.role === "recruiter").map((u: any) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
      );
    return <input className="input" value={v} onChange={(e) => set(e.target.value)} type={k === "years_experience" ? "number" : "text"} />;
  };

  const display = (k: string) => {
    const v = c[k];
    if (k === "stage") return <StageBadge stage={v} />;
    if (k === "owner_id") return data.owner || "Unassigned";
    if (k === "skills") return (v || []).length ? <div className="flex flex-wrap gap-1">{v.map((s: string) => <Badge key={s}>{s}</Badge>)}</div> : "—";
    if (k.endsWith("_at")) return v ? fmtDateTime(v) : "—";
    if (k === "phone" && v) return formatPhone(v);
    return v === null || v === "" || v === undefined ? <span className="text-slate-400">—</span> : String(v);
  };

  const ps = data.profile_summary;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card
        className="xl:col-span-2"
        title="Candidate record (18 fields)"
        subtitle="Kept current automatically from calls, emails, forms and uploads."
        actions={
          staff &&
          (editing ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button size="sm" variant="primary" loading={busy} onClick={save}>
                Save
              </Button>
            </>
          ) : (
            <Button size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
          ))
        }
      >
        <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
          {(meta.database_fields as [string, string][]).map(([k, label]) => (
            <div key={k}>
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-sm mt-0.5">{editing && !["stage", "last_contact_at", "next_follow_up_at"].includes(k) ? input(k) : display(k)}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <div className="space-y-4">
        <Card title="Profile summary" subtitle="Read this before reaching out.">
          <div className="text-sm font-medium">{ps.headline}</div>
          {ps.education && <div className="text-xs text-slate-500 mt-0.5">{ps.education}</div>}
          <div className="flex flex-wrap gap-1 mt-2">
            {ps.highlighted_skills.map((s: any) => (
              <Badge key={s.skill} tone={s.match ? "green" : "gray"}>
                {s.match && <Check className="h-3 w-3" />}
                {s.skill}
              </Badge>
            ))}
          </div>
          {ps.projects.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-slate-600 dark:text-slate-300 list-disc pl-4">
              {ps.projects.map((p: string, i: number) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
          <div className="mt-3 rounded-lg bg-brand-50 dark:bg-brand-500/10 px-3 py-2 text-xs">
            <span className="font-medium">Talking point:</span> {ps.talking_point}
          </div>
        </Card>
        <Card title="Matching requirements">
          {data.matches.length === 0 ? (
            <Empty title="No open requirements match yet" />
          ) : (
            <div className="space-y-2">
              {data.matches.map((m: any) => (
                <div key={m.requirement_id} className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <Link to={`/requirements/${m.requirement_id}`} className="text-sm font-medium hover:underline truncate block">
                      {m.title}
                    </Link>
                    <div className="text-[11px] text-slate-500 truncate">
                      {m.client} · ✓ {(m.breakdown?.skills?.matched || []).join(", ") || "—"}
                      {m.status === "not_fit" && " · marked not a fit"}
                    </div>
                  </div>
                  <ScoreBadge score={m.score} />
                </div>
              ))}
            </div>
          )}
        </Card>
        {data.duplicates.length > 0 && (
          <Card title="Possible duplicates">
            {data.duplicates.map((d: any) => (
              <div key={d.pair_id} className="text-sm flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <Link className="hover:underline" to={`/candidates/${d.other_id}`}>
                  Record #{d.other_id}
                </Link>
                <span className="text-xs text-slate-500">matched on {d.matched_on.join(", ")}</span>
              </div>
            ))}
            <Link to="/candidates?tab=duplicates" className="text-xs text-brand-700 dark:text-brand-200 hover:underline">
              Review in merge queue →
            </Link>
          </Card>
        )}
      </div>
    </div>
  );
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select className="input" value={value || ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">—</option>
      {options.map((o) => (
        <option key={o}>{o}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
function CallGuide({ meta, onLog, staff }: any) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<"cold" | "first">("cold");
  const list: string[] = mode === "cold" ? meta.cold_call_checkpoints : meta.first_conversation_topics;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card
        className="lg:col-span-2"
        title={mode === "cold" ? "Cold call — 10 checkpoints" : "First conversation — 11 topics"}
        subtitle="This is your conversation. The guide just makes sure nothing gets missed."
        actions={
          <div className="flex gap-1">
            <Button size="sm" variant={mode === "cold" ? "primary" : "secondary"} onClick={() => { setMode("cold"); setChecked(new Set()); }}>
              Cold call
            </Button>
            <Button size="sm" variant={mode === "first" ? "primary" : "secondary"} onClick={() => { setMode("first"); setChecked(new Set()); }}>
              First conversation
            </Button>
          </div>
        }
      >
        <div className="mb-3 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
          <Headphones className="h-4 w-4 shrink-0" /> Listen more than you talk. Ask one question at a time, and reflect back what you heard before moving on.
        </div>
        <ol className="space-y-1.5">
          {list.map((item, i) => (
            <li key={i}>
              <label className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={checked.has(i)}
                  onChange={() => {
                    const n = new Set(checked);
                    n.has(i) ? n.delete(i) : n.add(i);
                    setChecked(n);
                  }}
                />
                <span className={cx("text-sm", checked.has(i) && "line-through text-slate-400")}>
                  <span className="tabular text-slate-400 mr-1">{i + 1}.</span>
                  {item}
                </span>
              </label>
            </li>
          ))}
        </ol>
        {staff && (
          <div className="mt-3">
            <Button variant="primary" icon={<Phone className="h-4 w-4" />} onClick={onLog}>
              Log call outcome ({checked.size}/{list.length} covered)
            </Button>
          </div>
        )}
      </Card>
      <div className="space-y-4">
        <Card title="W-2 vs C2C — approved talking points" subtitle="Use these words. Don't improvise on pay or tax.">
          <ul className="space-y-2 text-sm list-disc pl-4 text-slate-700 dark:text-slate-200">
            {meta.w2_c2c_talking_points.map((t: string, i: number) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </Card>
        <Card title="Hard rules">
          <ul className="space-y-1.5 text-sm">
            {[
              "Never promise a pay date or amount.",
              "Payroll questions → Delegate to Payroll.",
              "Visa / I-983 / immigration questions → Delegate to the authorized team.",
              "No pressure. The candidate decides in their own time.",
              "Nothing is final until the process is complete.",
            ].map((r) => (
              <li key={r} className="flex items-start gap-2">
                <ShieldCheck className="h-4 w-4 text-brand-600 shrink-0 mt-0.5" /> {r}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function CallModal({ open, onClose, candidate, meta, onDone, calllist }: any) {
  const toast = useToast();
  const [outcome, setOutcome] = useState("connected");
  const [notes, setNotes] = useState("");
  const [transcript, setTranscript] = useState("");
  const [fields, setFields] = useState<any>({});
  const [followDays, setFollowDays] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [flags, setFlags] = useState<any[]>([]);
  useEffect(() => {
    if (open) {
      setOutcome("connected");
      setNotes("");
      setTranscript("");
      setFields({});
      setFlags([]);
      setFollowDays("");
    }
  }, [open]);

  async function prefill() {
    try {
      const r = await post(`/api/candidates/${candidate.id}/summarize-call`, { transcript });
      const s = r.suggestions;
      const { outcome: o, ...rest } = s;
      if (rest.skills) rest.skills = rest.skills.join(", ");
      setFields({ ...fields, ...rest });
      if (o) setOutcome(o);
      if (!notes) setNotes(transcript.slice(0, 1000));
      toast("info", `Pre-filled ${Object.keys(rest).length} fields — review before saving`);
    } catch (e) {
      toast("error", errMsg(e));
    }
  }

  async function save() {
    setBusy(true);
    try {
      const r = await post(`/api/candidates/${candidate.id}/calls`, {
        outcome,
        notes,
        fields,
        follow_up_days: followDays ? Number(followDays) : null,
        checkpoints: [],
      });
      if (calllist) await post(`/api/call-list/${calllist}?status=called`).catch(() => {});
      if (r.compliance_flags?.length) {
        setFlags(r.compliance_flags);
        toast("warning", "Saved. Some notes mention payroll/immigration topics — make sure those are delegated.");
      } else {
        toast("success", "Call logged");
        onClose();
      }
      onDone();
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  const editable: [string, string][] = [
    ["current_project_status", "Current project status"],
    ["availability", "Availability"],
    ["preferred_type", "Preferred type"],
    ["work_arrangement", "Work arrangement"],
    ["location", "Location"],
    ["years_experience", "Years of experience"],
    ["skills", "Skills (comma-separated)"],
    ["expected_compensation", "Compensation expectation"],
    ["interview_status", "Interviewing elsewhere"],
    ["career_goals", "Career goals"],
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Log call — ${candidate.full_name}`}
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {flags.length ? "Close" : "Cancel"}
          </Button>
          {!flags.length && (
            <Button variant="primary" loading={busy} onClick={save}>
              Save call
            </Button>
          )}
        </>
      }
    >
      {flags.length > 0 && (
        <div className="mb-3">
          <ErrorBox error={`Notes mention: ${flags.map((f) => `"${f.match}" (${f.category})`).join(", ")}. Notes are saved and flagged for review — route these questions to the right team instead of answering them.`} />
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Outcome">
          <select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {["connected", "interested", "call_back", "not_interested", "no_answer", "voicemail", "wrong_number"].map((o) => (
              <option key={o} value={o}>
                {humanize(o)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Schedule follow-up in (days)" hint="Optional — stage cadence applies otherwise">
          <input className="input" type="number" min={0} value={followDays} onChange={(e) => setFollowDays(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3">
        <Field label="Speech-to-text transcript or rough notes (optional)" hint="Paste a transcript and pre-fill the fields below. You review everything before saving.">
          <textarea className="input" rows={3} value={transcript} onChange={(e) => setTranscript(e.target.value)} placeholder="e.g. Based in Austin, TX, prefers W-2, remote, available in 2 weeks, 7 years of Python…" />
        </Field>
        <Button size="sm" className="mt-2" icon={<Sparkles className="h-3.5 w-3.5" />} disabled={!transcript.trim()} onClick={prefill}>
          Pre-fill from transcript
        </Button>
      </div>
      <div className="mt-3">
        <Field label="Call notes">
          <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {editable.map(([k, label]) => (
          <Field key={k} label={label}>
            {k === "preferred_type" ? (
              <Select value={fields[k] ?? candidate[k] ?? ""} onChange={(v) => setFields({ ...fields, [k]: v })} options={TYPES} />
            ) : k === "work_arrangement" ? (
              <Select value={fields[k] ?? candidate[k] ?? ""} onChange={(v) => setFields({ ...fields, [k]: v })} options={ARRANGEMENTS} />
            ) : (
              <input
                className={cx("input", fields[k] !== undefined && "ring-2 ring-emerald-300/60")}
                value={fields[k] ?? (k === "skills" ? (candidate.skills || []).join(", ") : candidate[k] ?? "")}
                onChange={(e) => setFields({ ...fields, [k]: e.target.value })}
              />
            )}
          </Field>
        ))}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
function Qualification({ data, meta, staff, reload }: any) {
  const c = data.candidate;
  const toast = useToast();
  const [form, setForm] = useState<any>({});
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => {
    const f: any = {};
    for (const [k] of meta.qualification_fields) f[k] = k === "skills" ? (c.skills || []).join(", ") : c[k] ?? "";
    setForm(f);
  }, [c.id, c.updated_at]);
  const required = new Set(meta.required_for_qualified);
  const missing = data.gates.missing_qualification_fields as string[];

  async function save() {
    setBusy(true);
    try {
      const r = await post(`/api/candidates/${c.id}/qualification`, { fields: form });
      toast(r.vendor_conflict?.conflict ? "warning" : "success", r.vendor_conflict?.conflict ? "Saved — possible vendor conflict found" : "Qualification saved");
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusy(false);
    }
  }
  async function decide(decision: string) {
    try {
      await post(`/api/candidates/${c.id}/decision`, { decision, reason: reason || (decision === "qualified" ? "Recruiter decision after qualification" : "Not a fit at this time") });
      toast("success", decision === "qualified" ? "Marked qualified" : "Closed as not qualified");
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2" title="12 qualification fields" subtitle="Known values are pre-filled. Required for Qualified are marked *.">
        <div className="grid gap-3 sm:grid-cols-2">
          {(meta.qualification_fields as [string, string][]).map(([k, label]) => (
            <Field key={k} label={`${label}${required.has(k) ? " *" : ""}`}>
              {k === "work_authorization" ? (
                <Select value={form[k]} onChange={(v) => setForm({ ...form, [k]: v })} options={WORK_AUTH} />
              ) : k === "preferred_type" ? (
                <Select value={form[k]} onChange={(v) => setForm({ ...form, [k]: v })} options={TYPES} />
              ) : k === "work_arrangement" ? (
                <Select value={form[k]} onChange={(v) => setForm({ ...form, [k]: v })} options={ARRANGEMENTS} />
              ) : k === "past_projects" || k === "career_goals" ? (
                <textarea className="input" rows={2} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              ) : (
                <input className={cx("input", missing.includes(k) && "border-amber-400")} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} type={k === "years_experience" ? "number" : "text"} />
              )}
            </Field>
          ))}
        </div>
        {staff && (
          <Button className="mt-4" variant="primary" loading={busy} onClick={save}>
            Save qualification
          </Button>
        )}
      </Card>
      <div className="space-y-4">
        <Card title="Is this candidate qualified?" subtitle="Your call — the score is only a suggestion.">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold">{c.fit_score != null ? `${Math.round(c.fit_score)}%` : "—"}</span>
            <span className="text-xs text-slate-500">suggested fit (best open requirement)</span>
          </div>
          {c.vendor_conflict?.conflict && (
            <div className="mt-2 rounded-md bg-red-50 dark:bg-red-500/10 px-2 py-1.5 text-xs text-red-800 dark:text-red-200">
              {(c.vendor_conflict.details || []).map((d: string, i: number) => (
                <div key={i}>⚠ {d}</div>
              ))}
            </div>
          )}
          {missing.length > 0 && <div className="mt-2 text-xs text-amber-700 dark:text-amber-300">Missing: {missing.map(humanize).join(", ")}</div>}
          {c.qualification_decision && <div className="mt-2 text-xs text-slate-500">Current decision: {humanize(c.qualification_decision)}</div>}
          {staff && (
            <>
              <textarea className="input mt-3" rows={2} placeholder="Reason (kept in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <div className="flex gap-2 mt-2">
                <Button variant="success" icon={<Check className="h-4 w-4" />} disabled={missing.length > 0} onClick={() => decide("qualified")}>
                  Qualified
                </Button>
                <Button variant="secondary" icon={<XCircle className="h-4 w-4" />} onClick={() => decide("not_qualified")}>
                  Not qualified
                </Button>
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function ProcessConsent({ data, meta, staff, reload }: any) {
  const c = data.candidate;
  const toast = useToast();
  const [items, setItems] = useState<Set<number>>(new Set());
  const [w2, setW2] = useState(!!c.w2_c2c_explained);
  const [notes, setNotes] = useState("");
  const prevAnswers = c.comfort_check?.answers || [];
  const [answers, setAnswers] = useState<{ answer: string; note: string }[]>(() => meta.comfort_check_questions.map((_: string, i: number) => ({ answer: prevAnswers[i]?.answer || "", note: prevAnswers[i]?.note || "" })));
  const canExplain = ["qualified", "process_explained"].includes(c.stage);
  const consent = data.consent[0];

  async function act(fn: () => Promise<any>, ok: string) {
    try {
      const r = await fn();
      toast("success", ok);
      reload();
      return r;
    } catch (e) {
      toast("error", errMsg(e));
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="1 · Explain the process" subtitle="Say it in your own words. The written summary is emailed automatically afterwards.">
        <ol className="space-y-1">
          {meta.company_process.map((p: string, i: number) => (
            <li key={i}>
              <label className="flex items-start gap-2 text-sm py-0.5 cursor-pointer">
                <input type="checkbox" checked={items.has(i)} onChange={() => { const n = new Set(items); n.has(i) ? n.delete(i) : n.add(i); setItems(n); }} className="mt-0.5" />
                {p}
              </label>
            </li>
          ))}
        </ol>
        <label className="flex items-center gap-2 text-sm mt-3">
          <input type="checkbox" checked={w2} onChange={(e) => setW2(e.target.checked)} /> Explained W-2 vs C2C using approved talking points
        </label>
        <textarea className="input mt-2" rows={2} placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        {c.process_explained_at && <div className="text-xs text-[#006300] dark:text-[#0ca30c] mt-2">✓ Explained {fmtDateTime(c.process_explained_at)}</div>}
        {staff && (
          <Button className="mt-3" variant="primary" disabled={!canExplain || items.size < meta.company_process.length || !w2} onClick={() => act(() => post(`/api/candidates/${c.id}/process-explained`, { w2_c2c_explained: w2, items_covered: [...items], notes }), "Process explained — summary email sent")}>
            Mark process explained
          </Button>
        )}
        {!canExplain && !c.process_explained_at && <div className="text-xs text-slate-500 mt-2">Available once the candidate is Qualified.</div>}
      </Card>

      <Card title="2 · Comfort check (5 questions)" subtitle="Required before any documents are requested. No pressure — 'no' is a fine answer.">
        <div className="space-y-3">
          {meta.comfort_check_questions.map((q: string, i: number) => (
            <div key={i}>
              <div className="text-sm">{q}</div>
              <div className="flex gap-2 mt-1">
                {["yes", "no"].map((a) => (
                  <button
                    key={a}
                    onClick={() => setAnswers(answers.map((x, j) => (j === i ? { ...x, answer: a } : x)))}
                    className={cx("rounded-md px-3 py-1 text-xs font-medium ring-1 ring-inset", answers[i].answer === a ? (a === "yes" ? "bg-emerald-600 text-white ring-emerald-600" : "bg-amber-500 text-white ring-amber-500") : "ring-slate-300 dark:ring-white/15")}
                  >
                    {a === "yes" ? "Yes" : "No"}
                  </button>
                ))}
                {answers[i].answer === "no" && <input className="input py-1 text-xs" placeholder="What's the concern?" value={answers[i].note} onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} />}
              </div>
            </div>
          ))}
        </div>
        {c.comfort_check?.completed_at && <div className="text-xs text-[#006300] dark:text-[#0ca30c] mt-3">✓ Completed {fmtDateTime(c.comfort_check.completed_at)}</div>}
        {c.comfort_check?.recorded_at && !c.comfort_check?.completed_at && <div className="text-xs text-amber-700 dark:text-amber-300 mt-3">Concerns raised — a follow-up was scheduled.</div>}
        {staff && (
          <Button className="mt-3" variant="primary" disabled={answers.some((a) => !a.answer)} onClick={() => act(() => post(`/api/candidates/${c.id}/comfort-check`, { answers }), "Comfort check saved")}>
            Save comfort check
          </Button>
        )}
      </Card>

      <Card title="3 · Consent to proceed" subtitle="E-consent link, timestamped and stored. Sent automatically when the comfort check is complete.">
        {consent ? (
          <div className="space-y-1 text-sm">
            <div className="flex items-center gap-2">
              Status:{" "}
              <Badge tone={consent.status === "granted" ? "green" : consent.status === "pending" ? "amber" : "red"}>{humanize(consent.status)}</Badge>
            </div>
            <div className="text-xs text-slate-500">Requested {fmtDateTime(consent.requested_at)}</div>
            {consent.recorded_at && (
              <div className="text-xs text-slate-500">
                Recorded {fmtDateTime(consent.recorded_at)} · {consent.method} · IP {consent.ip || "—"}
              </div>
            )}
          </div>
        ) : (
          <Empty icon={<ShieldCheck className="h-8 w-8" />} title="No consent requested yet" />
        )}
        {staff && !consent && (
          <Button className="mt-3" disabled={!data.gates.comfort_check_complete} onClick={() => act(() => post(`/api/candidates/${c.id}/consent/request`), "Consent link sent")}>
            Send consent link
          </Button>
        )}
        <div className="mt-4 rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
          <Lock className="inline h-3 w-3 mr-1" />
          Docs Requested and later stages stay locked until both the comfort check and consent are complete — manual overrides included.
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
const OFFER_TONE: Record<string, string> = { uploaded: "blue", pending_approval: "amber", approved: "green", rejected: "red", superseded: "gray", sent: "green" };
const ROLE_LABEL: Record<string, string> = { payroll: "Payroll" };
const OFFER_LABEL: Record<string, string> = { uploaded: "Ready to submit", pending_approval: "Waiting for approval", approved: "Approved", rejected: "Rejected", superseded: "Replaced", sent: "Sent to candidate" };

function OfferLetter({ data, reload }: any) {
  const { user } = useAuth();
  const toast = useToast();
  const c = data.candidate;
  const letters: any[] = data.offer_letters || [];
  const approvers: any[] = (data.offer_approvers || []).filter((a: any) => a.id !== user?.id);
  const current = letters.find((o) => o.status !== "superseded");
  const history = letters.filter((o) => o !== current);
  const canEdit = !!user && ["onboarding", "admin"].includes(user.role);
  const canOpen = !!user && (["onboarding", "ta_lead", "admin"].includes(user.role) || (user.role === "recruiter" && c.owner_id === user.id) || current?.approver_id === user.id);
  const isApprover = !!user && !!current && current.status === "pending_approval" && current.approver_id === user.id;

  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0); // remount the file input to clear it after upload
  const [notes, setNotes] = useState("");
  const [approverId, setApproverId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");

  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast("success", ok);
      reload();
      return true;
    } catch (e) {
      toast("error", errMsg(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function upload() {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("notes", notes);
    if (await run(() => api(`/api/candidates/${c.id}/offer-letters`, { method: "POST", form }), "Offer letter uploaded — now send it to Payroll for approval")) {
      setFile(null);
      setFileKey((k: number) => k + 1);
      setNotes("");
    }
  }
  async function open(o: any) {
    try {
      const res = await fetch(`/api/candidates/${c.id}/offer-letters/${o.id}/download`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      window.open(URL.createObjectURL(await res.blob()), "_blank");
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  const submit = () => run(() => post(`/api/candidates/${c.id}/offer-letters/${current.id}/submit`, { approver_id: Number(approverId) }), "Sent to Payroll for approval — the approver has been emailed");
  const send = () =>
    run(() => post(`/api/candidates/${c.id}/offer-letters/${current.id}/send`, { message }), `Offer letter emailed to ${c.email}`).then((ok) => {
      if (ok) setMessage("");
    });
  const decide = (approve: boolean) =>
    run(() => post(`/api/candidates/${c.id}/offer-letters/${current.id}/decision`, { approve, note: approve ? "" : reason }), approve ? "Offer letter approved" : "Offer letter rejected").then((ok) => {
      if (ok) {
        setRejecting(false);
        setReason("");
      }
    });

  const step = !current ? 1 : current.status === "uploaded" ? 2 : current.status === "pending_approval" ? 3 : current.status === "approved" ? 4 : current.status === "sent" ? 5 : 1;
  const steps = ["Upload offer letter", "Send to Payroll", "Payroll approves", "Send to candidate"];

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2 space-y-4">
        <Card title="Offer letter" subtitle="Onboarding uploads the finished offer letter once and sends it to Payroll for approval, then emails the approved letter to the candidate.">
          <ol className="flex flex-wrap gap-x-6 gap-y-2 text-xs mb-4">
            {steps.map((label, i) => (
              <li key={label} className={cx("flex items-center gap-1.5", i + 1 < step ? "text-emerald-700 dark:text-emerald-300" : i + 1 === step ? "font-semibold text-brand-800 dark:text-brand-200" : "text-slate-400")}>
                {i + 1 < step ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
                {label}
              </li>
            ))}
          </ol>

          {current && (
            <div className="rounded-lg border border-slate-200 dark:border-white/10 p-3 mb-4">
              <div className="flex flex-wrap items-center gap-2">
                <FileText className="h-4 w-4 text-[var(--series-1)]" />
                <div className="flex-1 min-w-[12rem]">
                  <div className="text-sm font-medium">{current.filename}</div>
                  <div className="text-[11px] text-slate-500">
                    Uploaded {fmtDateTime(current.uploaded_at)} by {current.uploaded_by_name || "—"}
                    {current.submitted_at && ` · sent to ${current.approver_name} ${relTime(current.submitted_at)}`}
                    {current.decided_at && ` · ${OFFER_LABEL[current.status].toLowerCase()} ${relTime(current.decided_at)}${current.decided_via === "email" ? " via email" : ""}`}
                    {current.sent_at && ` · emailed to ${current.sent_to} by ${current.sent_by_name || "—"} ${relTime(current.sent_at)}`}
                  </div>
                </div>
                <Badge tone={OFFER_TONE[current.status]}>{OFFER_LABEL[current.status]}</Badge>
                {canOpen && (
                  <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => open(current)}>
                    Open
                  </Button>
                )}
              </div>
              {current.notes && <div className="text-xs text-slate-600 dark:text-slate-300 mt-2 whitespace-pre-wrap">Notes: {current.notes}</div>}
              {current.decision_note && (
                <div className={cx("text-xs mt-2 whitespace-pre-wrap", current.status === "rejected" ? "text-red-700 dark:text-red-300" : "text-slate-600 dark:text-slate-300")}>
                  {current.status === "rejected" ? "Reason: " : "Approver note: "}
                  {current.decision_note}
                </div>
              )}
            </div>
          )}

          {canEdit && current?.status === "uploaded" && (
            <div className="flex flex-wrap items-end gap-2 mb-4">
              <div className="flex-1 min-w-[14rem]">
                <Field label="Payroll approver">
                  <select className="input" value={approverId} onChange={(e) => setApproverId(e.target.value)}>
                    <option value="">Choose a Payroll team member…</option>
                    {approvers.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({ROLE_LABEL[a.role] || humanize(a.role)})
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <Button variant="primary" icon={<Send className="h-4 w-4" />} disabled={!approverId} loading={busy} onClick={submit}>
                Send for approval
              </Button>
            </div>
          )}

          {isApprover && (
            <div className="rounded-lg bg-amber-50 dark:bg-amber-500/10 p-3 mb-4">
              <div className="text-sm font-medium mb-2">Your approval is needed</div>
              {!rejecting ? (
                <div className="flex flex-wrap gap-2">
                  <Button variant="success" icon={<Check className="h-4 w-4" />} loading={busy} onClick={() => decide(true)}>
                    Confirm & approve
                  </Button>
                  <Button variant="ghost" onClick={() => setRejecting(true)}>
                    Reject…
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <textarea className="input" rows={2} placeholder="What needs to change?" value={reason} onChange={(e) => setReason(e.target.value)} />
                  <div className="flex gap-2">
                    <Button variant="danger" disabled={!reason.trim()} loading={busy} onClick={() => decide(false)}>
                      Reject offer letter
                    </Button>
                    <Button variant="ghost" onClick={() => setRejecting(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {canEdit && current?.status === "approved" && (
            <div className="rounded-lg bg-emerald-50 dark:bg-emerald-500/10 p-3 mb-4 space-y-2">
              <div className="text-sm font-medium">Approved — ready to send to the candidate</div>
              {c.email_opt_out ? (
                <div className="text-xs text-red-700 dark:text-red-300">{c.full_name} has unsubscribed from emails. Share the offer letter another way.</div>
              ) : !c.email ? (
                <div className="text-xs text-red-700 dark:text-red-300">Add the candidate's email address to send the offer letter.</div>
              ) : (
                <>
                  <div className="text-xs text-slate-600 dark:text-slate-300">
                    The PDF will be emailed to <b>{c.email}</b> as an attachment.
                  </div>
                  <textarea className="input" rows={2} placeholder="Add a personal note to the email (optional)" value={message} onChange={(e) => setMessage(e.target.value)} />
                  <Button variant="primary" icon={<Send className="h-4 w-4" />} loading={busy} onClick={send}>
                    Send offer letter to candidate
                  </Button>
                </>
              )}
            </div>
          )}

          {canEdit && (!current || current.status === "rejected") && (
            <div className="space-y-2">
              <div className="text-sm font-medium">{current ? "Upload a corrected offer letter" : "Upload the offer letter"}</div>
              <input key={fileKey} type="file" accept="application/pdf,.pdf" className="block text-sm text-slate-600 dark:text-slate-300 file:mr-3 file:cursor-pointer file:rounded-lg file:border file:border-solid file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-50 dark:file:border-white/15 dark:file:bg-white/5 dark:file:text-slate-200" onChange={(e) => setFile(e.target.files?.[0] || null)} />
              <textarea className="input" rows={2} placeholder="Notes for Payroll (optional): rate, start date, client…" value={notes} onChange={(e) => setNotes(e.target.value)} />
              <Button icon={<Upload className="h-4 w-4" />} disabled={!file} loading={busy} onClick={upload}>
                Upload PDF
              </Button>
              {!current && <div className="text-[11px] text-slate-500">The offer letter is uploaded once. A new version can only be uploaded if Payroll rejects it.</div>}
            </div>
          )}
          {!canEdit && !current && <div className="text-sm text-slate-500">No offer letter yet. Onboarding uploads it here.</div>}
        </Card>
      </div>

      <Card title="History">
        {history.length === 0 ? (
          <div className="text-sm text-slate-500">No earlier versions.</div>
        ) : (
          <ul className="space-y-2">
            {history.map((o) => (
              <li key={o.id} className="text-xs">
                <div className="flex items-center gap-2">
                  <span className="flex-1 truncate">{o.filename}</span>
                  <Badge tone={OFFER_TONE[o.status]}>{OFFER_LABEL[o.status]}</Badge>
                </div>
                <div className="text-slate-500">{fmtDateTime(o.uploaded_at)}</div>
                {o.decision_note && <div className="text-slate-500">“{o.decision_note}”</div>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Documents({ data, reload }: any) {
  const { user } = useAuth();
  const toast = useToast();
  const c = data.candidate;
  const d = data.documents;
  const { data: preview } = useApi<any>(!d.request ? `/api/candidates/${c.id}/documents/checklist-preview` : null, [c.id]);
  const canVerify = user && ["onboarding", "ta_lead", "admin"].includes(user.role);
  const canDownload = user && (["onboarding", "ta_lead", "admin"].includes(user.role) || (user.role === "recruiter" && c.owner_id === user.id));

  async function download(item: any) {
    try {
      const res = await fetch(`/api/candidates/${c.id}/documents/${item.id}/download`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const blob = await res.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  async function verify(item: any, approve: boolean) {
    const note = approve ? "" : prompt("Reason for rejection (shown to the candidate)") || "";
    if (!approve && !note) return;
    try {
      await post(`/api/candidates/${c.id}/documents/${item.id}/verify`, { approve, note });
      toast("success", approve ? "Verified" : "Rejected — candidate will see the note in the portal");
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }

  const statusIcon = (s: string) =>
    s === "verified" ? <CheckCircle2 className="h-4 w-4 text-[#0ca30c]" /> : s === "uploaded" ? <FileText className="h-4 w-4 text-[var(--series-1)]" /> : s === "rejected" ? <XCircle className="h-4 w-4 text-[#d03b3b]" /> : <Circle className="h-4 w-4 text-slate-300" />;

  if (!d.request)
    return (
      <Card title="Documents" subtitle="Requested automatically once the process is explained, the comfort check is done and consent is recorded.">
        {preview?.items?.length ? (
          <>
            <div className="text-sm mb-2">Based on {c.work_authorization} · {c.preferred_type}, the checklist will be:</div>
            <ul className="text-sm list-disc pl-5 space-y-0.5">
              {preview.items.map((i: any) => (
                <li key={i.doc_type}>{i.label}</li>
              ))}
            </ul>
          </>
        ) : (
          <div className="text-sm text-slate-500">{preview?.error || "No checklist yet."}</div>
        )}
        <div className="mt-3 flex items-center gap-2">
          <Button
            disabled={!data.gates.consent_granted || !data.gates.comfort_check_complete}
            onClick={() =>
              post(`/api/candidates/${c.id}/documents/request`)
                .then(() => {
                  toast("success", "Checklist and secure portal link sent");
                  reload();
                })
                .catch((e) => toast("error", errMsg(e)))
            }
          >
            Request documents now
          </Button>
          <span className="text-xs text-slate-500">Rule-based only — no free-form requests.</span>
        </div>
      </Card>
    );

  const req = d.request;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card
        className="lg:col-span-2"
        title="Document checklist"
        subtitle={`Requested ${fmtDate(req.created_at)} · ${req.reminders_sent} reminder(s) sent${req.escalated ? " · escalated" : ""}`}
        actions={<Badge tone={req.status === "verified" ? "green" : req.status === "complete" ? "blue" : "amber"}>{humanize(req.status)}</Badge>}
      >
        <div className="divide-y divide-slate-100 dark:divide-white/5">
          {d.items.map((i: any) => (
            <div key={i.id} className="flex flex-wrap items-center gap-2 py-2.5">
              {statusIcon(i.status)}
              <div className="flex-1 min-w-[12rem]">
                <div className="text-sm">{i.label}</div>
                <div className="text-[11px] text-slate-500">
                  {humanize(i.status)}
                  {i.filename && ` · ${i.filename}`}
                  {i.expiry_date && ` · expires ${fmtDate(i.expiry_date, { month: "short", day: "numeric", year: "numeric" })}`}
                  {i.handled_by === "immigration" && " · coordinated by authorized team"}
                </div>
                {i.validation?.warnings?.length > 0 && <div className="text-[11px] text-amber-700 dark:text-amber-300">{i.validation.warnings.join("; ")}</div>}
                {i.validation?.errors?.length > 0 && i.status === "rejected" && <div className="text-[11px] text-red-700 dark:text-red-300">{i.validation.errors.join("; ")}</div>}
                {i.review_note && <div className="text-[11px] text-red-700 dark:text-red-300">Review note: {i.review_note}</div>}
              </div>
              {i.filename && canDownload && (
                <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download(i)}>
                  Open
                </Button>
              )}
              {canVerify && ["uploaded", "rejected", "verified"].includes(i.status) && i.filename && (
                <>
                  {i.status !== "verified" && (
                    <Button size="sm" variant="success" onClick={() => verify(i, true)}>
                      Verify
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => verify(i, false)}>
                    Reject
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      </Card>
      <div className="space-y-4">
        <Card title="Secure portal">
          <div className="text-xs text-slate-500 mb-1">Personal link sent to the candidate (expires {fmtDate(req.expires_at)}):</div>
          <a href={d.portal_url} target="_blank" rel="noreferrer" className="text-xs break-all text-brand-700 dark:text-brand-200 hover:underline">
            {d.portal_url}
          </a>
          <div className="mt-3 text-xs text-slate-500">Uploads are checked automatically (type, size, expiry). Content is verified by Onboarding / HR.</div>
        </Card>
        {d.folder && (
          <Card title="Candidate folder">
            <div className="text-xs font-mono break-all">{d.folder.path}/</div>
            <ul className="mt-2 text-xs font-mono text-slate-600 dark:text-slate-300 space-y-0.5">
              {d.folder.subfolders.map((s: string) => (
                <li key={s}>└ {s}</li>
              ))}
            </ul>
            <div className="mt-2 text-[11px] text-slate-500">Access: {d.folder.acl.join(", ")}</div>
          </Card>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function Outreach({ data, reload }: any) {
  const active = data.drafts.filter((d: any) => ["pending_approval", "blocked", "manual_send"].includes(d.status) && (!d.sequence_id || d.step === 1));
  const history = data.drafts.filter((d: any) => !active.includes(d));
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2" title="Drafts awaiting approval">
        {active.length === 0 ? <Empty icon={<MessageSquare className="h-8 w-8" />} title="No drafts waiting">Use "Draft message" above.</Empty> : <div className="space-y-3">{active.map((d: any) => <DraftCard key={d.id} draft={d} onChange={reload} showCandidate={false} candidateId={data.candidate.id} />)}</div>}
      </Card>
      <div className="space-y-4">
        <Card title="Email sequences" subtitle="Sends on schedule, stops on reply, capped, unsubscribe included.">
          {data.sequences.length === 0 ? (
            <Empty title="No sequences" />
          ) : (
            data.sequences.map((s: any) => (
              <div key={s.id} className="flex items-center gap-2 py-1.5 text-sm">
                <Badge tone={s.status === "active" ? "green" : s.status === "stopped" ? "gray" : "blue"}>{humanize(s.status)}</Badge>
                <span>Step {s.current_step}/3</span>
                {s.next_send_at && <span className="text-xs text-slate-500">next {relTime(s.next_send_at)}</span>}
                {s.stop_reason && <span className="text-xs text-slate-500">({humanize(s.stop_reason)})</span>}
              </div>
            ))
          )}
        </Card>
        <Card title="History">
          {history.length === 0 ? (
            <Empty title="Nothing yet" />
          ) : (
            <div className="space-y-1.5">
              {history.map((d: any) => (
                <div key={d.id} className="flex items-center gap-2 text-xs">
                  <Badge tone={d.status === "sent" ? "green" : "gray"}>{humanize(d.status)}</Badge>
                  <span className="truncate">{d.subject || humanize(d.kind)}</span>
                  <span className="ml-auto text-slate-400 shrink-0">{relTime(d.sent_at || d.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Timeline({ items }: { items: any[] }) {
  const icon: Record<string, JSX.Element> = {
    call: <Phone className="h-3.5 w-3.5" />,
    email_out: <Send className="h-3.5 w-3.5" />,
    email_in: <Mail className="h-3.5 w-3.5" />,
    linkedin_connection: <Linkedin className="h-3.5 w-3.5" />,
    linkedin_message: <Linkedin className="h-3.5 w-3.5" />,
    stage_change: <ArrowRightLeft className="h-3.5 w-3.5" />,
    document: <FileText className="h-3.5 w-3.5" />,
    consent: <ShieldCheck className="h-3.5 w-3.5" />,
    ticket: <TicketCheck className="h-3.5 w-3.5" />,
    note: <MessageSquare className="h-3.5 w-3.5" />,
  };
  const [filter, setFilter] = useState("all");
  const shown = useMemo(() => (filter === "all" ? items : items.filter((i) => (filter === "meaningful" ? i.meaningful : i.type.startsWith(filter)))), [items, filter]);
  return (
    <Card
      title="Timeline"
      subtitle="Every meaningful interaction is logged automatically."
      actions={
        <select className="input w-40 py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All activity</option>
          <option value="meaningful">Meaningful only</option>
          <option value="call">Calls</option>
          <option value="email">Emails</option>
          <option value="linkedin">LinkedIn</option>
          <option value="stage">Stage changes</option>
          <option value="note">Notes</option>
        </select>
      }
    >
      {shown.length === 0 ? (
        <Empty title="No activity" />
      ) : (
        <ol className="relative border-l border-slate-200 dark:border-white/10 ml-2">
          {shown.map((i) => (
            <li key={i.id} className="ml-4 pb-4">
              <span className="absolute -left-[11px] flex h-5 w-5 items-center justify-center rounded-full bg-white dark:bg-[#1a1a19] ring-1 ring-slate-200 dark:ring-white/15 text-slate-500">{icon[i.type] || <Circle className="h-3 w-3" />}</span>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{i.subject || humanize(i.type)}</span>
                {i.outcome && <Badge>{humanize(i.outcome)}</Badge>}
                {i.meaningful && <Badge tone="green">Meaningful</Badge>}
                {i.meta?.auto && <Badge tone="gray">Automated</Badge>}
              </div>
              {i.body && <p className="text-xs text-slate-600 dark:text-slate-300 mt-0.5 whitespace-pre-wrap line-clamp-4">{i.body}</p>}
              <div className="text-[11px] text-slate-400 mt-0.5">
                {fmtDateTime(i.occurred_at)}
                {i.user_name && ` · ${i.user_name}`}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function Tickets({ items }: { items: any[] }) {
  return (
    <Card title="Delegated tickets">
      {items.length === 0 ? (
        <Empty icon={<TicketCheck className="h-8 w-8" />} title="No tickets" />
      ) : (
        <div className="divide-y divide-slate-100 dark:divide-white/5">
          {items.map((t) => (
            <div key={t.id} className="py-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="brand">{TEAM_LABELS[t.team]}</Badge>
                <span className="text-sm font-medium">{t.subject}</span>
                <Badge tone={t.status === "resolved" ? "green" : t.breached ? "red" : "amber"}>{t.breached && t.status !== "resolved" ? "SLA breached" : humanize(t.status)}</Badge>
                {t.candidate_acknowledged && <Badge tone="gray">Candidate acknowledged</Badge>}
              </div>
              {t.description && <p className="text-xs text-slate-600 dark:text-slate-300 mt-1">{t.description}</p>}
              {t.resolution && <p className="text-xs text-[#006300] dark:text-[#0ca30c] mt-1">Resolution: {t.resolution}</p>}
              <div className="text-[11px] text-slate-400 mt-0.5">Created {fmtDateTime(t.created_at)} · due {fmtDateTime(t.due_at)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
function StageModal({ open, onClose, candidate, onDone }: any) {
  const toast = useToast();
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setTo("");
    setReason("");
    setErr(null);
  }, [open]);
  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await post(`/api/candidates/${candidate.id}/stage`, { to, reason });
      toast("success", `Moved to ${STAGE_LABELS[to]}`);
      onDone();
      onClose();
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
      title="Move stage (manual override)"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!to || reason.trim().length < 3} onClick={save}>
            Move
          </Button>
        </>
      }
    >
      <ErrorBox error={err} />
      <div className="space-y-3 mt-2">
        <Field label="New stage">
          <select className="input" value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">Choose…</option>
            {[...STAGE_ORDER, ...OUTCOMES].filter((s) => s !== candidate.stage).map((s) => (
              <option key={s} value={s}>
                {STAGE_LABELS[s]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reason (required, audit-logged)">
          <textarea className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <p className="text-xs text-slate-500">
          <Lock className="inline h-3 w-3" /> Docs Requested and later need the comfort check + consent, and Onboarding needs every document verified. Those gates can't be overridden.
        </p>
      </div>
    </Modal>
  );
}

function DelegateModal({ open, onClose, candidateId, onDone }: any) {
  const toast = useToast();
  const [team, setTeam] = useState("payroll");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [ack, setAck] = useState(true);
  async function save() {
    try {
      await post(`/api/candidates/${candidateId}/delegate`, { team, subject, description, acknowledge_candidate: ack });
      toast("success", `Delegated to ${TEAM_LABELS[team]}`);
      onDone();
      onClose();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Delegate to a specialist team"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!subject} onClick={save}>
            Create ticket
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Team">
          <select className="input" value={team} onChange={(e) => setTeam(e.target.value)}>
            {Object.entries(TEAM_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Subject">
          <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Question about payroll schedule" />
        </Field>
        <Field label="Details (the candidate's question, in their words)">
          <textarea className="input" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> Send the candidate an acknowledgment (no answers, just who will respond and when)
        </label>
      </div>
    </Modal>
  );
}

function FollowUpModal({ open, onClose, candidateId, onDone }: any) {
  const toast = useToast();
  const [days, setDays] = useState("2");
  const [reason, setReason] = useState("Follow up");
  async function save() {
    try {
      await post(`/api/candidates/${candidateId}/follow-ups`, { days: Number(days), reason });
      toast("success", "Follow-up scheduled");
      onDone();
      onClose();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Schedule a follow-up"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save}>
            Schedule
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-3 gap-3">
        <Field label="In (days)">
          <input className="input" type="number" min={0} value={days} onChange={(e) => setDays(e.target.value)} />
        </Field>
        <div className="col-span-2">
          <Field label="Reason">
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </div>
      </div>
      <p className="text-xs text-slate-500 mt-2">Weekends roll to Monday 9:00 AM.</p>
    </Modal>
  );
}
