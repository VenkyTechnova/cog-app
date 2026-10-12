import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Circle, Clock, FileUp, Info, Loader2, Lock, ShieldCheck, Upload, XCircle } from "lucide-react";
import { ApiError, api, errMsg } from "../lib/api";
import { fmtDate } from "../lib/format";
import { ProgressBar, cx } from "../components/ui";

type Item = {
  id: number;
  label: string;
  required: boolean;
  needs_expiry: boolean;
  status: "missing" | "uploaded" | "verified" | "rejected" | string;
  handled_by: string | null;
  filename: string | null;
  validation: { ok?: boolean; errors?: string[]; warnings?: string[] } | null;
  review_note: string;
};
type PortalData = {
  first_name: string;
  recruiter: string;
  status: string;
  expires_at: string;
  max_file_mb: number;
  accepted: string[];
  items: Item[];
};
type UploadResult = { ok: boolean; errors: string[]; warnings: string[]; status: string };

function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-full bg-[var(--page)]">
      <header className="bg-brand-800 dark:bg-[#0b2233]">
        <div className="mx-auto flex max-w-2xl items-center gap-2.5 px-4 py-3">
          <img src="/favicon.svg" className="h-7 w-7" alt="" />
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white">Cognitech Technologies</div>
            <div className="text-[11px] text-brand-200">Talent Acquisition</div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 py-6 sm:py-8">{children}</main>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { icon: ReactNode; label: string; cls: string }> = {
    missing: { icon: <Circle className="h-3.5 w-3.5" />, label: "Not uploaded yet", cls: "bg-slate-100 text-slate-700 dark:bg-white/10 dark:text-slate-200" },
    uploaded: { icon: <Clock className="h-3.5 w-3.5" />, label: "Received — being reviewed", cls: "bg-blue-50 text-blue-800 dark:bg-blue-500/15 dark:text-blue-200" },
    verified: { icon: <CheckCircle2 className="h-3.5 w-3.5" />, label: "Verified", cls: "bg-emerald-50 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200" },
    rejected: { icon: <XCircle className="h-3.5 w-3.5" />, label: "Needs another upload", cls: "bg-red-50 text-red-800 dark:bg-red-500/15 dark:text-red-200" },
  };
  const s = map[status] || map.missing;
  return <span className={cx("inline-flex self-start items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", s.cls)}>{s.icon}{s.label}</span>;
}

function Messages({ errors, warnings }: { errors?: string[]; warnings?: string[] }) {
  if (!errors?.length && !warnings?.length) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {errors?.map((e, i) => (
        <p key={`e${i}`} className="flex items-start gap-1.5 text-sm text-red-700 dark:text-red-300">
          <XCircle className="h-4 w-4 mt-0.5 shrink-0" /> {e}
        </p>
      ))}
      {warnings?.map((w, i) => (
        <p key={`w${i}`} className="flex items-start gap-1.5 text-sm text-amber-800 dark:text-amber-200">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" /> {w}
        </p>
      ))}
    </div>
  );
}

export default function Portal() {
  const { token = "" } = useParams();
  const [data, setData] = useState<PortalData | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const d = await api<PortalData>(`/api/public/portal/${encodeURIComponent(token)}`, { auth: false });
      setData(d);
      setError(null);
    } catch (e) {
      setError({ status: e instanceof ApiError ? e.status : 0, message: errMsg(e) });
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    document.title = "Secure document checklist · Cognitech";
    load();
  }, [load]);

  if (loading) {
    return (
      <PublicShell>
        <div className="flex items-center justify-center gap-2 py-24 text-sm text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading your checklist…
        </div>
      </PublicShell>
    );
  }

  if (error || !data) {
    const expired = error?.status === 410;
    const notFound = error?.status === 404;
    return (
      <PublicShell>
        <div className="card p-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 dark:bg-white/10 text-slate-500">{expired ? <Clock className="h-6 w-6" /> : <Lock className="h-6 w-6" />}</div>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white">{expired ? "This link has expired" : notFound ? "This link isn't valid" : "We couldn't load your checklist"}</h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            {expired
              ? "For your security, upload links only work for a limited time. Please reply to your recruiter and they'll send you a new link."
              : notFound
                ? "The link may have been replaced by a newer one. Please check your most recent email from your recruiter, or reply to ask for a new link."
                : `${error?.message || "Something went wrong."} Please try again in a moment, or contact your recruiter.`}
          </p>
          {!expired && !notFound && (
            <button onClick={() => { setLoading(true); load(); }} className="mt-4 rounded-lg border border-slate-300 dark:border-white/15 px-4 py-2 text-sm font-medium">
              Try again
            </button>
          )}
        </div>
        <Footer />
      </PublicShell>
    );
  }

  const required = data.items.filter((i) => i.required);
  const received = required.filter((i) => i.status === "uploaded" || i.status === "verified").length;
  const verified = required.filter((i) => i.status === "verified").length;
  const allIn = required.length > 0 && received === required.length;

  return (
    <PublicShell>
      <h1 className="text-xl sm:text-2xl font-semibold text-slate-900 dark:text-white">Hi {data.first_name}, here's your secure document checklist</h1>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Requested by {data.recruiter}. Upload each item below — you can come back to this page any time before {fmtDate(data.expires_at, { month: "long", day: "numeric" })}.</p>

      <div className="mt-4 flex items-start gap-2 rounded-lg border border-emerald-200 dark:border-emerald-400/20 bg-emerald-50/70 dark:bg-emerald-500/10 px-3 py-2.5 text-sm text-emerald-900 dark:text-emerald-100">
        <ShieldCheck className="h-5 w-5 shrink-0" />
        <span>Your files are encrypted and only authorized Cognitech team members can view them. Please upload here rather than sending documents by email.</span>
      </div>

      <div className="card mt-4 px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
            {allIn ? "All required documents received — thank you!" : `${received} of ${required.length} required documents received`}
          </span>
          <span className="text-xs text-slate-500 tabular whitespace-nowrap">{verified} verified</span>
        </div>
        <div className="mt-2">
          <ProgressBar value={received} max={required.length || 1} />
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Accepted: {data.accepted.join(", ")} · up to {data.max_file_mb} MB each
        </p>
      </div>

      <ul className="mt-4 space-y-3">
        {data.items.map((item) => (
          <li key={item.id}>
            <ItemCard item={item} token={token} maxMb={data.max_file_mb} onUploaded={load} />
          </li>
        ))}
      </ul>

      <Footer />
    </PublicShell>
  );
}

function Footer() {
  return (
    <footer className="mt-8 border-t border-slate-200 dark:border-white/10 pt-4 text-center text-xs text-slate-500 dark:text-slate-400 space-y-1">
      <p>This is not a final employment commitment.</p>
      <p>Questions about payroll, tax or work authorization? Reply to your recruiter and they'll route it to the right team.</p>
    </footer>
  );
}

function ItemCard({ item, token, maxMb, onUploaded }: { item: Item; token: string; maxMb: number; onUploaded: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const verified = item.status === "verified";
  const today = new Date().toISOString().slice(0, 10);
  const inputId = `file-${item.id}`;
  const [showForm, setShowForm] = useState(item.status !== "uploaded");

  const clientErrors: string[] = [];
  if (file && file.size > maxMb * 1024 * 1024) clientErrors.push(`This file is larger than ${maxMb} MB. Please upload a smaller copy.`);
  const needsDate = item.needs_expiry && !expiry;

  async function upload() {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (item.needs_expiry && expiry) form.append("expiry_date", expiry);
      const r = await api<UploadResult>(`/api/public/portal/${encodeURIComponent(token)}/items/${item.id}`, { method: "POST", form, auth: false });
      setResult(r);
      if (r.ok) {
        setFile(null);
        setExpiry("");
        setShowForm(false);
        if (fileRef.current) fileRef.current.value = "";
      }
      await onUploaded();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  // Show the last server validation for rejected items unless we have a fresher result.
  const shownErrors = result ? result.errors : item.status === "rejected" ? item.validation?.errors : undefined;
  const shownWarnings = result ? result.warnings : item.validation?.warnings;

  return (
    <div className={cx("card p-4", item.status === "rejected" && "border-red-200 dark:border-red-400/30")}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">{item.label}</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {item.required ? "Required" : "Optional"}
            {item.needs_expiry && " · Expiry date needed"}
            {item.filename && ` · ${item.filename}`}
          </p>
        </div>
        <StatusChip status={item.status} />
      </div>

      {item.handled_by === "immigration" && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2 text-sm text-slate-700 dark:text-slate-200">
          <Info className="h-4 w-4 mt-0.5 shrink-0 text-slate-400" />
          Our authorized team will coordinate this with you. Upload it here once they've walked you through it.
        </p>
      )}

      {item.status === "rejected" && item.review_note && !result && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-red-700 dark:text-red-300">
          <XCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            <span className="font-medium">Reviewer note: </span>
            {item.review_note}
          </span>
        </p>
      )}
      <Messages errors={shownErrors} warnings={shownWarnings} />
      {result?.ok && (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-emerald-700 dark:text-emerald-300">
          <CheckCircle2 className="h-4 w-4" /> Uploaded — thank you. We'll review it shortly.
        </p>
      )}
      {err && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-red-700 dark:text-red-300">
          <XCircle className="h-4 w-4 mt-0.5 shrink-0" /> {err}
        </p>
      )}

      {!verified && !showForm ? (
        <button type="button" onClick={() => setShowForm(true)} className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 dark:text-brand-200 hover:underline">
          <FileUp className="h-4 w-4" /> Upload a replacement
        </button>
      ) : verified ? (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
          <Lock className="h-3.5 w-3.5" /> Verified documents can't be replaced here. Contact your recruiter if something changed.
        </p>
      ) : (
        <div className="mt-3 space-y-3 border-t border-slate-100 dark:border-white/10 pt-3">
          <div className={cx("grid gap-3", item.needs_expiry && "sm:grid-cols-[1fr_auto]")}>
            <div>
              <label htmlFor={inputId} className="label">
                {item.status === "missing" ? "Choose file" : "Upload a replacement"}
              </label>
              <label
                htmlFor={inputId}
                className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300 dark:border-white/20 px-3 py-3 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5"
              >
                <FileUp className="h-5 w-5 shrink-0 text-slate-400" />
                <span className="truncate">{file ? `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)` : "Tap to choose a PDF or photo"}</span>
              </label>
              <input
                ref={fileRef}
                id={inputId}
                type="file"
                className="sr-only"
                accept=".pdf,.jpg,.jpeg,.png,.docx,application/pdf,image/jpeg,image/png"
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null);
                  setResult(null);
                  setErr(null);
                }}
              />
            </div>
            {item.needs_expiry && (
              <div>
                <label htmlFor={`exp-${item.id}`} className="label">
                  Expiry date
                </label>
                <input id={`exp-${item.id}`} type="date" min={today} className="input sm:w-44" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
              </div>
            )}
          </div>
          <Messages errors={clientErrors} />
          <button
            type="button"
            onClick={upload}
            disabled={!file || needsDate || busy || clientErrors.length > 0}
            className="inline-flex w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-brand-800 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-400 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {busy ? "Uploading securely…" : "Upload"}
          </button>
          {file && needsDate && <p className="text-xs text-slate-500">Enter the expiry date printed on the document to continue.</p>}
        </div>
      )}
    </div>
  );
}
