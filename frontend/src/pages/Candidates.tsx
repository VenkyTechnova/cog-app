import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Copy, Flame, Merge, Plus, Upload, Users } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, ScoreBadge, StageBadge, Tabs, useToast } from "../components/ui";
import { api, errMsg, post } from "../lib/api";
import { OUTCOMES, relTime, STAGE_LABELS, STAGE_ORDER } from "../lib/format";
import { useApi } from "../lib/hooks";

export default function Candidates() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "all";
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("");
  const [mine, setMine] = useState(false);
  const [hot, setHot] = useState(false);
  const qs = new URLSearchParams();
  if (q) qs.set("q", q);
  if (stage) qs.set("stage", stage);
  if (mine) qs.set("mine", "true");
  if (hot) qs.set("hot", "true");
  const { data, error, loading, reload } = useApi<any[]>(tab === "all" ? `/api/candidates?${qs}` : null, [q, stage, mine, hot, tab]);
  const { data: dups, reload: reloadDups } = useApi<any[]>("/api/duplicates", [tab]);
  const { data: users } = useApi<any[]>("/api/users");
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const owners = Object.fromEntries((users || []).map((u) => [u.id, u.name]));

  return (
    <>
      <PageHeader
        title="Candidates"
        subtitle="One record per person. Every channel deduplicates on email, phone and LinkedIn URL."
        actions={
          <>
            <Button icon={<Upload className="h-4 w-4" />} onClick={() => setImportOpen(true)}>
              Import LinkedIn profiles
            </Button>
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setAddOpen(true)}>
              Add candidate
            </Button>
          </>
        }
      />
      <Tabs
        value={tab}
        onChange={(k) => setParams(k === "all" ? {} : { tab: k })}
        tabs={[
          { key: "all", label: "All candidates" },
          { key: "duplicates", label: "Merge queue", count: dups?.length },
        ]}
      />
      <div className="mt-4">
        {tab === "all" ? (
          <Card bodyClass="pt-4">
            <div className="flex flex-wrap gap-2 mb-3">
              <input className="input max-w-xs" placeholder="Search name, email, phone, headline" value={q} onChange={(e) => setQ(e.target.value)} />
              <select className="input w-48" value={stage} onChange={(e) => setStage(e.target.value)}>
                <option value="">All stages</option>
                {[...STAGE_ORDER, ...OUTCOMES].map((s) => (
                  <option key={s} value={s}>
                    {STAGE_LABELS[s]}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mine
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={hot} onChange={(e) => setHot(e.target.checked)} /> Hot replies
              </label>
            </div>
            <ErrorBox error={error} />
            {loading && !data ? (
              <Loading />
            ) : !data?.length ? (
              <Empty icon={<Users className="h-8 w-8" />} title="No candidates match" />
            ) : (
              <div className="overflow-x-auto -mx-4">
                <table className="w-full min-w-[820px]">
                  <thead>
                    <tr className="border-b border-slate-100 dark:border-white/5">
                      <th className="th">Name</th>
                      <th className="th">Skills</th>
                      <th className="th">Stage</th>
                      <th className="th">Fit</th>
                      <th className="th">Source</th>
                      <th className="th">Owner</th>
                      <th className="th">Last contact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((c) => (
                      <tr key={c.id} className="border-b border-slate-50 dark:border-white/5 hover:bg-slate-50/60 dark:hover:bg-white/[.03]">
                        <td className="td">
                          <Link to={`/candidates/${c.id}`} className="font-medium text-brand-800 dark:text-brand-200 hover:underline">
                            {c.full_name}
                          </Link>
                          {c.hot_reply && <Flame className="inline h-3.5 w-3.5 text-red-600 ml-1" aria-label="Hot reply" />}
                          <div className="text-xs text-slate-500">{c.location}</div>
                        </td>
                        <td className="td text-xs text-slate-600 dark:text-slate-300">{(c.skills || []).slice(0, 4).join(", ")}</td>
                        <td className="td">
                          <StageBadge stage={c.stage} />
                        </td>
                        <td className="td">
                          <ScoreBadge score={c.fit_score} />
                        </td>
                        <td className="td text-xs">{c.source}</td>
                        <td className="td text-xs">{owners[c.owner_id] || "—"}</td>
                        <td className="td text-xs text-slate-500">{relTime(c.last_contact_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        ) : (
          <MergeQueue pairs={dups || []} reload={reloadDups} />
        )}
      </div>
      <AddCandidate open={addOpen} onClose={() => setAddOpen(false)} onDone={reload} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onDone={reload} />
    </>
  );
}

function MergeQueue({ pairs, reload }: { pairs: any[]; reload: () => void }) {
  const toast = useToast();
  async function act(fn: () => Promise<any>, ok: string) {
    try {
      await fn();
      toast("success", ok);
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  if (!pairs.length) return <Card><Empty icon={<Copy className="h-8 w-8" />} title="No duplicates waiting">The weekly scan runs Sundays at 6:00 AM; duplicates are also caught on create.</Empty></Card>;
  const fields = ["email", "phone", "stage", "source", "created_at"];
  return (
    <div className="space-y-3">
      {pairs.map((p) => (
        <Card key={p.id} title={<span className="flex items-center gap-2">Possible duplicate <Badge tone="amber">matched on {p.matched_on.join(", ")}</Badge></span>}>
          <div className="grid gap-3 md:grid-cols-2">
            {[p.a, p.b].map((c: any) => (
              <div key={c.id} className="rounded-lg border border-slate-200 dark:border-white/10 p-3">
                <Link to={`/candidates/${c.id}`} className="font-medium hover:underline">
                  {c.full_name} <span className="text-xs text-slate-400">#{c.id}</span>
                </Link>
                <dl className="mt-2 grid grid-cols-3 gap-1 text-xs">
                  {fields.map((f) => (
                    <div key={f} className="contents">
                      <dt className="text-slate-500">{f.replace("_", " ")}</dt>
                      <dd className="col-span-2 truncate">{f === "stage" ? STAGE_LABELS[c[f]] : f === "created_at" ? relTime(c[f]) : c[f] || "—"}</dd>
                    </div>
                  ))}
                </dl>
                <Button size="sm" className="mt-3" icon={<Merge className="h-3.5 w-3.5" />} onClick={() => act(() => post(`/api/duplicates/${p.id}/merge`, { keep_id: c.id }), "Merged — history and documents moved to the kept record")}>
                  Keep this one
                </Button>
              </div>
            ))}
          </div>
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => act(() => post(`/api/duplicates/${p.id}/dismiss`), "Marked as not a duplicate")}>
            Not a duplicate
          </Button>
        </Card>
      ))}
    </div>
  );
}

function AddCandidate({ open, onClose, onDone }: any) {
  const toast = useToast();
  const nav = useNavigate();
  const [f, setF] = useState<any>({ source: "LinkedIn" });
  const [busy, setBusy] = useState(false);
  async function parse() {
    try {
      const r = await post("/api/candidates/parse-resume", { text: f.resume_text || "" });
      setF({ ...f, ...Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v])) });
      toast("info", "Parsed — check the fields");
    } catch (e) {
      toast("error", errMsg(e));
    }
  }
  async function save() {
    setBusy(true);
    try {
      const body = { ...f, years_experience: f.years_experience ? Number(f.years_experience) : undefined, grad_year: f.grad_year ? Number(f.grad_year) : undefined };
      const r = await post("/api/candidates", body);
      toast(r.deduplicated ? "info" : "success", r.deduplicated ? "Already in the database — merged into the existing record" : "Candidate added");
      onDone();
      onClose();
      nav(`/candidates/${r.candidate.id}`);
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusy(false);
    }
  }
  const input = (k: string, label: string, type = "text") => (
    <Field label={label}>
      <input className="input" type={type} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
    </Field>
  );
  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="Add candidate"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!f.full_name} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      <Field label="Paste resume text (optional)" hint="We'll extract email, phone, LinkedIn, skills and years.">
        <textarea className="input" rows={4} value={f.resume_text ?? ""} onChange={(e) => setF({ ...f, resume_text: e.target.value })} />
      </Field>
      <Button size="sm" className="mt-2" disabled={!f.resume_text} onClick={parse}>
        Parse resume
      </Button>
      <div className="grid gap-3 sm:grid-cols-2 mt-4">
        {input("full_name", "Full name *")}
        {input("email", "Email", "email")}
        {input("phone", "Phone")}
        {input("linkedin_url", "LinkedIn URL")}
        {input("location", "Location (City, ST)")}
        {input("skills", "Skills (comma-separated)")}
        {input("years_experience", "Years of experience", "number")}
        {input("headline", "Headline")}
        {input("university", "University")}
        {input("grad_year", "Graduation year", "number")}
        <Field label="Source">
          <select className="input" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
            {["LinkedIn", "Job Posting", "Cold Call", "Cold Email", "Recruitment Post", "Referral", "Other"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
      </div>
    </Modal>
  );
}

function ImportModal({ open, onClose, onDone }: any) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  async function go() {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api("/api/candidates/import", { method: "POST", form: fd });
      toast("success", `Imported ${r.created} new, updated ${r.updated_existing} existing`);
      onDone();
      onClose();
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import LinkedIn profiles"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!file} onClick={go}>
            Import
          </Button>
        </>
      }
    >
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Upload a CSV or JSON of profiles you exported or saved yourself (columns such as full_name, email, linkedin_url, location, skills, headline, university, grad_year). Nothing is scraped and nothing is sent on LinkedIn —
        messages are drafted for you to send manually.
      </p>
      <input type="file" accept=".csv,.json" className="mt-3 text-sm" onChange={(e) => setFile(e.target.files?.[0] || null)} />
    </Modal>
  );
}
