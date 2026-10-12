import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlarmClock, CalendarCheck, Check, Flame, Inbox, Mail, Phone, PhoneCall, RefreshCw, SkipForward, TicketCheck, UserPlus, X } from "lucide-react";
import { DraftCard } from "../components/DraftCard";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, ScoreBadge, StageBadge, Stat, Tabs, useToast } from "../components/ui";
import { errMsg, post } from "../lib/api";
import { isManager, useAuth } from "../lib/auth";
import { durationLabel, fmtDateTime, relTime, TEAM_LABELS } from "../lib/format";
import { useApi } from "../lib/hooks";

export default function Home() {
  const { user } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [viewAs, setViewAs] = useState<number | "">("");
  const { data: users } = useApi<any[]>(isManager(user) ? "/api/users" : null);
  const { data, error, loading, reload } = useApi<any>(`/api/home${viewAs ? `?user_id=${viewAs}` : ""}`, [viewAs]);
  const [fuTab, setFuTab] = useState("overdue");

  async function act(fn: () => Promise<any>, ok: string) {
    try {
      await fn();
      toast("success", ok);
      reload();
    } catch (e) {
      toast("error", errMsg(e));
    }
  }

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const pendingCalls = data.call_list.filter((c: any) => c.status === "pending");
  const fus = fuTab === "overdue" ? data.follow_ups_overdue : data.follow_ups_today;

  return (
    <>
      <PageHeader
        title={`${greet}, ${(viewAs ? data.user.name : user?.name || "").split(" ")[0]}`}
        subtitle={`${new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })} · The admin is handled — here's who to talk to today.`}
        actions={
          <>
            {isManager(user) && (
              <select className="input w-48" value={viewAs} onChange={(e) => setViewAs(e.target.value ? Number(e.target.value) : "")}>
                <option value="">My view</option>
                {(users || [])
                  .filter((u) => u.role === "recruiter")
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      View as {u.name}
                    </option>
                  ))}
              </select>
            )}
            <Button icon={<RefreshCw className="h-4 w-4" />} onClick={reload}>
              Refresh
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
        <Stat label="Calls on today's list" value={pendingCalls.length} icon={<PhoneCall className="h-4 w-4" />} />
        <Stat label="Hot replies" value={data.hot_replies.length} sub={data.hot_replies.length ? "Reach out first" : "None waiting"} tone={data.hot_replies.length ? "bad" : "neutral"} icon={<Flame className="h-4 w-4" />} />
        <Stat label="Follow-ups today" value={data.follow_ups_today.length} icon={<CalendarCheck className="h-4 w-4" />} />
        <Stat label="Overdue" value={data.follow_ups_overdue.length} tone={data.follow_ups_overdue.length ? "bad" : "good"} sub={data.follow_ups_overdue.length ? "Needs attention" : "All caught up"} icon={<AlarmClock className="h-4 w-4" />} />
        <Stat label="Drafts to approve" value={data.drafts.length} icon={<Mail className="h-4 w-4" />} />
      </div>

      <div className="grid gap-5 xl:grid-cols-5">
        <div className="space-y-5 xl:col-span-3">
          {data.hot_replies.length > 0 && (
            <Card title={<span className="flex items-center gap-1.5"><Flame className="h-4 w-4 text-red-600" /> Hot replies — interested, not yet contacted</span>} className="border-red-200 dark:border-red-400/30">
              <div className="divide-y divide-slate-100 dark:divide-white/5">
                {data.hot_replies.map((c: any) => (
                  <div key={c.id} className="flex flex-wrap items-center gap-3 py-2">
                    <div className="flex-1 min-w-[12rem]">
                      <Link to={`/candidates/${c.id}`} className="font-medium text-brand-800 dark:text-brand-200 hover:underline">
                        {c.full_name}
                      </Link>
                      <div className="text-xs text-slate-500">{c.headline}</div>
                    </div>
                    <ScoreBadge score={c.fit_score} />
                    <Button size="sm" variant="primary" icon={<Phone className="h-3.5 w-3.5" />} onClick={() => nav(`/candidates/${c.id}?action=call`)}>
                      Call
                    </Button>
                    <Button size="sm" icon={<Mail className="h-3.5 w-3.5" />} onClick={() => nav(`/candidates/${c.id}?action=draft`)}>
                      Draft
                    </Button>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card
            title="Today's call list"
            subtitle="Ranked by match score and time since last contact. Recently contacted people are left out."
            actions={
              !viewAs && (
                <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => act(() => post("/api/call-list/rebuild"), "Call list rebuilt")}>
                  Rebuild
                </Button>
              )
            }
          >
            {data.call_list.length === 0 ? (
              <Empty icon={<PhoneCall className="h-8 w-8" />} title="No calls queued">The list is built every weekday at 6:30 AM.</Empty>
            ) : (
              <div className="overflow-x-auto -mx-4">
                <table className="w-full min-w-[560px]">
                  <thead>
                    <tr className="border-b border-slate-100 dark:border-white/5">
                      <th className="th w-10">#</th>
                      <th className="th">Candidate</th>
                      <th className="th">Why</th>
                      <th className="th">Stage</th>
                      <th className="th text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.call_list.map((i: any) => (
                      <tr key={i.id} className={i.status !== "pending" ? "opacity-50" : "border-b border-slate-50 dark:border-white/5"}>
                        <td className="td tabular text-slate-400">{i.rank}</td>
                        <td className="td">
                          <Link to={`/candidates/${i.candidate.id}`} className="font-medium text-brand-800 dark:text-brand-200 hover:underline">
                            {i.candidate.full_name}
                          </Link>
                          <div className="text-xs text-slate-500">{i.candidate.phone ? formatPhone(i.candidate.phone) : "No phone"}</div>
                        </td>
                        <td className="td text-xs text-slate-600 dark:text-slate-300">{i.reason}</td>
                        <td className="td">
                          <StageBadge stage={i.candidate.stage} />
                        </td>
                        <td className="td text-right whitespace-nowrap">
                          {i.status === "pending" ? (
                            <>
                              <Button size="sm" variant="primary" icon={<Phone className="h-3.5 w-3.5" />} onClick={() => nav(`/candidates/${i.candidate.id}?action=call&calllist=${i.id}`)}>
                                Call
                              </Button>{" "}
                              <Button size="sm" variant="ghost" icon={<SkipForward className="h-3.5 w-3.5" />} onClick={() => act(() => post(`/api/call-list/${i.id}?status=skipped`), "Skipped")}>
                                Skip
                              </Button>
                            </>
                          ) : (
                            <Badge>{i.status}</Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Follow-ups" bodyClass="pt-0">
            <Tabs
              value={fuTab}
              onChange={setFuTab}
              tabs={[
                { key: "overdue", label: "Overdue", count: data.follow_ups_overdue.length },
                { key: "today", label: "Due today", count: data.follow_ups_today.length },
              ]}
            />
            {fus.length === 0 ? (
              <Empty icon={<Check className="h-8 w-8" />} title={fuTab === "overdue" ? "Nothing overdue" : "Nothing else due today"} />
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-white/5">
                {fus.map((f: any) => (
                  <div key={f.id} className="flex flex-wrap items-center gap-2 py-2.5">
                    <div className="flex-1 min-w-[12rem]">
                      <Link to={`/candidates/${f.candidate.id}`} className="font-medium text-brand-800 dark:text-brand-200 hover:underline">
                        {f.candidate.full_name}
                      </Link>
                      <div className="text-xs text-slate-500">
                        {f.reason} · due {fmtDateTime(f.due_at)}
                      </div>
                    </div>
                    <StageBadge stage={f.candidate.stage} />
                    <Button size="sm" onClick={() => nav(`/candidates/${f.candidate.id}?action=draft&kind=follow_up`)}>
                      Draft
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => act(() => post(`/api/candidates/${f.candidate.id}/snooze?days=1`), "Snoozed until tomorrow")}>
                      Snooze
                    </Button>
                    <Button size="sm" variant="ghost" icon={<Check className="h-3.5 w-3.5" />} onClick={() => act(() => post(`/api/candidates/${f.candidate.id}/follow-ups/${f.id}/done`), "Follow-up done")}>
                      Done
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-5 xl:col-span-2">
          <Card title="Drafts awaiting approval" subtitle="Nothing personalized is sent until you approve it. LinkedIn messages are always sent by you.">
            {data.drafts.length === 0 ? (
              <Empty icon={<Inbox className="h-8 w-8" />} title="No drafts waiting" />
            ) : (
              <div className="space-y-3">
                {data.drafts.slice(0, 8).map((d: any) => (
                  <DraftCard key={d.id} draft={d} onChange={reload} />
                ))}
              </div>
            )}
          </Card>

          <Card title="New applicants" subtitle="Ranked by fit — confirm the shortlist." actions={<UserPlus className="h-4 w-4 text-slate-400" />}>
            {data.applicants.length === 0 ? (
              <Empty title="No new applicants in the last 3 days" />
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-white/5">
                {data.applicants.map((a: any) => (
                  <div key={a.id} className="flex items-center gap-2 py-2">
                    <div className="flex-1 min-w-0">
                      <Link to={`/candidates/${a.candidate.id}`} className="font-medium text-sm text-brand-800 dark:text-brand-200 hover:underline">
                        {a.candidate.full_name}
                      </Link>
                      <div className="text-xs text-slate-500 truncate">
                        {a.requirement_title || "General"} · {a.source} · {relTime(a.created_at)}
                      </div>
                    </div>
                    <ScoreBadge score={a.fit_score} />
                    {a.shortlist_status === "suggested" && <Badge tone="green">Suggested</Badge>}
                    <button title="Shortlist" className="rounded p-1 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10" onClick={() => act(() => post(`/api/applications/${a.id}/shortlist?decision=shortlisted`), "Shortlisted")}>
                      <Check className="h-4 w-4" />
                    </button>
                    <button title="Not a fit" className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10" onClick={() => act(() => post(`/api/applications/${a.id}/shortlist?decision=rejected`), "Removed from shortlist")}>
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Delegated tickets" actions={<Link to="/delegation" className="text-xs text-brand-700 dark:text-brand-200 hover:underline">Delegation Center →</Link>}>
            {data.tickets.length === 0 ? (
              <Empty icon={<TicketCheck className="h-8 w-8" />} title="No open tickets" />
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-white/5">
                {data.tickets.slice(0, 8).map((t: any) => {
                  const secs = (new Date(t.due_at).getTime() - Date.now()) / 1000;
                  return (
                    <div key={t.id} className="py-2">
                      <div className="flex items-center gap-2">
                        <Badge tone="brand">{TEAM_LABELS[t.team]}</Badge>
                        <span className="text-sm flex-1 truncate">{t.subject}</span>
                      </div>
                      <div className={`text-xs mt-0.5 ${secs < 0 || t.breached ? "text-red-700 dark:text-red-300 font-medium" : "text-slate-500"}`}>{durationLabel(secs)}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

export function formatPhone(p: string) {
  const d = p.replace(/\D/g, "");
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : p;
}
