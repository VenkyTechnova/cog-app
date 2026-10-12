import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Info, Loader2, Lock, MinusCircle } from "lucide-react";
import { ApiError, api, errMsg } from "../lib/api";
import { cx } from "../components/ui";

type ConsentData = { first_name: string; text: string; status: string; recorded_at: string | null };

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-full bg-[var(--page)]">
      <header className="bg-brand-800 dark:bg-[#0b2233]">
        <div className="mx-auto flex max-w-xl items-center gap-2.5 px-4 py-3">
          <img src="/favicon.svg" className="h-7 w-7" alt="" />
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white">Cognitech Technologies</div>
            <div className="text-[11px] text-brand-200">Talent Acquisition</div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-xl px-4 py-6 sm:py-10">{children}</main>
    </div>
  );
}

const fmtWhen = (s: string | null) =>
  s ? new Date(s).toLocaleString(undefined, { weekday: "short", month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "";

export default function Consent() {
  const { token = "" } = useParams();
  const [data, setData] = useState<ConsentData | null>(null);
  const [loadErr, setLoadErr] = useState<{ status: number; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"yes" | "no" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<ConsentData>(`/api/public/consent/${encodeURIComponent(token)}`, { auth: false }));
      setLoadErr(null);
    } catch (e) {
      setLoadErr({ status: e instanceof ApiError ? e.status : 0, message: errMsg(e) });
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    document.title = "Confirm next steps · Cognitech";
    load();
  }, [load]);

  async function record(granted: boolean) {
    setBusy(granted ? "yes" : "no");
    setErr(null);
    try {
      await api(`/api/public/consent/${encodeURIComponent(token)}`, { method: "POST", body: { granted }, auth: false });
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setNotice("Your response was already recorded — here's what we have on file.");
        await load();
      } else setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <Shell>
        <div className="flex items-center justify-center gap-2 py-24 text-sm text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading…
        </div>
      </Shell>
    );
  }

  if (loadErr || !data) {
    const nf = loadErr?.status === 404;
    return (
      <Shell>
        <div className="card p-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 dark:bg-white/10 text-slate-500">
            <Lock className="h-6 w-6" />
          </div>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white">{nf ? "This link isn't valid" : "We couldn't load this page"}</h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            {nf ? "Please check the most recent email from your recruiter, or reply to it and they'll send you a new link." : `${loadErr?.message || "Something went wrong."} Please try again shortly.`}
          </p>
        </div>
      </Shell>
    );
  }

  const pending = data.status === "pending";
  const granted = data.status === "granted";

  return (
    <Shell>
      <h1 className="text-xl sm:text-2xl font-semibold text-slate-900 dark:text-white">Hi {data.first_name}, are you comfortable moving forward?</h1>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
        There's no pressure either way. Please read the statement below and let us know. Nothing here is final, and you can change your mind at any time by replying to your recruiter.
      </p>

      <div className="card mt-5 p-5">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">Consent statement</div>
        <p className="text-[15px] leading-relaxed text-slate-800 dark:text-slate-100 whitespace-pre-wrap">{data.text}</p>
      </div>

      {notice && (
        <p className="mt-4 flex items-start gap-2 rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2 text-sm text-slate-700 dark:text-slate-200">
          <Info className="h-4 w-4 mt-0.5 shrink-0 text-slate-400" /> {notice}
        </p>
      )}
      {err && <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-200">{err}</p>}

      {pending ? (
        <div className="mt-5 flex flex-col gap-3 sm:flex-row-reverse sm:justify-start">
          <button
            type="button"
            disabled={!!busy}
            onClick={() => record(true)}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-800 px-5 py-3 text-sm font-semibold text-white hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-400 disabled:opacity-60"
          >
            {busy === "yes" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            I'd like to proceed
          </button>
          <button
            type="button"
            disabled={!!busy}
            onClick={() => record(false)}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 dark:border-white/15 bg-white dark:bg-white/5 px-5 py-3 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-white/10 disabled:opacity-60"
          >
            {busy === "no" && <Loader2 className="h-4 w-4 animate-spin" />}
            Not right now
          </button>
        </div>
      ) : (
        <div
          className={cx(
            "mt-5 flex items-start gap-3 rounded-xl border px-4 py-4",
            granted ? "border-emerald-200 bg-emerald-50 dark:border-emerald-400/20 dark:bg-emerald-500/10" : "border-slate-200 bg-white dark:border-white/10 dark:bg-[#1a1a19]",
          )}
        >
          {granted ? <CheckCircle2 className="h-6 w-6 shrink-0 text-emerald-600 dark:text-emerald-300" /> : <MinusCircle className="h-6 w-6 shrink-0 text-slate-400" />}
          <div>
            <div className="font-semibold text-slate-900 dark:text-white">
              {granted ? "Thank you — you've chosen to proceed" : data.status === "declined" ? "Got it — we won't move forward for now" : `Status: ${data.status}`}
            </div>
            {data.recorded_at && <div className="text-sm text-slate-600 dark:text-slate-300 mt-0.5">Recorded {fmtWhen(data.recorded_at)}</div>}
            <p className="text-sm text-slate-600 dark:text-slate-300 mt-2">
              {granted
                ? "Your recruiter will send a secure link for the documentation step. If you have questions in the meantime, just reply to their email."
                : "Thanks for letting us know. Your recruiter may check in later — and if you change your mind, simply reply to them."}
            </p>
          </div>
        </div>
      )}

      <footer className="mt-8 border-t border-slate-200 dark:border-white/10 pt-4 text-center text-xs text-slate-500 dark:text-slate-400">
        This is not a final employment commitment. Your response is recorded securely with the date and time.
      </footer>
    </Shell>
  );
}
