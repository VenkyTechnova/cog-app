import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Check, Copy, Linkedin, Mail, MessageSquare, Pencil, ShieldAlert, X } from "lucide-react";
import { errMsg, patch, post } from "../lib/api";
import { humanize, relTime, TEAM_LABELS } from "../lib/format";
import { Badge, Button, cx, useToast } from "./ui";

const KIND_LABEL: Record<string, string> = {
  linkedin_note: "LinkedIn note",
  intro_message: "LinkedIn intro",
  cold_email: "Cold email",
  follow_up: "Follow-up",
  reengagement: "Re-engagement",
  process_summary: "Process summary",
  offer_explainer: "Offer explainer",
  check_in: "Check-in",
  dm: "Direct message",
};

export function DraftCard({ draft, onChange, showCandidate = true, candidateId }: { draft: any; onChange: () => void; showCandidate?: boolean; candidateId?: number }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(draft.subject || "");
  const [body, setBody] = useState(draft.body || "");
  const [busy, setBusy] = useState<string | null>(null);
  const comp = draft.compliance || {};
  const blocked = draft.status === "blocked" || comp.blocked;
  const isLinkedIn = draft.channel !== "email";
  const icon = draft.channel === "linkedin" ? <Linkedin className="h-3.5 w-3.5" /> : draft.channel === "dm" ? <MessageSquare className="h-3.5 w-3.5" /> : <Mail className="h-3.5 w-3.5" />;

  async function act(name: string, fn: () => Promise<any>, ok: string) {
    setBusy(name);
    try {
      await fn();
      toast("success", ok);
      onChange();
    } catch (e) {
      toast("error", errMsg(e));
      onChange();
    } finally {
      setBusy(null);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(draft.body);
      toast("info", "Copied — paste it into LinkedIn, then mark it sent.");
    } catch {
      toast("error", "Couldn't access the clipboard");
    }
  }

  return (
    <div className={cx("rounded-lg border p-3", blocked ? "border-red-300 bg-red-50/50 dark:border-red-400/30 dark:bg-red-500/5" : "border-slate-200 dark:border-white/10")}>
      <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
        <Badge tone={isLinkedIn ? "blue" : "brand"}>
          {icon}
          {KIND_LABEL[draft.kind] || humanize(draft.kind)}
        </Badge>
        {draft.sequence_id && <Badge tone="violet">Sequence · 3 steps</Badge>}
        {draft.status === "manual_send" && <Badge tone="amber">Approved · send manually</Badge>}
        {blocked && (
          <Badge tone="red">
            <ShieldAlert className="h-3 w-3" /> Blocked
          </Badge>
        )}
        {comp.generic && !blocked && (
          <Badge tone="amber" title="No personal detail found">
            <AlertTriangle className="h-3 w-3" /> Generic
          </Badge>
        )}
        {draft.generated_by === "llm" && <Badge>AI</Badge>}
        <span className="ml-auto text-[11px] text-slate-400">{relTime(draft.created_at)}</span>
      </div>
      {showCandidate && draft.candidate && (
        <div className="text-sm mb-1">
          To{" "}
          <Link to={`/candidates/${draft.candidate.id}`} className="font-medium text-brand-800 dark:text-brand-200 hover:underline">
            {draft.candidate.full_name}
          </Link>
          {draft.requirement_title && <span className="text-slate-500"> · re {draft.requirement_title}</span>}
        </div>
      )}
      {editing ? (
        <div className="space-y-2">
          {!isLinkedIn && <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" />}
          <textarea className="input font-mono text-xs" rows={10} value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
      ) : (
        <>
          {draft.subject && <div className="text-sm font-medium text-slate-800 dark:text-slate-100">{draft.subject}</div>}
          <pre className="whitespace-pre-wrap font-sans text-xs text-slate-600 dark:text-slate-300 max-h-40 overflow-y-auto mt-1">{draft.body}</pre>
        </>
      )}
      {blocked && comp.hits?.length > 0 && (
        <div className="mt-2 rounded-md bg-red-100/70 dark:bg-red-500/10 px-2 py-1.5 text-xs text-red-800 dark:text-red-200">
          <div className="font-medium">Contains statements recruiters can't make: {comp.hits.filter((h: any) => h.severity === "block").map((h: any) => `"${h.match}"`).join(", ")}</div>
          {Object.entries(comp.route_to || {}).map(([team, msg]) => (
            <div key={team}>
              → {String(msg)}{" "}
              {(candidateId || draft.candidate?.id) && (
                <button
                  className="underline font-medium"
                  onClick={() =>
                    act("delegate", () => post(`/api/candidates/${candidateId || draft.candidate.id}/delegate`, { team, subject: `Candidate question (${TEAM_LABELS[team]})`, description: draft.body.slice(0, 1500), acknowledge_candidate: true }), `Delegated to ${TEAM_LABELS[team]}`)
                  }
                >
                  Delegate now
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {comp.too_long && <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">LinkedIn notes must be 5 lines or fewer.</div>}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {editing ? (
          <>
            <Button size="sm" variant="primary" loading={busy === "save"} onClick={() => act("save", () => patch(`/api/drafts/${draft.id}`, { subject, body }), "Draft updated").then(() => setEditing(false))} icon={<Check className="h-3.5 w-3.5" />}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            {draft.status === "manual_send" ? (
              <>
                <Button size="sm" icon={<Copy className="h-3.5 w-3.5" />} onClick={copy}>
                  Copy
                </Button>
                <Button size="sm" variant="primary" loading={busy === "sent"} onClick={() => act("sent", () => post(`/api/drafts/${draft.id}/mark-sent`), "Logged as sent on LinkedIn")}>
                  Mark sent
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="primary"
                disabled={blocked}
                loading={busy === "approve"}
                icon={<Check className="h-3.5 w-3.5" />}
                onClick={() => act("approve", () => post(`/api/drafts/${draft.id}/approve`), isLinkedIn ? "Approved — copy it into LinkedIn" : draft.sequence_id ? "Sequence approved — step 1 sent" : "Approved and sent")}
              >
                {isLinkedIn ? "Approve" : draft.sequence_id ? "Approve sequence" : "Approve & send"}
              </Button>
            )}
            {draft.status !== "manual_send" && (
              <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} loading={busy === "reject"} onClick={() => act("reject", () => post(`/api/drafts/${draft.id}/reject`), "Draft discarded")}>
              Discard
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
