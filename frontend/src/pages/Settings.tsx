import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Eye, Lock, Mail, MinusCircle, Pencil, Plug, Plus, Send, ShieldAlert, UserPlus } from "lucide-react";
import { ApiError, api, errMsg, get, patch, post, put } from "../lib/api";
import { ROLE_LABELS, isManager, useAuth } from "../lib/auth";
import { OUTCOMES, STAGE_LABELS, STAGE_ORDER, fmtDate, fmtDateTime, humanize, relTime } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Tabs, Toggle, cx, useToast } from "../components/ui";

type SettingsResp = { values: Record<string, any>; defaults: Record<string, any> };

const DIGEST_SECTIONS = [
  { key: "new_requirements", label: "New requirements & top matches" },
  { key: "applicants", label: "New applicants" },
  { key: "hot_replies", label: "Hot replies" },
  { key: "follow_ups", label: "Follow-ups due today & overdue" },
  { key: "pending_documents", label: "Pending documents past SLA" },
];

const COUNT_LABELS: Record<string, string> = {
  new_requirements: "reqs",
  matches: "matches",
  applicants: "applicants",
  hot_replies: "hot replies",
  follow_ups_today: "due today",
  follow_ups_overdue: "overdue",
  pending_documents: "pending docs",
  breached_tickets: "breached tickets",
};

const DOW: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

function ReadOnlyNote() {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
      <Lock className="h-3.5 w-3.5" /> Read-only — TA leads and admins can change these
    </span>
  );
}

/** Save a set of changed settings sequentially via PUT /api/settings/:key. */
async function saveSettings(changes: Record<string, any>) {
  for (const [k, v] of Object.entries(changes)) await put(`/api/settings/${encodeURIComponent(k)}`, { value: v });
}

const eq = (a: any, b: any) => JSON.stringify(a) === JSON.stringify(b);

export default function Settings() {
  const { user } = useAuth();
  const manager = isManager(user);
  const admin = user?.role === "admin";
  const tabs = [
    { key: "digest", label: "Digest" },
    { key: "templates", label: "Templates" },
    { key: "cadences", label: "Follow-up cadences" },
    { key: "guardrails", label: "Guardrails & limits" },
    { key: "integrations", label: "Integrations" },
    ...(admin ? [{ key: "users", label: "Users & roles" }] : []),
  ];
  const [params, setParams] = useSearchParams();
  const tab = tabs.find((t) => t.key === params.get("tab"))?.key || "digest";
  const settings = useApi<SettingsResp>("/api/settings");

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" subtitle={manager ? "Digest, templates, cadences, guardrails and integrations" : "Your digest preferences and the team's configuration"} />
      <Tabs tabs={tabs} value={tab} onChange={(k) => setParams({ tab: k }, { replace: true })} />
      <ErrorBox error={settings.error} />
      {tab === "digest" && <DigestTab settings={settings.data} reloadSettings={settings.reload} manager={manager} />}
      {tab === "templates" && <TemplatesTab manager={manager} />}
      {tab === "cadences" && (settings.data ? <CadenceTab settings={settings.data} manager={manager} onSaved={settings.reload} /> : <Loading />)}
      {tab === "guardrails" && (settings.data ? <GuardrailsTab settings={settings.data} manager={manager} onSaved={settings.reload} /> : <Loading />)}
      {tab === "integrations" && <IntegrationsTab />}
      {tab === "users" && admin && <UsersTab />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Digest
// ---------------------------------------------------------------------------
function DigestTab({ settings, reloadSettings, manager }: { settings: SettingsResp | null; reloadSettings: () => void; manager: boolean }) {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const [enabled, setEnabled] = useState(!!user?.digest_enabled);
  const initialSections = (): Record<string, boolean> => {
    const s = (user?.digest_prefs || {}).sections || {};
    return Object.fromEntries(DIGEST_SECTIONS.map((d) => [d.key, s[d.key] !== false]));
  };
  const [sections, setSections] = useState<Record<string, boolean>>(initialSections);
  const [savingMine, setSavingMine] = useState(false);
  const [mineErr, setMineErr] = useState<string | null>(null);

  useEffect(() => {
    setEnabled(!!user?.digest_enabled);
    setSections(initialSections());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  const mineDirty = user && (enabled !== user.digest_enabled || !eq(sections, initialSections()));

  async function saveMine() {
    if (!user) return;
    setSavingMine(true);
    setMineErr(null);
    try {
      await patch(`/api/users/${user.id}`, { digest_enabled: enabled, digest_prefs: { ...(user.digest_prefs || {}), sections } });
      await refresh();
      toast("success", "Digest preferences saved");
    } catch (e) {
      setMineErr(errMsg(e));
    } finally {
      setSavingMine(false);
    }
  }

  // Global schedule
  const v = settings?.values || {};
  const [g, setG] = useState<Record<string, any>>({});
  useEffect(() => {
    if (settings)
      setG({
        "digest.time": v["digest.time"],
        "digest.business_days_only": v["digest.business_days_only"],
        "digest.when_empty": v["digest.when_empty"],
        "digest.top_matches": v["digest.top_matches"],
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);
  const gChanges = Object.fromEntries(Object.entries(g).filter(([k, val]) => !eq(val, v[k])));
  const [savingG, setSavingG] = useState(false);
  const [gErr, setGErr] = useState<string | null>(null);
  async function saveGlobal() {
    setSavingG(true);
    setGErr(null);
    try {
      await saveSettings(gChanges);
      toast("success", "Digest schedule saved");
      reloadSettings();
    } catch (e) {
      setGErr(errMsg(e));
    } finally {
      setSavingG(false);
    }
  }

  // Preview + send
  const [preview, setPreview] = useState(false);
  const [fmt, setFmt] = useState<"html" | "text">("html");
  const [html, setHtml] = useState<string | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  useEffect(() => {
    if (!preview) return;
    setHtml(null);
    setPreviewErr(null);
    api<string>(`/api/digest/preview?format=${fmt}`)
      .then((t) => setHtml(typeof t === "string" ? t : JSON.stringify(t)))
      .catch((e) => setPreviewErr(errMsg(e)));
  }, [preview, fmt]);

  const logs = useApi<any[]>("/api/digest/logs");
  const [sending, setSending] = useState(false);
  async function sendNow() {
    setSending(true);
    try {
      const r = await post<any>("/api/digest/send-now");
      toast(r.status === "failed" ? "error" : "success", `Test digest: ${humanize(r.status)}`);
      logs.reload();
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="My daily digest"
          subtitle="A morning email with new requirements, top matches, hot replies, follow-ups and pending documents."
          actions={
            <Button variant="primary" size="sm" disabled={!mineDirty} loading={savingMine} onClick={saveMine}>
              Save
            </Button>
          }
        >
          <Toggle checked={enabled} onChange={setEnabled} label={<span className="font-medium">{enabled ? "Digest on" : "Digest off"}</span>} />
          <div className="mt-4">
            <div className="label">Sections to include</div>
            <div className="space-y-1.5">
              {DIGEST_SECTIONS.map((s) => (
                <label key={s.key} className={cx("flex items-center gap-2 text-sm", !enabled && "opacity-50")}>
                  <input type="checkbox" className="h-4 w-4 accent-brand-700" disabled={!enabled} checked={sections[s.key]} onChange={(e) => setSections({ ...sections, [s.key]: e.target.checked })} />
                  {s.label}
                </label>
              ))}
            </div>
          </div>
          <ErrorBox error={mineErr} />
          <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 dark:border-white/10 pt-3">
            <Button icon={<Eye className="h-4 w-4" />} onClick={() => setPreview(true)}>
              Preview my digest
            </Button>
            <Button icon={<Send className="h-4 w-4" />} loading={sending} onClick={sendNow}>
              Send me a test now
            </Button>
          </div>
        </Card>

        <Card title="Team schedule" subtitle="Applies to everyone's digest" actions={manager ? <Button variant="primary" size="sm" disabled={!Object.keys(gChanges).length || g["digest.top_matches"] === "" || !g["digest.time"]} loading={savingG} onClick={saveGlobal}>Save</Button> : undefined}>
          {!settings ? (
            <Loading />
          ) : (
            <div className="space-y-3">
              {!manager && <ReadOnlyNote />}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Send time (ET, 24h)">
                  <input type="time" className="input" disabled={!manager} value={g["digest.time"] || ""} onChange={(e) => setG({ ...g, "digest.time": e.target.value })} />
                </Field>
                <Field label="Top matches per requirement">
                  <input type="number" min={1} max={20} className="input" disabled={!manager} value={g["digest.top_matches"] ?? ""} onChange={(e) => setG({ ...g, "digest.top_matches": e.target.value === "" ? "" : Number(e.target.value) })} />
                </Field>
              </div>
              <Toggle disabled={!manager} checked={!!g["digest.business_days_only"]} onChange={(val) => setG({ ...g, "digest.business_days_only": val })} label="Business days only (Mon–Fri)" />
              <Field label="When there's nothing new">
                <select className="input" disabled={!manager} value={g["digest.when_empty"] || "note"} onChange={(e) => setG({ ...g, "digest.when_empty": e.target.value })}>
                  <option value="note">Send a short "nothing new today" note</option>
                  <option value="skip">Skip the email</option>
                </select>
              </Field>
              <ErrorBox error={gErr} />
            </div>
          )}
        </Card>
      </div>

      <Card title="Delivery log" subtitle={manager ? "Recent digests across the team" : "Your recent digests"} bodyClass="px-0 pb-0 pt-0">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full min-w-[820px]">
            <thead className="border-y border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.03]">
              <tr>
                <th className="th">Date</th>
                <th className="th">User</th>
                <th className="th">Kind</th>
                <th className="th">Status</th>
                <th className="th">Contents</th>
                <th className="th">Opened</th>
                <th className="th text-right">Clicks</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-white/5">
              {logs.loading && !logs.data && (
                <tr>
                  <td colSpan={7}>
                    <Loading />
                  </td>
                </tr>
              )}
              {logs.data?.map((d) => {
                const summary = Object.entries(d.counts || {})
                  .filter(([, n]) => Number(n) > 0)
                  .map(([k, n]) => `${n} ${COUNT_LABELS[k] || humanize(k)}`)
                  .join(" · ");
                return (
                  <tr key={d.id}>
                    <td className="td whitespace-nowrap tabular">{fmtDate(d.digest_date + "T12:00:00", { weekday: "short", month: "short", day: "numeric" })}</td>
                    <td className="td whitespace-nowrap">{d.user_name}</td>
                    <td className="td">{d.kind === "team_rollup" ? "Team rollup" : "Recruiter"}</td>
                    <td className="td">
                      <DigestStatus status={d.status} />
                    </td>
                    <td className="td text-xs text-slate-600 dark:text-slate-300">{summary || "Nothing new"}</td>
                    <td className="td whitespace-nowrap text-slate-600 dark:text-slate-300" title={fmtDateTime(d.opened_at)}>
                      {d.opened_at ? `${relTime(d.opened_at)}${d.open_count > 1 ? ` (${d.open_count}×)` : ""}` : "—"}
                    </td>
                    <td className="td text-right tabular">{d.click_count || 0}</td>
                  </tr>
                );
              })}
              {logs.data && logs.data.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <Empty icon={<Mail className="h-8 w-8" />} title="No digests sent yet">
                      Use "Send me a test now" to try it.
                    </Empty>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-2">
          <ErrorBox error={logs.error} />
        </div>
      </Card>

      <Modal
        open={preview}
        onClose={() => setPreview(false)}
        wide
        title={
          <span className="flex items-center gap-3">
            Digest preview
            <span className="inline-flex rounded-lg border border-slate-300 dark:border-white/15 p-0.5 text-xs font-normal">
              {(["html", "text"] as const).map((f) => (
                <button key={f} type="button" onClick={() => setFmt(f)} className={cx("px-2.5 py-0.5 rounded-md", fmt === f ? "bg-brand-800 text-white dark:bg-brand-500" : "text-slate-600 dark:text-slate-300")}>
                  {f === "html" ? "HTML" : "Text"}
                </button>
              ))}
            </span>
          </span>
        }
      >
        <ErrorBox error={previewErr} />
        {html == null && !previewErr ? (
          <Loading label="Building preview…" />
        ) : (
          html != null && <iframe title="Digest preview" srcDoc={html} sandbox="" className="w-full h-[60vh] rounded-lg border border-slate-200 dark:border-white/10 bg-white" />
        )}
        <p className="mt-2 text-[11px] text-slate-500">Preview only — links and one-click actions are inactive here, and nothing is saved.</p>
      </Modal>
    </div>
  );
}

function DigestStatus({ status }: { status: string }) {
  if (status === "sent") return <Badge tone="green"><CheckCircle2 className="h-3 w-3" />Sent</Badge>;
  if (status === "failed") return <Badge tone="red"><AlertTriangle className="h-3 w-3" />Failed</Badge>;
  if (status === "empty_note") return <Badge tone="blue"><Mail className="h-3 w-3" />Empty note</Badge>;
  if (status === "skipped") return <Badge tone="gray"><MinusCircle className="h-3 w-3" />Skipped</Badge>;
  return <Badge>{humanize(status)}</Badge>;
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------
type Hit = { category: string; severity: string; match: string };
const placeholdersOf = (s: string) => Array.from(new Set(Array.from((s || "").matchAll(/\{\{\s*(\w+)\s*\}\}/g)).map((m) => m[1])));

function TemplatesTab({ manager }: { manager: boolean }) {
  const toast = useToast();
  const { data, error, loading, setData } = useApi<any[]>("/api/templates");
  const [edit, setEdit] = useState<any | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hits, setHits] = useState<Hit[]>([]);

  const allPlaceholders = useMemo(() => Array.from(new Set((data || []).flatMap((t) => placeholdersOf(t.subject + "\n" + t.body)))).sort(), [data]);

  function open(t: any) {
    setEdit(t);
    setSubject(t.subject || "");
    setBody(t.body || "");
    setErr(null);
    setHits([]);
  }
  async function save() {
    setBusy(true);
    setErr(null);
    setHits([]);
    try {
      const r = await put<any>(`/api/templates/${edit.key}`, { subject, body });
      setData((data || []).map((t) => (t.key === r.key ? r : t)));
      toast("success", "Template saved");
      setEdit(null);
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === "object" && Array.isArray(e.detail.hits)) {
        setErr(e.detail.message);
        setHits(e.detail.hits);
      } else setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <Loading />;
  return (
    <div className="space-y-4">
      <ErrorBox error={error} />
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="flex items-start gap-2 rounded-lg border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
          <Lock className="h-4 w-4 shrink-0 mt-0.5 text-slate-400" />
          <span>
            Only templates marked <strong>Auto-send allowed</strong> may be sent by workflows without a human. Every other template is a draft the recruiter reviews and sends. Templates can't contain pay, tax or immigration statements.
          </span>
        </div>
        <div className="rounded-lg border border-slate-200 dark:border-white/10 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
          <div className="font-medium mb-1">Available placeholders</div>
          <div className="flex flex-wrap gap-1">
            {allPlaceholders.map((p) => (
              <code key={p} className="rounded bg-slate-100 dark:bg-white/10 px-1.5 py-0.5 text-[11px]">{`{{${p}}}`}</code>
            ))}
          </div>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.map((t) => (
          <Card
            key={t.key}
            title={t.name}
            subtitle={
              <span className="flex flex-wrap items-center gap-1.5 mt-1">
                <code className="text-[11px]">{t.key}</code>
                <Badge>{humanize(t.channel)}</Badge>
                {t.auto_send_allowed ? (
                  <Badge tone="brand" title="Workflows may send this template automatically">
                    <Lock className="h-3 w-3" />
                    Auto-send allowed
                  </Badge>
                ) : (
                  <Badge tone="gray" title="Always reviewed by a recruiter before sending">
                    <Pencil className="h-3 w-3" />
                    Recruiter-approved
                  </Badge>
                )}
              </span>
            }
            actions={
              manager ? (
                <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => open(t)}>
                  Edit
                </Button>
              ) : undefined
            }
          >
            {t.description && <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">{t.description}</p>}
            {t.subject && (
              <div className="text-sm mb-1">
                <span className="text-slate-500">Subject: </span>
                <span className="font-medium text-slate-800 dark:text-slate-100">{t.subject}</span>
              </div>
            )}
            <pre className="whitespace-pre-wrap font-sans text-sm text-slate-700 dark:text-slate-200 rounded-lg bg-slate-50 dark:bg-white/5 px-3 py-2 max-h-56 overflow-y-auto scrollbar-thin">{t.body}</pre>
            <div className="mt-2 flex flex-wrap gap-1">
              {placeholdersOf(t.subject + "\n" + t.body).map((p) => (
                <code key={p} className="rounded bg-slate-100 dark:bg-white/10 px-1 text-[10px] text-slate-600 dark:text-slate-300">{`{{${p}}}`}</code>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-slate-400">Updated {relTime(t.updated_at)}</p>
          </Card>
        ))}
      </div>

      <Modal
        open={!!edit}
        onClose={() => setEdit(null)}
        wide
        title={`Edit template — ${edit?.name || ""}`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEdit(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} disabled={!body.trim()} onClick={save}>
              Save template
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {edit?.auto_send_allowed && (
            <div className="flex items-start gap-2 rounded-lg bg-brand-50 dark:bg-brand-500/10 px-3 py-2 text-xs text-brand-900 dark:text-brand-100">
              <Lock className="h-4 w-4 shrink-0" /> Workflows send this template automatically — changes take effect on the next send.
            </div>
          )}
          {edit?.channel === "email" && (
            <Field label="Subject">
              <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} />
            </Field>
          )}
          <Field label="Body" hint={`Placeholders: ${placeholdersOf(edit?.body || "").map((p) => `{{${p}}}`).join(", ") || "none"}`}>
            <textarea className="input min-h-[260px] font-mono text-[13px]" value={body} onChange={(e) => setBody(e.target.value)} />
          </Field>
          <ErrorBox error={err} />
          {hits.length > 0 && (
            <ul className="space-y-1">
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
                  <span>{humanize(h.category)}:</span>
                  <code className="rounded bg-slate-100 dark:bg-white/10 px-1">“{h.match}”</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Follow-up cadences
// ---------------------------------------------------------------------------
function CadenceTab({ settings, manager, onSaved }: { settings: SettingsResp; manager: boolean; onSaved: () => void }) {
  const toast = useToast();
  const current: Record<string, number> = settings.values["followup.cadence_days"] || {};
  const defaults: Record<string, number> = settings.defaults["followup.cadence_days"] || {};
  const [vals, setVals] = useState<Record<string, number | "">>(current);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setVals(current), [settings]); // eslint-disable-line react-hooks/exhaustive-deps
  const stages = [...STAGE_ORDER, ...OUTCOMES].filter((s) => s in current || s in defaults);
  const invalid = stages.some((s) => vals[s] === "" || Number(vals[s]) < 0);
  const dirty = !eq(vals, current);

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await saveSettings({ "followup.cadence_days": Object.fromEntries(stages.map((s) => [s, Number(vals[s])])) });
      toast("success", "Follow-up cadences saved");
      onSaved();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Follow-up cadence by stage"
      subtitle="Days until the next follow-up is scheduled after a candidate enters each stage."
      actions={manager ? <Button variant="primary" size="sm" disabled={!dirty || invalid} loading={busy} onClick={save}>Save</Button> : <ReadOnlyNote />}
      bodyClass="px-0 pb-0"
    >
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full min-w-[480px]">
          <thead className="border-y border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.03]">
            <tr>
              <th className="th">Stage</th>
              <th className="th">Days to next follow-up</th>
              <th className="th">Default</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-white/5">
            {stages.map((s) => (
              <tr key={s}>
                <td className="td font-medium text-slate-700 dark:text-slate-200">
                  {STAGE_LABELS[s] || humanize(s)}
                  {OUTCOMES.includes(s) && <span className="ml-2 text-[11px] font-normal text-slate-400">outcome</span>}
                </td>
                <td className="td">
                  {manager ? (
                    <input
                      type="number"
                      min={0}
                      className="input w-28 py-1 tabular"
                      value={vals[s] ?? ""}
                      onChange={(e) => setVals({ ...vals, [s]: e.target.value === "" ? "" : Number(e.target.value) })}
                    />
                  ) : (
                    <span className="tabular">{current[s]} days</span>
                  )}
                </td>
                <td className="td text-slate-500 tabular">{defaults[s] ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2">
        <ErrorBox error={err} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Guardrails
// ---------------------------------------------------------------------------
type GField = { key: string; label: string; hint: string; unit?: string; kind?: "number" | "list"; min?: number; max?: number };
const GUARDRAIL_GROUPS: { title: string; subtitle: string; fields: GField[] }[] = [
  {
    title: "Outreach",
    subtitle: "Protect candidates from over-contact. Sends beyond these limits are blocked.",
    fields: [
      { key: "outreach.max_per_candidate_7d", label: "Max messages per candidate (7 days)", hint: "Across all channels and sequences", unit: "messages", min: 1 },
      { key: "outreach.min_hours_between", label: "Minimum gap between messages", hint: "To the same candidate", unit: "hours", min: 0 },
      { key: "outreach.sequence_offsets_days", label: "Sequence step offsets", hint: "Days after the first message, comma-separated (e.g. 0, 3, 7)", unit: "days", kind: "list" },
    ],
  },
  {
    title: "Documents",
    subtitle: "Secure portal behaviour and reminders.",
    fields: [
      { key: "documents.reminder_interval_hours", label: "Reminder interval", hint: "Between automatic portal reminders", unit: "hours", min: 1 },
      { key: "documents.max_reminders", label: "Max reminders", hint: "Then the recruiter is notified instead", unit: "reminders", min: 0 },
      { key: "documents.sla_hours", label: "Pending-documents SLA", hint: "Pending longer than this appears in the digest", unit: "hours", min: 1 },
      { key: "documents.portal_ttl_days", label: "Portal link lifetime", hint: "Links expire after this many days", unit: "days", min: 1 },
    ],
  },
  {
    title: "Retention & matching",
    subtitle: "Data minimisation and suggestion thresholds.",
    fields: [
      { key: "retention.days_inactive", label: "Retention after last activity", hint: "Records then enter the retention review queue", unit: "days", min: 30 },
      { key: "matching.min_score_suggest", label: "Minimum match score to suggest", hint: "Candidates below this aren't suggested", unit: "/ 100", min: 0, max: 100 },
    ],
  },
];

const toDisplay = (f: GField, v: any) => (f.kind === "list" ? (Array.isArray(v) ? v.join(", ") : String(v ?? "")) : String(v ?? ""));
function parse(f: GField, s: string): { ok: boolean; value: any } {
  if (f.kind === "list") {
    const parts = s.split(",").map((x) => x.trim()).filter(Boolean);
    const nums = parts.map(Number);
    const ok = parts.length > 0 && nums.every((n) => Number.isInteger(n) && n >= 0) && nums.every((n, i) => i === 0 || n > nums[i - 1]);
    return { ok, value: nums };
  }
  if (s.trim() === "") return { ok: false, value: null };
  const n = Number(s);
  const ok = Number.isFinite(n) && (f.min == null || n >= f.min) && (f.max == null || n <= f.max);
  return { ok, value: n };
}

function GuardrailsTab({ settings, manager, onSaved }: { settings: SettingsResp; manager: boolean; onSaved: () => void }) {
  const toast = useToast();
  const fields = GUARDRAIL_GROUPS.flatMap((g) => g.fields);
  const initial = () => Object.fromEntries(fields.map((f) => [f.key, toDisplay(f, settings.values[f.key])]));
  const [vals, setVals] = useState<Record<string, string>>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setVals(initial()), [settings]); // eslint-disable-line react-hooks/exhaustive-deps

  const parsed = Object.fromEntries(fields.map((f) => [f.key, parse(f, vals[f.key] ?? "")]));
  const invalid = fields.filter((f) => !parsed[f.key].ok);
  const changes = Object.fromEntries(fields.filter((f) => parsed[f.key].ok && !eq(parsed[f.key].value, settings.values[f.key])).map((f) => [f.key, parsed[f.key].value]));

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await saveSettings(changes);
      toast("success", `Saved ${Object.keys(changes).length} setting${Object.keys(changes).length === 1 ? "" : "s"}`);
      onSaved();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {manager ? <span className="text-xs text-slate-500">Changes apply immediately to workflows and are recorded in the audit log.</span> : <ReadOnlyNote />}
        {manager && (
          <Button variant="primary" disabled={!Object.keys(changes).length || invalid.length > 0} loading={busy} onClick={save}>
            Save changes
          </Button>
        )}
      </div>
      <ErrorBox error={err} />
      <div className="grid gap-4 lg:grid-cols-3">
        {GUARDRAIL_GROUPS.map((g) => (
          <Card key={g.title} title={g.title} subtitle={g.subtitle}>
            <div className="space-y-4">
              {g.fields.map((f) => {
                const bad = !parsed[f.key].ok;
                return (
                  <div key={f.key}>
                    <label className="label" htmlFor={f.key}>
                      {f.label}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        id={f.key}
                        className={cx("input tabular", bad && manager && "border-red-400 focus:ring-red-400/50")}
                        type={f.kind === "list" ? "text" : "number"}
                        min={f.min}
                        max={f.max}
                        disabled={!manager}
                        value={vals[f.key] ?? ""}
                        onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}
                      />
                      {f.unit && <span className="text-xs text-slate-500 whitespace-nowrap">{f.unit}</span>}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1">
                      {f.hint} · default {toDisplay(f, settings.defaults[f.key])}
                    </p>
                    {bad && manager && (
                      <p className="text-[11px] text-red-600 dark:text-red-300 mt-0.5">
                        {f.kind === "list" ? "Use increasing whole numbers, comma-separated" : `Enter a number${f.min != null ? ` ≥ ${f.min}` : ""}${f.max != null ? ` and ≤ ${f.max}` : ""}`}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
        ))}
      </div>
      <Card title="Other scheduled settings" subtitle="Shown for reference">
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="label">Follow-up reminder time</dt>
            <dd className="tabular">{settings.values["followup.reminder_time"]} ET</dd>
          </div>
          <div>
            <dt className="label">Weekly report</dt>
            <dd>
              {DOW[settings.values["report.weekly_day"]] || settings.values["report.weekly_day"]} at {settings.values["report.weekly_time"]} ET
            </dd>
          </div>
          <div>
            <dt className="label">Authorized sharing domains</dt>
            <dd>{(settings.values["compliance.authorized_domains"] || []).join(", ")}</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------
function IntegrationsTab() {
  const { data, error, loading } = useApi<any[]>("/api/integrations");
  if (loading && !data) return <Loading />;
  return (
    <div className="space-y-3">
      <ErrorBox error={error} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data?.map((i) => (
          <div key={i.key} className="card px-4 py-3 flex flex-col">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <Plug className="h-4 w-4 text-slate-400 shrink-0" />
                <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">{i.name}</span>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {i.connected ? (
                <Badge tone="green">
                  <CheckCircle2 className="h-3 w-3" />
                  Connected
                </Badge>
              ) : (
                <Badge tone="gray">
                  <MinusCircle className="h-3 w-3" />
                  Not connected
                </Badge>
              )}
              <code className="text-[11px] text-slate-500">{i.status}</code>
            </div>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-300 break-words">{i.detail}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500">Credentials are configured through environment variables on the server; they're never shown in the app.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users & roles (admin)
// ---------------------------------------------------------------------------
const ROLES = ["recruiter", "ta_lead", "coordinator", "payroll", "immigration", "onboarding", "marketing", "admin"];

function UsersTab() {
  const { user: me } = useAuth();
  const toast = useToast();
  const { data, error, loading, setData } = useApi<any[]>("/api/users");
  // GET /api/users doesn't include is_active; in dev mode /api/auth/dev-users lists only active users.
  const [activeIds, setActiveIds] = useState<Set<number> | null>(null);
  useEffect(() => {
    get<any[]>("/api/auth/dev-users")
      .then((list) => setActiveIds(list.length ? new Set(list.map((u) => u.id)) : null))
      .catch(() => setActiveIds(null));
  }, []);
  const [override, setOverride] = useState<Record<number, boolean>>({});
  const isActive = (u: any) => (u.id in override ? override[u.id] : u.is_active ?? (activeIds ? activeIds.has(u.id) : true));
  const [busyId, setBusyId] = useState<number | null>(null);

  async function update(u: any, body: any, msg: string) {
    setBusyId(u.id);
    try {
      const r = await patch<any>(`/api/users/${u.id}`, body);
      setData((data || []).map((x) => (x.id === u.id ? { ...x, ...r } : x)));
      if ("is_active" in body) setOverride({ ...override, [u.id]: body.is_active });
      toast("success", msg);
    } catch (e) {
      toast("error", errMsg(e));
    } finally {
      setBusyId(null);
    }
  }

  const [adding, setAdding] = useState(false);
  const [nu, setNu] = useState({ name: "", email: "", role: "recruiter" });
  const [addErr, setAddErr] = useState<string | null>(null);
  const [addBusy, setAddBusy] = useState(false);
  async function add() {
    setAddBusy(true);
    setAddErr(null);
    try {
      const r = await post<any>("/api/users", { name: nu.name.trim(), email: nu.email.trim(), role: nu.role });
      setData([...(data || []), r].sort((a, b) => a.name.localeCompare(b.name)));
      setOverride({ ...override, [r.id]: true });
      toast("success", `${r.name} added`);
      setAdding(false);
      setNu({ name: "", email: "", role: "recruiter" });
    } catch (e) {
      setAddErr(errMsg(e));
    } finally {
      setAddBusy(false);
    }
  }
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(nu.email.trim());

  if (loading && !data) return <Loading />;
  return (
    <div className="space-y-3">
      <ErrorBox error={error} />
      <Card
        title="Users & roles"
        subtitle="Role controls what each person can see. Team roles (Payroll, Immigration, Onboarding, Marketing, Coordinator) only see their own tickets."
        actions={
          <Button variant="primary" size="sm" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>
            Add user
          </Button>
        }
        bodyClass="px-0 pb-0"
      >
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full min-w-[720px]">
            <thead className="border-y border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.03]">
              <tr>
                <th className="th">Name</th>
                <th className="th">Email</th>
                <th className="th">Role</th>
                <th className="th">Digest</th>
                <th className="th">Active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-white/5">
              {data?.map((u) => {
                const self = u.id === me?.id;
                const active = isActive(u);
                return (
                  <tr key={u.id} className={cx(!active && "opacity-60")}>
                    <td className="td font-medium text-slate-800 dark:text-slate-100 whitespace-nowrap">
                      {u.name}
                      {self && <span className="ml-1 text-xs font-normal text-slate-400">(you)</span>}
                    </td>
                    <td className="td text-slate-600 dark:text-slate-300">{u.email}</td>
                    <td className="td">
                      <select
                        className="input w-40 py-1"
                        value={u.role}
                        disabled={busyId === u.id || self}
                        title={self ? "You can't change your own role" : undefined}
                        onChange={(e) => update(u, { role: e.target.value }, `${u.name} is now ${ROLE_LABELS[e.target.value]}`)}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r] || r}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="td text-slate-600 dark:text-slate-300">{u.digest_enabled ? "On" : "Off"}</td>
                    <td className="td">
                      <Toggle
                        checked={active}
                        disabled={busyId === u.id || self}
                        onChange={(val) => update(u, { is_active: val }, val ? `${u.name} reactivated` : `${u.name} deactivated`)}
                        label={<span className="text-xs text-slate-500">{active ? "Active" : "Inactive"}</span>}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add user"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} loading={addBusy} disabled={!nu.name.trim() || !emailOk} onClick={add}>
              Add user
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Full name">
            <input className="input" value={nu.name} onChange={(e) => setNu({ ...nu, name: e.target.value })} />
          </Field>
          <Field label="Work email" hint="Must match their SSO identity.">
            <input className="input" type="email" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
          </Field>
          <Field label="Role">
            <select className="input" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r] || r}
                </option>
              ))}
            </select>
          </Field>
          <ErrorBox error={addErr} />
        </div>
      </Modal>
    </div>
  );
}

