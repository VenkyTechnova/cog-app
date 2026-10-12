"""Default message templates, written in the playbook's tone: warm, specific, brief, never pushy.

Placeholders use {{name}}. Templates are seeded into the `email_templates` table and are
editable in Settings. `auto_send_allowed` marks the few system messages the platform may send
without a human approving each one; none of them contain pay, tax or immigration statements.
"""

TEMPLATES = {
    "linkedin_note": {
        "name": "LinkedIn connection note",
        "channel": "linkedin",
        "subject": "",
        "auto_send_allowed": False,
        "description": "≤5 lines, one specific detail, one question. Recruiter edits and sends manually on LinkedIn.",
        "body": (
            "Hi {{first_name}}, I noticed {{specific_detail}}.\n"
            "I'm {{recruiter_first}}, a recruiter at Cognitech Technologies — I work with {{skill_area}} engineers.\n"
            "{{question}}\n"
            "Would be glad to connect."
        ),
    },
    "intro_message": {
        "name": "Company intro (after connection accepted)",
        "channel": "linkedin",
        "subject": "",
        "auto_send_allowed": False,
        "description": "Queued when a LinkedIn connection is marked Connected.",
        "body": (
            "Thanks for connecting, {{first_name}}!\n\n"
            "A quick intro: Cognitech Technologies is an IT consulting and staffing firm that places engineers on "
            "client projects across the US. I reached out because your {{skill_area}} background lines up with work "
            "our clients are hiring for{{req_clause}}.\n\n"
            "No pressure at all — would you be open to a short call this week to hear what you're looking for next?"
        ),
    },
    "cold_email": {
        "name": "Cold email (6-part flow)",
        "channel": "email",
        "subject": "{{skill_area}} opportunity — {{req_title}}",
        "auto_send_allowed": False,
        "description": "Intro → company → opportunity → relevance → CTA → contact.",
        "body": (
            "Hi {{first_name}},\n\n"
            "I'm {{recruiter_first}}, a recruiter with Cognitech Technologies.\n\n"
            "Cognitech is an IT consulting and staffing firm that partners with clients across the US to staff "
            "engineering projects.\n\n"
            "We're currently working on a {{req_title}} role ({{req_arrangement}}{{req_location_clause}}) focused on {{req_skills}}.\n\n"
            "I reached out because {{relevance}}.\n\n"
            "Would you be open to a 15-minute call this week? Just reply with a time that works, or let me know if now isn't the right moment.\n\n"
            "Best,\n{{recruiter_name}}\nCognitech Technologies · {{recruiter_email}}"
        ),
    },
    "follow_up": {
        "name": "Follow-up",
        "channel": "email",
        "subject": "Following up — {{req_title}}",
        "auto_send_allowed": False,
        "description": "Context-aware follow-up. Frequency-capped.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Just following up on my note about the {{req_title}} role. I know inboxes get busy — if the timing "
            "isn't right, no problem at all, and I'm happy to keep you in mind for future {{skill_area}} work.\n\n"
            "If you're open to it, a quick reply with a good time to talk is all I need.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "reengagement": {
        "name": "Re-engagement (new matching requirement)",
        "channel": "email",
        "subject": "A new {{req_title}} role that made me think of you",
        "auto_send_allowed": False,
        "description": "Generated when a new requirement matches a past candidate (Hold / Not Interested / Closed, >90 days).",
        "body": (
            "Hi {{first_name}},\n\n"
            "It's been a while since we last spoke — I hope things are going well.\n\n"
            "A new {{req_title}} role just opened up, and given your experience with {{matched_skills}}, you were one "
            "of the first people I thought of. Would you be open to hearing a bit more? If you're settled right now, "
            "just let me know and I won't keep reaching out.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "process_summary": {
        "name": "Process summary (post-call)",
        "channel": "email",
        "subject": "Summary of our conversation and next steps",
        "auto_send_allowed": True,
        "description": "Approved written summary of the company process, auto-sent after the process-explained call.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Thank you for taking the time to talk today. As promised, here is a written summary of how our process works:\n\n"
            "{{process_items}}\n\n"
            "Questions about payroll are answered in writing by our Payroll team, and questions about work "
            "authorization are handled by our authorized team — please don't hesitate to ask, and I'll route them.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "offer_explainer": {
        "name": "Offer letter / documentation explainer",
        "channel": "email",
        "subject": "About your offer letter and documentation",
        "auto_send_allowed": False,
        "description": "What it is, why it's needed, how it works, who reviews it, what happens next, who will call.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Here's a quick explanation of the offer letter and documentation step:\n\n"
            "• What it is: a written document describing the proposed engagement.\n"
            "• Why it's needed: it records the terms both sides review before anything is final.\n"
            "• How it works: you'll receive it through our secure portal and can review it at your own pace.\n"
            "• Who reviews it: our Onboarding / HR team prepares and reviews it with you.\n"
            "• What happens next: once reviewed and signed, Onboarding confirms the next steps in writing.\n"
            "• Who will contact you: {{recruiter_name}} or a member of our Onboarding team.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "check_in": {
        "name": "Nurture check-in",
        "channel": "email",
        "subject": "Checking in",
        "auto_send_allowed": False,
        "description": "Periodic relationship check-in. Recruiter approves.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Just checking in to see how things are going{{project_clause}}. If anything has changed on your side — "
            "a project wrapping up, a new skill you're focusing on — I'd love to hear about it so I can keep an eye "
            "out for the right fit.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "dm": {
        "name": "Direct message to post respondent",
        "channel": "dm",
        "subject": "",
        "auto_send_allowed": False,
        "description": "Created when a candidate engages with a recruitment post.",
        "body": (
            "Hi {{first_name}}, thanks for engaging with our post about {{post_title}}! "
            "I'd be happy to share more details. What kind of role are you looking for right now?"
        ),
    },
    "doc_request": {
        "name": "Document request (personalized checklist)",
        "channel": "email",
        "subject": "Your secure document checklist",
        "auto_send_allowed": True,
        "description": "Sent automatically once the process is explained and consent is recorded.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Thank you for confirming you'd like to proceed. Based on your situation, here is the short list of "
            "documents we need — nothing more:\n\n"
            "{{checklist}}\n\n"
            "Please upload them through our secure, encrypted portal (please don't send documents by email):\n"
            "{{portal_link}}\n\n"
            "The link is personal to you and expires on {{portal_expiry}}.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "doc_reminder": {
        "name": "Missing document reminder",
        "channel": "email",
        "subject": "Reminder: a few documents are still missing",
        "auto_send_allowed": True,
        "description": "Every 48h until complete, up to 3 reminders, then escalate to the recruiter.",
        "body": (
            "Hi {{first_name}},\n\n"
            "A friendly reminder — we're still missing:\n\n{{checklist}}\n\n"
            "You can upload them here: {{portal_link}}\n\n"
            "If you have any questions or concerns, just reply and {{recruiter_first}} will get back to you.\n\n"
            "Thanks,\nCognitech Talent Acquisition"
        ),
    },
    "ticket_ack": {
        "name": "Question acknowledgment (delegated)",
        "channel": "email",
        "subject": "We've received your question",
        "auto_send_allowed": True,
        "description": "Acknowledgment when a payroll / immigration question is routed to a specialist team.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Thanks for your question. I've passed it to our {{team_label}} team, who are the right people to answer "
            "it accurately. You can expect a written response within {{sla_hours}} hours.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "consent_request": {
        "name": "Consent to proceed",
        "channel": "email",
        "subject": "Please confirm you'd like to proceed",
        "auto_send_allowed": True,
        "description": "E-consent link, timestamped and stored.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Thanks again for our conversation. When you're ready, please confirm you'd like to proceed using this "
            "secure link: {{consent_link}}\n\n"
            "There's no rush, and you can ask any questions first.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
    "onboarding_welcome": {
        "name": "Moved to onboarding",
        "channel": "email",
        "subject": "Your documents are verified — next steps",
        "auto_send_allowed": True,
        "description": "Sent when every required document is verified.",
        "body": (
            "Hi {{first_name}},\n\n"
            "Good news — our Onboarding team has verified your documents. A member of the team will reach out "
            "with the next steps.\n\n"
            "Best,\n{{recruiter_name}}"
        ),
    },
}
