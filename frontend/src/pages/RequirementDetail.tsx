import { Fragment, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Copy, Megaphone, Pencil, RefreshCw, Search, X } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, ScoreBadge, StageBadge, useToast } from "../components/ui";
import { errMsg, post } from "../lib/api";
import { humanize, relTime } from "../lib/format";
import { useApi } from "../lib/hooks";
import { PRIORITY_TONE, RequirementForm } from "./Requirements";

export default function RequirementDetail() {
  const { id } = useParams();
  const toast = useToast();
  const { data: r, error, loading, reload } = useApi<any>(`/api/requirements/${id}`, [id]);
  const [edit, setEdit] = useState(false);
  const [postOpen, setPostOpen] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  if (loading && !r) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!r) return null;

  async function act(fn: () => Promise<any>, ok: string) {
    try {
      await fn();
      toast("success", ok);
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  function copy(t: string) {
    navigator.clipboard.writeText(t).then(() => toast("info", "Copied — paste into LinkedIn Recruiter search"), () => toast("error", "Clipboard not available"));
  }

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {r.title} <Badge tone={PRIORITY_TONE[r.priority]}>{r.priority}</Badge> <Badge>{humanize(r.status)}</Badge>
          </span>
        }
        subtitle={`${r.client} · ${r.work_arrangement === "Remote" ? "Remote" : `${r.location} · ${r.work_arrangement}`} · ${r.employment_type}${r.rate ? ` · ${r.rate}` : ""} · min ${r.min_years} yrs · added ${relTime(r.created_at)}`}
        actions={
          <>
            <Button icon={<RefreshCw className="h-4 w-4" />} onClick={() => act(() => post(`/api/requirements/${id}/rematch`), "Re-matched against the database")}>
              Re-match
            </Button>
            <Button icon={<Megaphone className="h-4 w-4" />} onClick={() => setPostOpen(true)}>
              Request recruitment post
            </Button>
            <Button icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(true)}>
              Edit
            </Button>
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={`Top matches (${r.matches.length})`} subtitle="From your existing database, including past candidates to re-engage. Scores are explainable — click a row.">
          {r.matches.length === 0 ? (
            <Empty title="No matches yet" />
          ) : (
            <div className="overflow-x-auto -mx-4">
              <table className="w-full min-w-[640px]">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-white/5">
                    <th className="th">Candidate</th>
                    <th className="th">Score</th>
                    <th className="th">Stage</th>
                    <th className="th">Last contact</th>
                    <th className="th text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {r.matches.map((m: any) => (
                    <Fragment key={m.id}>
                      <tr className="border-b border-slate-50 dark:border-white/5 cursor-pointer hover:bg-slate-50/60 dark:hover:bg-white/[.03]" onClick={() => setExpanded(expanded === m.id ? null : m.id)}>
                        <td className="td">
                          <Link to={`/candidates/${m.id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-brand-800 dark:text-brand-200 hover:underline">
                            {m.full_name}
                          </Link>
                          {m.reengagement && <Badge tone="violet" className="ml-1.5">Re-engage</Badge>}
                          <div className="text-xs text-slate-500">{m.headline}</div>
                        </td>
                        <td className="td">
                          <ScoreBadge score={m.score} />
                        </td>
                        <td className="td">
                          <StageBadge stage={m.stage} />
                        </td>
                        <td className="td text-xs text-slate-500">{relTime(m.last_contact_at)}</td>
                        <td className="td text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                          <Link to={`/candidates/${m.id}?action=draft&kind=${m.reengagement ? "reengagement" : "cold_email"}&requirement=${r.id}`}>
                            <Button size="sm">Draft</Button>
                          </Link>{" "}
                          <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} onClick={() => act(() => post(`/api/requirements/${r.id}/matches/${m.id}?status=not_fit`), "Marked not a fit")}>
                            Not a fit
                          </Button>
                        </td>
                      </tr>
                      {expanded === m.id && (
                        <tr key={`${m.id}-x`} className="bg-slate-50/70 dark:bg-white/[.03]">
                          <td colSpan={5} className="px-4 py-3">
                            <Breakdown b={m.breakdown} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <div className="space-y-4">
          <Card title={<span className="flex items-center gap-1.5"><Search className="h-4 w-4" /> LinkedIn search strings</span>} subtitle="Run these yourself in LinkedIn / Recruiter. Nothing is automated on LinkedIn.">
            <div className="space-y-3">
              {r.boolean_queries.map((q: any, i: number) => (
                <div key={i}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium">{q.label}</span>
                    <button className="text-slate-400 hover:text-slate-600" onClick={() => copy(q.query)} aria-label="Copy">
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <code className="block mt-1 rounded bg-slate-50 dark:bg-white/5 px-2 py-1.5 text-[11px] break-words">{q.query}</code>
                  <div className="text-[11px] text-slate-500 mt-0.5">{Object.entries(q.filters).map(([k, v]) => `${humanize(k)}: ${v}`).join(" · ")}</div>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Description">
            <p className="text-sm text-slate-600 dark:text-slate-300 whitespace-pre-wrap">{r.description || "—"}</p>
            <div className="flex flex-wrap gap-1 mt-3">
              {r.skills.map((s: string) => (
                <Badge key={s}>{s}</Badge>
              ))}
            </div>
          </Card>
          {r.posts.length > 0 && (
            <Card title="Recruitment posts">
              {r.posts.map((p: any) => (
                <div key={p.id} className="text-sm flex items-center gap-2 py-1">
                  <Badge tone={p.status === "published" ? "green" : "amber"}>{humanize(p.status)}</Badge> {p.title}
                </div>
              ))}
              <Link to="/delegation" className="text-xs text-brand-700 dark:text-brand-200 hover:underline">
                Open in Delegation Center →
              </Link>
            </Card>
          )}
        </div>
      </div>
      {edit && <RequirementForm open={edit} onClose={() => setEdit(false)} onDone={reload} initial={r} />}
      <PostRequest open={postOpen} onClose={() => setPostOpen(false)} r={r} onDone={reload} />
    </>
  );
}

function Breakdown({ b }: { b: any }) {
  const rows = [
    ["Skills", b.skills, `✓ ${(b.skills?.matched || []).join(", ") || "none"}${b.skills?.missing?.length ? ` · missing ${b.skills.missing.join(", ")}` : ""}`],
    ["Experience", b.experience, `${b.experience?.candidate_years ?? "?"} yrs vs ${b.experience?.required} required`],
    ["Location", b.location, b.location?.note],
    ["Work authorization", b.work_authorization, b.work_authorization?.note],
    ["Availability", b.availability, b.availability?.value || "unknown"],
  ];
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map(([label, v, note]: any) => (
        <div key={label}>
          <div className="flex justify-between text-xs">
            <span className="font-medium">{label}</span>
            <span className="tabular">
              {v?.points ?? 0}/{v?.max}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-slate-200 dark:bg-white/10 mt-1 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${((v?.points || 0) / (v?.max || 1)) * 100}%`, background: "var(--series-1)" }} />
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">{note}</div>
        </div>
      ))}
      {b.employment_type_penalty > 0 && <div className="text-xs text-amber-700 dark:text-amber-300">−{b.employment_type_penalty} employment type mismatch</div>}
    </div>
  );
}

function PostRequest({ open, onClose, r, onDone }: any) {
  const toast = useToast();
  const [title, setTitle] = useState(`We're hiring: ${r.title}${r.work_arrangement === "Remote" ? " — Remote" : ` — ${r.location}`}`);
  const [body, setBody] = useState(`Cognitech Technologies is hiring a ${r.title} (${r.skills.join(", ")}). Interested? Comment or message us.`);
  const [channel, setChannel] = useState("LinkedIn");
  async function go() {
    try {
      await post(`/api/requirements/${r.id}/post-request`, { title, body, channel });
      toast("success", "Sent to Marketing (72h SLA)");
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
      title="Request a recruitment post"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={go}>
            Send to Marketing
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Channel">
          <select className="input" value={channel} onChange={(e) => setChannel(e.target.value)}>
            {["LinkedIn", "Flyer", "Job board", "Instagram", "University career portal"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Headline">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Draft copy" hint="Marketing designs it; a checklist gate checks accuracy before publishing.">
          <textarea className="input" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
