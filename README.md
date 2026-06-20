# Contractor Relief

Small contractor-sourcing desk for planning home jobs, finding local contractors, and tracking calls, texts, contractor emails, and follow-up actions. The greenhouse assembly workflow is now the first job inside the app rather than the whole app.

It keeps this work separate from Nox Voice:

- FastAPI app with Twilio webhook and OpenAI Realtime bridge
- SQLite jobs, lead/call queue, contractor email addresses, SMS history, and follow-up actions
- Invite-only dashboard registration, PBKDF2 password hashing, and server-side sessions
- Production dashboard at `https://contractorrelief.ai/contractor` via Cloudflare Tunnel
- Local dashboard at `http://127.0.0.1:8016/contractor`
- Selected-job call loop execution from the dashboard, plus one-shot CLI caller via `python -m app.caller`
- Two separate text paths so the sender is never ambiguous:
  - `python -m app.sms TO BODY` sends from the configured Twilio project number and captures replies in the project database.
  - `python -m app.imessage TO BODY` sends from the operator's Messages.app account via `imsg`; use only after confirming recipient and exact wording.
- Sam executes due text/email follow-up actions during the job handoff flow. Text uses Twilio. Email uses Cloudflare Email Service when `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_EMAIL_TOKEN`, and `CLOUDFLARE_EMAIL_FROM` are configured. Resend and SMTP remain fallback sender paths; otherwise email actions are marked blocked so they stay visible in the dashboard.
- Systemd deployment files

The initial greenhouse run was intended for 2026-06-01 at 09:00 America/New_York. It should call local greenhouse builders first, then handyman/outdoor assembly services.

Local setup: create a venv, install with pip install -e '.[dev]', run python -m app.seed, then pytest.

Run the dashboard locally:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8016
```

## Dashboard MVP

The `/contractor` dashboard supports:

- creating multiple jobs, such as greenhouse assembly or door fitting
- reviewing the AI-generated job brief/checklist
- adding candidate leads
- seeing call outcomes and transcripts summarized by lead
- reviewing job-matched Twilio text history
- executing the selected job's pending call loop
- reviewing contractor email addresses discovered from search results and contractor pages
- agent-created and agent-executed next actions for text/email follow-up after missed calls, voicemail, IVR, or contractor requests

The next pieces to wire are richer planning and review controls:

- optional OpenAI planning pass for richer job briefs and search queries
- richer email/thread history beyond sent/blocked action status
- reply threading and retry controls

## Outreach Flow

The job agent owns channel decisions after the operator has handed over the job scope. It searches for usable contractors, contacts the best candidates first when a phone number is available, and queues the appropriate follow-up action if the call does not connect, reaches voicemail/IVR, or the contractor asks for details by text/email. Outreach should continue without per-message approval prompts.

## Dashboard Auth

The dashboard routes under `/contractor` require login. Twilio webhook routes under `/greenhouse/*` remain public so callbacks continue to work.

Production runs on Hetzner behind Cloudflare Tunnel. The app binds to `127.0.0.1:8005`; `contractorrelief.ai` and `www.contractorrelief.ai` route directly to that local service through the `SIGNAL_OBSERVER_001` tunnel. Do not open a firewall port for the dashboard.

Required production env vars:

- `CONTRACTOR_AUTH_SECRET` - random long secret used to hash session tokens
- `CONTRACTOR_INVITE_CODE` - one-time/shared invite code for registration

Passwords are stored as PBKDF2-SHA256 hashes. Session tokens are random, stored hashed in SQLite, and set as HTTP-only cookies.

## Location Gate

Discovered contractor leads must include Gasport travel metadata: origin_address, distance_miles, and drive_minutes. The unattended CLI caller only dials pending non-referral leads inside MAX_DRIVE_MINUTES (default 90) or MAX_DISTANCE_MILES (default 75). Manufacturer/referral calls are exempt because they are asked for local installer referrals, not hired directly.

The dashboard call-loop button is selected-job only and also allows manually added leads with unknown travel metadata. Treat that as an explicit operator-approved lead, not a discovery result.

Use app.geo.travel_from_gasport(address) for OpenStreetMap/Nominatim + OSRM checks before adding new leads. Do not add fuzzy "WNY-ish" leads without a drive-time estimate; that is how two-hour nonsense gets into the queue.

## Operator Notes

The caller should ask whether the business can handle the configured contractor job, whether they are insured, rough pricing, earliest availability, and best callback/text number. It should not provide the full project address unless the contractor needs it for a serious quote.

Automated calls and follow-up texts should use the Twilio project number by default. Use iMessage only for deliberate manual-looking outbound texts from the operator's own number; inbound replies to those personal texts live in Messages.app, not in the Twilio webhook.
