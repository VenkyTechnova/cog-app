import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Briefcase, Plus, Upload } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Tabs, useToast } from "../components/ui";
import { api, errMsg, post } from "../lib/api";
import { relTime } from "../lib/format";
import { useApi } from "../lib/hooks";

export const PRIORITY_TONE: Record<string, string> = { High: "red", Medium: "amber", Low: "gray" };

export default function Requirements() {
  const [status, setStatus] = useState("open");
  const { data, error, loading, reload } = useApi<any[]>(`/api/requirements?status=${status}`, [status]);
  const [open, setOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Requirements"
        subtitle="Job openings from the ATS, client emails, CSV / Google Sheets, or entered here. New ones are matched against the whole database automatically."
        actions={
          <>
            <Button icon={<Upload className="h-4 w-4" />} onClick={() => setImportOpen(true)}>
              Import CSV
            </Button>
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
              New requirement
            </Button>
          </>
        }
      />
      <Tabs value={status} onChange={setStatus} tabs={[{ key: "open", label: "Open" }, { key: "filled", label: "Filled" }, { key: "closed", label: "Closed" }, { key: "all", label: "All" }]} />
      <div className="mt-4">
        <ErrorBox error={error} />
        {loading && !data ? (
          <Loading />
        ) : !data?.length ? (
          <Card>
            <Empty icon={<Briefcase className="h-8 w-8" />} title="No requirements" />
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.map((r) => (
              <Link key={r.id} to={`/requirements/${r.id}`} className="card p-4 hover:ring-2 hover:ring-brand-300/60 transition">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-semibold">{r.title}</div>
                  <Badge tone={PRIORITY_TONE[r.priority]}>{r.priority}</Badge>
                </div>
                <div className="text-sm text-slate-600 dark:text-slate-300 mt-0.5">{r.client}</div>
                <div className="text-xs text-slate-500 mt-1">
                  {r.work_arrangement === "Remote" ? "Remote" : `${r.location} · ${r.work_arrangement}`} · {r.employment_type} {r.rate && `· ${r.rate}`}
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {(r.skills || []).map((s: string) => (
                    <Badge key={s}>{s}</Badge>
                  ))}
                </div>
                <div className="flex items-center justify-between mt-3 text-xs text-slate-500">
                  <span>
                    <strong className="text-slate-800 dark:text-slate-100 tabular">{r.match_count}</strong> matches ≥60%
                  </span>
                  <span>
                    {r.source.replace("_", " ")} · {relTime(r.created_at)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
      <RequirementForm open={open} onClose={() => setOpen(false)} onDone={reload} />
      <ImportReqs open={importOpen} onClose={() => setImportOpen(false)} onDone={reload} />
    </>
  );
}

export function RequirementForm({ open, onClose, onDone, initial }: { open: boolean; onClose: () => void; onDone: () => void; initial?: any }) {
  const toast = useToast();
  const nav = useNavigate();
  const [f, setF] = useState<any>(initial || { work_arrangement: "Remote", employment_type: "Either", priority: "Medium", min_years: 3 });
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      const body = { ...f, min_years: Number(f.min_years || 0), skills: typeof f.skills === "string" ? f.skills : (f.skills || []).join(", ") };
      if (initial) {
        await api(`/api/requirements/${initial.id}`, { method: "PATCH", body });
        toast("success", "Saved — matches refreshed");
        onDone();
        onClose();
      } else {
        const r = await post("/api/requirements", body);
        toast("success", "Requirement created — matching and re-engagement drafts are running");
        onDone();
        onClose();
        nav(`/requirements/${r.id}`);
      }
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusy(false);
    }
  }
  const input = (k: string, label: string, type = "text") => (
    <Field label={label}>
      <input className="input" type={type} value={Array.isArray(f[k]) ? f[k].join(", ") : f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
    </Field>
  );
  const select = (k: string, label: string, opts: string[]) => (
    <Field label={label}>
      <select className="input" value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
        {opts.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </Field>
  );
  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={initial ? "Edit requirement" : "New requirement"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!f.title || !f.client} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {input("title", "Title *")}
        {input("client", "Client *")}
        {input("skills", "Skills (comma-separated)")}
        {input("location", "Location (City, ST)")}
        {select("work_arrangement", "Arrangement", ["Remote", "Hybrid", "Onsite"])}
        {select("employment_type", "Type", ["W-2", "C2C", "Either"])}
        {input("rate", "Rate (internal only)")}
        {input("min_years", "Minimum years", "number")}
        {select("priority", "Priority", ["High", "Medium", "Low"])}
        {initial && select("status", "Status", ["open", "filled", "closed"])}
      </div>
      <div className="mt-3">
        <Field label="Description">
          <textarea className="input" rows={3} value={f.description ?? ""} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
      </div>
      <p className="text-xs text-slate-500 mt-2">The rate is internal. It's never included in automated candidate messages.</p>
    </Modal>
  );
}

function ImportReqs({ open, onClose, onDone }: any) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  async function go() {
    if (!file) return;
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api("/api/requirements/import", { method: "POST", form: fd });
      toast("success", `Imported ${r.created} requirements`);
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
      title="Import requirements (CSV / Google Sheets)"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!file} onClick={go}>
            Import
          </Button>
        </>
      }
    >
      <p className="text-sm text-slate-600 dark:text-slate-300">
        In Google Sheets use File → Download → CSV. Columns: <code className="text-xs">title, client, skills, location, work_arrangement, employment_type, rate, min_years, priority, description</code>.
      </p>
      <input type="file" accept=".csv" className="mt-3 text-sm" onChange={(e) => setFile(e.target.files?.[0] || null)} />
    </Modal>
  );
}
