"""Weekly management report (Monday 8 AM): PDF attachment + email summary to TA leads."""
from __future__ import annotations

import io
from datetime import timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import HABITS, STAGE_LABELS
from ..engine import analytics
from ..mail import send_email
from ..models import HabitFlag, Ticket, User
from ..util import now, to_local

NAVY = colors.HexColor("#0f3d5e")


def build_data(db: Session) -> dict:
    since = now() - timedelta(days=7)
    recruiters = db.query(User).filter(User.role == "recruiter", User.is_active.is_(True)).order_by(User.name).all()
    per = []
    for u in recruiters:
        a = analytics.activity(db, since, u.id)
        q = analytics.quality(db, since, u.id)
        per.append({"name": u.name, **a, **q})
    habits = dict(db.query(HabitFlag.habit, func.count(HabitFlag.id)).filter(HabitFlag.created_at >= since).group_by(HabitFlag.habit).all())
    breached = db.query(func.count(Ticket.id)).filter(Ticket.breached.is_(True), Ticket.created_at >= since).scalar() or 0
    return {
        "period": f"{to_local(since):%b %d} – {to_local(now()):%b %d, %Y}",
        "team_activity": analytics.activity(db, since),
        "team_quality": analytics.quality(db, since),
        "pipeline": analytics.pipeline(db),
        "dq": analytics.data_quality(db),
        "impact": analytics.impact(db),
        "per_recruiter": per,
        "habits": habits,
        "breached_tickets": breached,
    }


def render_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    ss = getSampleStyleSheet()
    h1, h2, body = ss["Title"], ss["Heading2"], ss["BodyText"]
    h1.textColor = NAVY
    h2.textColor = NAVY
    story = [Paragraph("Cognitech Talent Acquisition — Weekly Report", h1), Paragraph(data["period"], body), Spacer(1, 12)]

    def table(rows, widths=None, header=True):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        style = [("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(style))
        return t

    a, q, p, dq, imp = data["team_activity"], data["team_quality"], data["pipeline"], data["dq"], data["impact"]
    story += [Paragraph("Team summary", h2)]
    story.append(
        table(
            [
                ["Calls", "LinkedIn conn.", "LinkedIn msgs", "Emails", "Profiles", "Contacts"],
                [a["calls"], a["linkedin_connections"], a["linkedin_messages"], a["emails_sent"], a["profiles_added"], a["unique_contacts"]],
                ["Meaningful conv.", "Interested", "Qualified", "Docs received", "Onboarded", "Placements"],
                [q["meaningful_conversations"], q["interested"], q["qualified"], q["documents_received"], q["onboarded"], p["placements"]],
            ]
        )
    )
    story += [Spacer(1, 10), Paragraph("By recruiter", h2)]
    rows = [["Recruiter", "Calls", "Emails", "LinkedIn", "Meaningful", "Qualified", "Onboarded"]]
    for r in data["per_recruiter"]:
        rows.append([r["name"], r["calls"], r["emails_sent"], r["linkedin_connections"] + r["linkedin_messages"], r["meaningful_conversations"], r["qualified"], r["onboarded"]])
    story.append(table(rows))
    story += [Spacer(1, 10), Paragraph("Pipeline", h2)]
    stage_rows = [["Stage", "Candidates"]] + [[STAGE_LABELS[s], n] for s, n in p["by_stage"].items()]
    story.append(table(stage_rows, [3 * inch, 1.2 * inch]))
    story += [Spacer(1, 10), Paragraph(f"Data quality: {dq['score']} / 100", h2)]
    m = dq["metrics"]
    story.append(
        table(
            [
                ["Accuracy", "Open duplicates", "Stale records", "Follow-up compliance", "Doc completeness"],
                [f"{m['accuracy']:.0%}", m["open_duplicates"], m["stale_records"], f"{m['follow_up_compliance']:.0%}", f"{m['document_completeness']:.0%}"],
            ]
        )
    )
    story += [Spacer(1, 10), Paragraph("Habits worth breaking (flags this week)", h2)]
    hrows = [["Habit", "Flags"]] + [[HABITS[h], n] for h, n in sorted(data["habits"].items(), key=lambda x: -x[1])] or [["None", 0]]
    if len(hrows) == 1:
        hrows.append(["No flags this week", 0])
    story.append(table(hrows, [5 * inch, 0.8 * inch]))
    story += [Spacer(1, 10), Paragraph("Automation impact", h2)]
    pr = imp["per_recruiter_week"]
    story.append(
        Paragraph(
            f"Estimated manual time per recruiter: {pr['baseline_hours']} h/week before, {pr['after_hours']} h/week after "
            f"(<b>{pr['hours_saved']} h saved, {pr['percent_reduction']}%</b>). Measured from workflow runs in the last 7 days: "
            f"{imp['measured_last_7d']['hours_saved_team']} h across the team. Delegated tickets past SLA this week: {data['breached_tickets']}.",
            body,
        )
    )
    doc.build(story)
    return buf.getvalue()


def send_weekly_report(db: Session) -> dict:
    data = build_data(db)
    pdf = render_pdf(data)
    q, a, dq = data["team_quality"], data["team_activity"], data["dq"]
    text = (
        f"Weekly report for {data['period']}\n\n"
        f"Activity: {a['calls']} calls, {a['emails_sent']} emails, {a['linkedin_connections'] + a['linkedin_messages']} LinkedIn touches, {a['profiles_added']} new profiles.\n"
        f"Quality: {q['meaningful_conversations']} meaningful conversations, {q['qualified']} qualified, {q['documents_received']} docs received, {q['onboarded']} onboarded.\n"
        f"Pipeline: {data['pipeline']['active']} active, {data['pipeline']['placements']} placed.\n"
        f"Data quality: {dq['score']}/100.\n"
        f"Habit flags this week: {sum(data['habits'].values())}.\n\nFull report attached (PDF)."
    )
    sent = 0
    for u in db.query(User).filter(User.role.in_(["ta_lead"]), User.is_active.is_(True)).all():
        send_email(db, u.email, f"Weekly TA report — {data['period']}", text, kind="report", user_id=u.id, attachments=[{"filename": "cognitech-weekly-report.pdf", "content": pdf, "content_type": "application/pdf"}])
        sent += 1
    return {"sent": sent, "pdf_bytes": len(pdf)}
