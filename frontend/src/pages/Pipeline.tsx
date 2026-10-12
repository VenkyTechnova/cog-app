import { useState } from "react";
import { Link } from "react-router-dom";
import { AlarmClock, Flame, GripVertical, Lock } from "lucide-react";
import { Button, cx, ErrorBox, Field, Loading, Modal, PageHeader, ScoreBadge, useToast } from "../components/ui";
import { errMsg, post } from "../lib/api";
import { STAGE_LABELS } from "../lib/format";
import { useApi } from "../lib/hooks";

const GATED = ["docs_requested", "docs_received", "onboarding", "marketing_pipeline", "placed"];

export default function Pipeline() {
  const toast = useToast();
  const [owner, setOwner] = useState("");
  const [req, setReq] = useState("");
  const [q, setQ] = useState("");
  const { data: users } = useApi<any[]>("/api/users");
  const { data: reqs } = useApi<any[]>("/api/requirements");
  const { data, error, loading, reload, setData } = useApi<any>(`/api/pipeline?${owner ? `owner_id=${owner}&` : ""}${req ? `requirement_id=${req}` : ""}`, [owner, req]);
  const [drag, setDrag] = useState<{ card: any; from: string } | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [move, setMove] = useState<{ card: any; from: string; to: string } | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirmMove() {
    if (!move) return;
    setBusy(true);
    setErr(null);
    try {
      await post(`/api/candidates/${move.card.id}/stage`, { to: move.to, reason });
      toast("success", `${move.card.full_name} → ${STAGE_LABELS[move.to]}`);
      setMove(null);
      setReason("");
      reload();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <Loading />;
  const ql = q.toLowerCase();
  const columns = (data?.columns || []).map((col: any) => ({ ...col, cards: ql ? col.cards.filter((c: any) => c.full_name.toLowerCase().includes(ql) || (c.skills || []).join(" ").toLowerCase().includes(ql)) : col.cards }));

  return (
    <>
      <PageHeader
        title="Pipeline"
        subtitle="Most moves happen automatically from events. Drag a card to override — a reason is always required."
        actions={
          <>
            <input className="input w-48" placeholder="Filter by name or skill" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className="input w-44" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">All recruiters</option>
              {(users || []).filter((u) => u.role === "recruiter").map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
            <select className="input w-56" value={req} onChange={(e) => setReq(e.target.value)}>
              <option value="">All requirements</option>
              {(reqs || []).map((r) => (
                <option key={r.id} value={r.id}>
                  Matches for {r.title}
                </option>
              ))}
            </select>
          </>
        }
      />
      <ErrorBox error={error} />
      <div className="flex gap-3 overflow-x-auto scrollbar-thin pb-4 -mx-4 px-4 sm:mx-0 sm:px-0" style={{ minHeight: "70vh" }}>
        {columns.map((col: any, i: number) => {
          const isOutcome = i >= 9;
          return (
            <div
              key={col.stage}
              className={cx("w-64 shrink-0 rounded-xl flex flex-col", over === col.stage ? "bg-brand-50 ring-2 ring-brand-300 dark:bg-brand-500/10" : isOutcome ? "bg-slate-100/60 dark:bg-white/[.03]" : "bg-slate-100 dark:bg-white/5")}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(col.stage);
              }}
              onDragLeave={() => setOver(null)}
              onDrop={(e) => {
                e.preventDefault();
                setOver(null);
                if (drag && drag.from !== col.stage) {
                  setErr(null);
                  setMove({ card: drag.card, from: drag.from, to: col.stage });
                }
                setDrag(null);
              }}
            >
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1">
                  {GATED.includes(col.stage) && <Lock className="h-3 w-3 text-slate-400" />}
                  {i < 9 ? `${i + 1}. ` : ""}
                  {col.label}
                </span>
                <span className="text-[11px] tabular rounded-full bg-white dark:bg-white/10 px-1.5 text-slate-500">{col.cards.length}</span>
              </div>
              <div className="flex-1 space-y-2 px-2 pb-2 overflow-y-auto max-h-[70vh] scrollbar-thin">
                {col.cards.map((c: any) => (
                  <div
                    key={c.id}
                    draggable
                    onDragStart={() => setDrag({ card: c, from: col.stage })}
                    onDragEnd={() => setDrag(null)}
                    className={cx("card p-2.5 cursor-grab active:cursor-grabbing", drag?.card.id === c.id && "opacity-50")}
                  >
                    <div className="flex items-start gap-1">
                      <GripVertical className="h-4 w-4 text-slate-300 shrink-0 mt-0.5" />
                      <div className="min-w-0 flex-1">
                        <Link to={`/candidates/${c.id}`} className="text-sm font-medium hover:underline block truncate">
                          {c.full_name}
                        </Link>
                        <div className="text-[11px] text-slate-500 truncate">{c.headline || (c.skills || []).slice(0, 3).join(", ")}</div>
                        <div className="flex items-center gap-1.5 mt-1.5">
                          <ScoreBadge score={c.fit_score} />
                          {c.hot_reply && <Flame className="h-3.5 w-3.5 text-red-600" aria-label="Hot reply" />}
                          {c.follow_up_overdue && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] text-red-700 dark:text-red-300">
                              <AlarmClock className="h-3 w-3" /> overdue
                            </span>
                          )}
                          <span className="ml-auto text-[10px] text-slate-400">{(users || []).find((u) => u.id === c.owner_id)?.name.split(" ")[0] || "—"}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <Modal
        open={!!move}
        onClose={() => setMove(null)}
        title="Confirm manual stage change"
        footer={
          <>
            <Button variant="ghost" onClick={() => setMove(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} disabled={reason.trim().length < 3} onClick={confirmMove}>
              Move
            </Button>
          </>
        }
      >
        {move && (
          <>
            <p className="text-sm mb-3">
              Move <strong>{move.card.full_name}</strong> from {STAGE_LABELS[move.from]} to <strong>{STAGE_LABELS[move.to]}</strong>?
            </p>
            <ErrorBox error={err} />
            <div className="mt-2">
              <Field label="Reason (required, audit-logged)">
                <textarea className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
              </Field>
            </div>
            {GATED.includes(move.to) && <p className="text-xs text-slate-500 mt-2"><Lock className="inline h-3 w-3" /> This stage requires a completed comfort check and recorded consent.</p>}
          </>
        )}
      </Modal>
    </>
  );
}
