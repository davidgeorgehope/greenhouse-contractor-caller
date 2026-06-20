from __future__ import annotations

import html

from fastapi import BackgroundTasks, FastAPI, Form, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi import status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .agent import run_job_agent
from .auth import authenticate_user, create_session, create_user, delete_session, has_users, require_user
from .billing import (
    billing_configured,
    call_credits_remaining,
    can_add_paid_lead,
    can_create_paid_job,
    can_use_paid_workflows,
    create_checkout_session,
    create_credit_checkout_session,
    credit_checkout_configured,
    handle_stripe_event,
    parse_stripe_event,
)
from .caller import place_calls, place_test_call
from .config import get_settings
from .contact import normalize_phone, resolve_lead_for_email, resolve_lead_for_phone
from .db import (
    append_event,
    call_for_id,
    calls_for_job,
    create_call,
    create_email_message,
    create_job,
    create_outreach_action,
    create_signup,
    create_sms_message,
    delete_test_calls_for_job,
    default_job_brief,
    get_user_billing,
    job_for_id,
    leads_for_job,
    list_jobs,
    lead_for_call,
    emails_for_job,
    mark_lead_status,
    mark_job_lead_status,
    sms_for_job,
    update_call,
    update_job_brief,
    update_job_status,
    upsert_lead,
    outreach_for_job,
)
from .discovery import discover_leads_for_job
from .outreach import execute_outreach_actions
from .test_harness import (
    activate_test_subscription,
    add_test_call_credits,
    reset_local_test_billing,
    simulate_realtime_test_contractor_call,
    simulate_test_contractor_call,
)
from .voice import bridge_call

app = FastAPI(title="Contractor Relief")

OWNER_EMAIL = "email.djhope@gmail.com"


@app.get("/greenhouse/health")
def health() -> dict[str, str]:
    return {"ok": "true"}


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return _landing_page()


def _landing_page() -> str:
    settings = get_settings()
    product_name = html.escape(settings.contractor_product_name)
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{product_name} - Stop chasing contractors</title>
  <style>
    :root {{ --ink:#17201b; --muted:#607067; --line:#d8dfda; --bg:#f6f7f3; --band:#ffffff; --accent:#0f766e; --accent-dark:#0a524d; --warm:#f3c77b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }}
    a {{ color:inherit; }}
    .nav {{ display:flex; align-items:center; justify-content:space-between; gap:16px; max-width:1120px; margin:0 auto; padding:18px 22px; }}
    .brand {{ font-weight:800; font-size:18px; }}
    .nav-links {{ display:flex; gap:10px; align-items:center; }}
    .nav-links a {{ text-decoration:none; font-weight:700; color:var(--muted); }}
    .nav-links .button {{ color:white; background:var(--accent); padding:9px 12px; border-radius:6px; }}
    .hero {{ background:linear-gradient(180deg,#fff 0%,#f6f7f3 100%); border-top:1px solid #eef1ed; }}
    .hero-inner {{ max-width:1120px; margin:0 auto; padding:72px 22px 54px; display:grid; grid-template-columns:minmax(0,1.1fr) minmax(300px,.9fr); gap:42px; align-items:center; }}
    h1 {{ margin:0; font-size:clamp(40px,6vw,72px); line-height:.96; letter-spacing:0; max-width:760px; }}
    .lede {{ margin:20px 0 0; color:var(--muted); font-size:20px; max-width:640px; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:28px; }}
    .button-primary,.button-secondary {{ display:inline-flex; align-items:center; justify-content:center; min-height:44px; padding:11px 16px; border-radius:6px; text-decoration:none; font-weight:800; }}
    .button-primary {{ background:var(--accent); color:white; }}
    .button-secondary {{ border:1px solid var(--line); background:white; color:var(--ink); }}
    .proof {{ display:grid; gap:12px; padding:0; margin:0; list-style:none; }}
    .proof li {{ border-left:4px solid var(--warm); background:white; padding:14px 16px; color:var(--muted); box-shadow:0 1px 0 rgba(23,32,27,.05); }}
    .proof strong {{ display:block; color:var(--ink); margin-bottom:3px; }}
    .band {{ background:var(--band); border-block:1px solid var(--line); }}
    .steps {{ max-width:1120px; margin:0 auto; padding:42px 22px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:22px; }}
    .step {{ padding:0; }}
    .step span {{ display:inline-grid; place-items:center; width:32px; height:32px; border-radius:50%; background:#e2f2ef; color:var(--accent-dark); font-weight:900; margin-bottom:12px; }}
    h2 {{ margin:0 0 8px; font-size:21px; letter-spacing:0; }}
    .step p,.pricing p {{ margin:0; color:var(--muted); }}
    .pricing {{ max-width:1120px; margin:0 auto; padding:44px 22px 60px; display:grid; grid-template-columns:minmax(0,.9fr) minmax(280px,.6fr); gap:34px; align-items:start; }}
    .price {{ font-size:44px; font-weight:900; line-height:1; margin:8px 0; }}
    .limits {{ margin:18px 0 0; padding:0; list-style:none; display:grid; gap:8px; color:var(--muted); }}
    .limits li::before {{ content:""; display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent); margin-right:9px; vertical-align:middle; }}
    footer {{ max-width:1120px; margin:0 auto; padding:22px; color:var(--muted); display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
    @media (max-width:760px) {{
      .hero-inner,.pricing {{ grid-template-columns:1fr; padding-top:42px; }}
      .steps {{ grid-template-columns:1fr; }}
      h1 {{ font-size:42px; }}
      .nav {{ align-items:flex-start; }}
      .nav-links {{ flex-wrap:wrap; justify-content:flex-end; }}
    }}
  </style>
</head>
<body>
  <nav class="nav">
    <div class="brand">{product_name}</div>
    <div class="nav-links">
      <a href="/contractor/login">Sign in</a>
      <a class="button" href="/signup">Start a job</a>
    </div>
  </nav>
  <main>
    <section class="hero">
      <div class="hero-inner">
        <div>
          <h1>Stop chasing contractors.</h1>
          <p class="lede">Send Contractor Relief the job. It finds local options, calls the best matches, follows up by text or email, and gives you the useful answers without the phone-tag misery.</p>
          <div class="actions">
            <a class="button-primary" href="/signup">Start a job</a>
            <a class="button-secondary" href="/contractor/login">Open dashboard</a>
          </div>
        </div>
        <ul class="proof">
          <li><strong>Built for small home jobs</strong> Assembly, repairs, installs, cleanup, and the odd work nobody wants to quote.</li>
          <li><strong>Calls real businesses</strong> Uses live AI voice on GPT-Realtime-2 with text and email follow-up.</li>
          <li><strong>Keeps the blast radius sane</strong> Jobs and contractor contacts are capped so pricing can stay consumer-friendly.</li>
        </ul>
      </div>
    </section>
    <section class="band">
      <div class="steps">
        <div class="step"><span>1</span><h2>Describe the job</h2><p>Tell it what needs doing, where, timing, constraints, and what a useful quote looks like.</p></div>
        <div class="step"><span>2</span><h2>It handles outreach</h2><p>Contractor Relief finds leads, places calls, sends follow-ups, and filters dead ends.</p></div>
        <div class="step"><span>3</span><h2>You get the short list</h2><p>Review availability, rough pricing, callbacks, and next steps in one dashboard.</p></div>
      </div>
    </section>
    <section class="pricing">
      <div>
        <h2>Launch pricing target</h2>
        <div class="price">$10/mo</div>
        <p>Designed for consumers, not procurement committees. Final limits may change while early users teach us where the real cost sits.</p>
      </div>
      <ul class="limits">
        <li>Up to 5 active jobs</li>
        <li>10 included contractor call credits</li>
        <li>Optional top-ups for bigger projects</li>
        <li>Limits on contractor count and call length</li>
      </ul>
    </section>
  </main>
  <footer><span>{product_name}</span><span>Contractor coordination without the coordination headache.</span></footer>
</body>
</html>
"""


@app.get("/signup", response_class=HTMLResponse)
def signup_form() -> str:
    return _signup_page()


@app.post("/signup")
def signup(
    request: Request,
    display_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    project_type: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
) -> Response:
    if len(password) < 12:
        return HTMLResponse(_signup_page(error="Password must be at least 12 characters."), status_code=400)
    try:
        user_id = create_user(email=email, password=password, display_name=display_name)
    except Exception:
        return HTMLResponse(_signup_page(error="That email is already registered. Sign in instead."), status_code=409)
    create_signup(
        email=email,
        display_name=display_name,
        project_type=project_type,
        location=location,
        notes=notes,
        source="account_signup",
    )
    token, expires_at = create_session(user_id)
    response = RedirectResponse("/contractor/billing", status_code=303)
    response.set_cookie(
        get_settings().contractor_session_cookie,
        token,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        expires=expires_at,
    )
    return response


def _signup_page(error: str = "") -> str:
    product_name = html.escape(get_settings().contractor_product_name)
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Start - {product_name}</title>
  <style>
    :root {{ --ink:#17201b; --muted:#647067; --line:#d7ddd8; --panel:#ffffff; --bg:#f4f6f2; --accent:#0f766e; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; font:15px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); padding:24px; }}
    main {{ width:min(520px,100%); background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:24px; }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
    p {{ color:var(--muted); margin:0 0 16px; }}
    form {{ display:grid; gap:11px; }}
    label {{ display:grid; gap:6px; font-weight:750; }}
    input,textarea {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:10px; font:inherit; }}
    textarea {{ min-height:96px; resize:vertical; }}
    button {{ border:0; border-radius:6px; padding:11px 12px; font-weight:800; background:var(--accent); color:white; cursor:pointer; }}
    a {{ color:var(--accent); font-weight:700; }}
    .error {{ color:#b42318; background:#fff1f0; border:1px solid #ffd0cc; border-radius:6px; padding:9px; }}
  </style>
</head>
<body>
  <main>
    <h1>Start Contractor Relief</h1>
    <p>Create an account, then subscribe to launch contractor outreach. Early launch pricing is $10/month for 5 active jobs and 10 included call credits.</p>
    {error_html}
    <form method="post" action="/signup">
      <label>Name <input name="display_name" autocomplete="name"></label>
      <label>Email <input name="email" type="email" autocomplete="email" required></label>
      <label>Password <input name="password" type="password" autocomplete="new-password" minlength="12" required></label>
      <label>Project type <input name="project_type" placeholder="Greenhouse, deck repair, bathroom fan, fence..."></label>
      <label>Location <input name="location" placeholder="City, state"></label>
      <label>What is annoying about this job? <textarea name="notes"></textarea></label>
      <button type="submit">Create account</button>
    </form>
    <p style="margin-top:16px"><a href="/contractor/login">Already have an account?</a> · <a href="/">Back to overview</a></p>
  </main>
</body>
</html>
"""


def _secure_cookie(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    host = (request.url.hostname or "").lower()
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    return request.url.scheme == "https" or forwarded_proto == "https" or host not in local_hosts


def _is_owner_user(user: object) -> bool:
    try:
        email = str(user["email"])
    except (KeyError, TypeError):
        return False
    return email.strip().lower() == OWNER_EMAIL


def _require_owner_user(request: Request):
    user = require_user(request)
    if not _is_owner_user(user):
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Owner-only tool")
    return user


def _auth_page(title: str, body: str, error: str = "") -> str:
    product_name = get_settings().contractor_product_name
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · {html.escape(product_name)}</title>
  <style>
    :root {{ --ink:#17201b; --muted:#647067; --line:#d7ddd8; --panel:#ffffff; --bg:#f4f6f2; --accent:#0f766e; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); padding:24px; }}
    main {{ width:min(420px,100%); background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:22px; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    p {{ color:var(--muted); margin:0 0 16px; }}
    form {{ display:grid; gap:10px; }}
    input {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:10px; font:inherit; }}
    button {{ border:0; border-radius:6px; padding:10px 12px; font-weight:700; background:var(--accent); color:white; cursor:pointer; }}
    a {{ color:var(--accent); font-weight:650; }}
    .error {{ color:#b42318; background:#fff1f0; border:1px solid #ffd0cc; border-radius:6px; padding:9px; }}
    .notice {{ color:#166534; background:#edf9ef; border:1px solid #c8e6ca; border-radius:6px; padding:9px; }}
  </style>
</head>
<body><main><h1>{html.escape(title)}</h1>{error_html}{body}</main></body>
</html>
"""


@app.get("/contractor/login", response_class=HTMLResponse)
def login_form(request: Request) -> str:
    if not has_users():
        return RedirectResponse("/contractor/register", status_code=303)
    body = """
    <p>Sign in to manage contractor jobs and outreach.</p>
    <form method="post" action="/contractor/login">
      <input name="email" type="email" placeholder="Email" autocomplete="email" required>
      <input name="password" type="password" placeholder="Password" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
    """
    return _auth_page("Sign in", body)


@app.post("/contractor/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
    user = authenticate_user(email, password)
    if user is None:
        body = """
        <p>Sign in to manage contractor jobs and outreach.</p>
        <form method="post" action="/contractor/login">
          <input name="email" type="email" placeholder="Email" autocomplete="email" required>
          <input name="password" type="password" placeholder="Password" autocomplete="current-password" required>
          <button type="submit">Sign in</button>
        </form>
        """
        return HTMLResponse(_auth_page("Sign in", body, "Email or password was wrong."), status_code=401)
    token, expires_at = create_session(int(user["id"]))
    response = RedirectResponse("/contractor", status_code=303)
    response.set_cookie(
        get_settings().contractor_session_cookie,
        token,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        expires=expires_at,
    )
    return response


@app.get("/contractor/register", response_class=HTMLResponse)
def register_form() -> str:
    settings = get_settings()
    if not settings.contractor_invite_code:
        return _auth_page("Registration disabled", "<p>Set CONTRACTOR_INVITE_CODE on the server before creating an account.</p>")
    body = """
    <p>Create the first dashboard account with the invite code.</p>
    <form method="post" action="/contractor/register">
      <input name="display_name" placeholder="Name" autocomplete="name" required>
      <input name="email" type="email" placeholder="Email" autocomplete="email" required>
      <input name="password" type="password" placeholder="Password" autocomplete="new-password" minlength="12" required>
      <input name="invite_code" type="password" placeholder="Invite code" autocomplete="off" required>
      <button type="submit">Create account</button>
    </form>
    <p><a href="/contractor/login">Already registered?</a></p>
    """
    return _auth_page("Register", body)


@app.post("/contractor/register", response_class=HTMLResponse)
def register(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    invite_code: str = Form(...),
) -> Response:
    settings = get_settings()
    if not settings.contractor_invite_code or not secrets_compare(invite_code, settings.contractor_invite_code):
        return HTMLResponse(_auth_page("Register", _register_form_body(), "Invite code was wrong."), status_code=403)
    if len(password) < 12:
        return HTMLResponse(_auth_page("Register", _register_form_body(), "Password must be at least 12 characters."), status_code=400)
    try:
        user_id = create_user(email=email, password=password, display_name=display_name)
    except Exception:
        return HTMLResponse(_auth_page("Register", _register_form_body(), "That email is already registered."), status_code=409)
    token, expires_at = create_session(user_id)
    response = RedirectResponse("/contractor", status_code=303)
    response.set_cookie(
        settings.contractor_session_cookie,
        token,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        expires=expires_at,
    )
    return response


def _register_form_body() -> str:
    return """
    <p>Create the first dashboard account with the invite code.</p>
    <form method="post" action="/contractor/register">
      <input name="display_name" placeholder="Name" autocomplete="name" required>
      <input name="email" type="email" placeholder="Email" autocomplete="email" required>
      <input name="password" type="password" placeholder="Password" autocomplete="new-password" minlength="12" required>
      <input name="invite_code" type="password" placeholder="Invite code" autocomplete="off" required>
      <button type="submit">Create account</button>
    </form>
    <p><a href="/contractor/login">Already registered?</a></p>
    """


def secrets_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@app.post("/contractor/logout")
def logout(request: Request) -> RedirectResponse:
    delete_session(request.cookies.get(get_settings().contractor_session_cookie))
    response = RedirectResponse("/contractor/login", status_code=303)
    response.delete_cookie(get_settings().contractor_session_cookie)
    return response


@app.get("/contractor/billing", response_class=HTMLResponse)
def billing_page(request: Request, required: str = "", checkout: str = "", credits: str = "", test: str = "") -> str:
    user = require_user(request)
    settings = get_settings()
    billing = get_user_billing(int(user["id"]))
    status = billing["status"] if billing else "inactive"
    notice = ""
    if required:
        notice = '<p class="error">Start a subscription before launching contractor outreach.</p>'
    elif checkout == "success":
        notice = '<p class="notice">Checkout finished. Stripe will activate this account as soon as the webhook arrives.</p>'
    elif checkout == "cancelled":
        notice = '<p class="error">Checkout was cancelled. No charge was made.</p>'
    elif credits == "success":
        notice = '<p class="notice">Credit checkout finished. Credits will appear as soon as Stripe sends the webhook.</p>'
    elif credits == "cancelled":
        notice = '<p class="error">Credit checkout was cancelled. No charge was made.</p>'
    elif test == "activated":
        notice = '<p class="notice">Test subscription activated for your owner account. No Stripe charge was made.</p>'
    elif test == "credits":
        notice = '<p class="notice">Test call credits added. No Stripe charge was made.</p>'
    elif test == "reset":
        notice = '<p class="notice">Local test billing reset.</p>'
    elif test == "reset-blocked":
        notice = '<p class="error">Billing was not reset because this account is not using local test billing IDs.</p>'
    elif test == "activate-blocked":
        notice = '<p class="error">Test billing was not activated because this account already has a non-test Stripe customer.</p>'

    button = "<p>Stripe is not configured on this server yet.</p>"
    if billing_configured() and status not in {"active", "trialing"}:
        button = '<form method="post" action="/contractor/billing/checkout"><button type="submit">Start Contractor Relief</button></form>'
    elif status in {"active", "trialing"}:
        button = '<p class="notice">Billing is active. You can launch outreach.</p>'
    credit_button = ""
    if credit_checkout_configured():
        credit_button = '<form method="post" action="/contractor/billing/credits"><button type="submit">Add 10 call credits</button></form>'
    test_tools = ""
    if _is_owner_user(user):
        test_tools = """
        <hr>
        <h2>Owner test billing</h2>
        <p>Use these to test Contractor Relief billing gates without charging a card or touching Stripe objects.</p>
        <form method="post" action="/contractor/test/billing/activate"><button type="submit">Activate test subscription</button></form>
        <form method="post" action="/contractor/test/billing/credits"><button type="submit">Add test call credits</button></form>
        <form method="post" action="/contractor/test/billing/reset"><button type="submit">Reset local test billing</button></form>
        """
    body = f"""
    {notice}
    <p>Contractor Relief finds, contacts, chases, and summarizes contractors so your home project actually moves.</p>
    <p><strong>Status:</strong> {html.escape(status)}</p>
    <p><strong>Call credits:</strong> {call_credits_remaining(int(user["id"]))}</p>
    {button}
    {credit_button}
    {test_tools}
    <p><a href="/contractor">Back to dashboard</a></p>
    """
    return _auth_page("Billing", body)


@app.post("/contractor/test/billing/activate")
def activate_test_billing(request: Request) -> RedirectResponse:
    user = _require_owner_user(request)
    activated = activate_test_subscription(int(user["id"]))
    return RedirectResponse(f"/contractor/billing?test={'activated' if activated else 'activate-blocked'}", status_code=303)


@app.post("/contractor/test/billing/credits")
def add_test_billing_credits(request: Request) -> RedirectResponse:
    user = _require_owner_user(request)
    add_test_call_credits(int(user["id"]))
    return RedirectResponse("/contractor/billing?test=credits", status_code=303)


@app.post("/contractor/test/billing/reset")
def reset_test_billing(request: Request) -> RedirectResponse:
    user = _require_owner_user(request)
    reset = reset_local_test_billing(int(user["id"]))
    return RedirectResponse(f"/contractor/billing?test={'reset' if reset else 'reset-blocked'}", status_code=303)


@app.post("/contractor/billing/checkout")
def start_billing_checkout(request: Request) -> RedirectResponse:
    user = require_user(request)
    try:
        checkout_url = create_checkout_session(user)
    except RuntimeError:
        return RedirectResponse("/contractor/billing?required=1", status_code=303)
    return RedirectResponse(checkout_url, status_code=303)


@app.post("/contractor/billing/credits")
def start_credit_checkout(request: Request) -> RedirectResponse:
    user = require_user(request)
    try:
        checkout_url = create_credit_checkout_session(user)
    except RuntimeError:
        return RedirectResponse("/contractor/billing?required=1", status_code=303)
    return RedirectResponse(checkout_url, status_code=303)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None)) -> dict[str, bool]:
    payload = await request.body()
    event = parse_stripe_event(payload, stripe_signature)
    handle_stripe_event(event)
    return {"received": True}


@app.get("/contractor", response_class=HTMLResponse)
def contractor_dashboard(
    request: Request,
    job_id: int | None = None,
    agent: str = "",
    test_call: str = "",
    test_cleanup: str = "",
    outreach_sent: str = "",
    outreach_blocked: str = "",
    outreach_failed: str = "",
    test_agent: str = "",
    limit: str = "",
) -> str:
    user = require_user(request)
    user_id = int(user["id"])
    jobs = list_jobs(user_id)
    selected_job = job_for_id(job_id, user_id) if job_id else (jobs[0] if jobs else None)
    selected_job_id = int(selected_job["id"]) if selected_job else None
    leads = leads_for_job(selected_job_id) if selected_job_id else []
    calls = calls_for_job(selected_job_id) if selected_job_id else []
    actions = outreach_for_job(selected_job_id) if selected_job_id else []
    texts = sms_for_job(selected_job_id) if selected_job_id else []
    emails = emails_for_job(selected_job_id) if selected_job_id else []
    settings = get_settings()
    billing = get_user_billing(user_id)
    billing_status = billing["status"] if billing else "inactive"
    billing_active = can_use_paid_workflows(user_id)
    call_credits = call_credits_remaining(user_id)

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    job_tabs = "".join(
        f"""<a class="job-tab {'active' if selected_job_id == int(job['id']) else ''}" href="/contractor?job_id={job['id']}">
          <strong>{esc(job['title'])}</strong>
          <span>{esc(job['status'])} · {job['lead_count']} leads</span>
        </a>"""
        for job in jobs
    )
    lead_rows = "".join(
        f"""<tr>
          <td><strong>{esc(lead['name'])}</strong><span>{esc(lead['category'])}</span></td>
          <td>{esc(lead['phone'])}</td>
          <td>{esc(lead['email'])}</td>
          <td>{esc(lead['status'])}</td>
          <td>{esc(lead['priority'])}</td>
          <td>{esc(lead['latest_call_summary'] or lead['notes'])}</td>
        </tr>"""
        for lead in leads
    ) or """<tr><td colspan="6" class="empty">No contractors found yet. Launch outreach and discovered contractors will appear here.</td></tr>"""
    call_rows = "".join(
        f"""<tr>
          <td>{esc(call['created_at'])}</td>
          <td>{esc(call['lead_name'])}</td>
          <td>{esc(call['direction'])}</td>
          <td>{esc(call['status'])}</td>
          <td>{esc(call['outcome'] or '')}</td>
          <td>{esc(call['summary'] or '')}</td>
          <td><a class="button-link" href="/contractor/calls/{call['id']}">Transcript</a></td>
        </tr>"""
        for call in calls
    ) or """<tr><td colspan="7" class="empty">No calls recorded for this job yet.</td></tr>"""
    action_rows = "".join(
        f"""<tr>
          <td>{esc(action['channel'])}</td>
          <td>{esc(action['lead_email'] if action['channel'] == 'email' and action['lead_email'] else action['lead_phone'] if action['channel'] == 'text' and action['lead_phone'] else action['lead_name'] or 'Job')}</td>
          <td>{esc(action['status'])}</td>
          <td>{esc(action['due_at'] or '')}</td>
          <td>{esc(action['body'] or action['notes'])}</td>
        </tr>"""
        for action in actions
    ) or """<tr><td colspan="5" class="empty">No next actions yet. Contractor Relief will add these when a call, text, or reply needs your attention.</td></tr>"""
    text_rows = "".join(
        f"""<tr>
          <td>{esc(text['created_at'])}</td>
          <td>{esc(text['lead_name'] or text['from_number'])}</td>
          <td>{esc(text['direction'])}</td>
          <td>{esc(text['from_number'])}</td>
          <td>{esc(text['to_number'])}</td>
          <td>{esc(text['status'] or '')}</td>
          <td>{esc(text['body'])}</td>
        </tr>"""
        for text in texts
    ) or """<tr><td colspan="7" class="empty">No texts recorded for this job yet.</td></tr>"""
    email_rows = "".join(
        f"""<tr>
          <td>{esc(email['created_at'])}</td>
          <td>{esc(email['lead_name'] or email['from_email'])}</td>
          <td>{esc(email['direction'])}</td>
          <td>{esc(email['from_email'])}</td>
          <td>{esc(email['to_email'])}</td>
          <td>{esc(email['subject'])}</td>
          <td>{esc(email['body'])}</td>
        </tr>"""
        for email in emails
    ) or """<tr><td colspan="7" class="empty">No emails recorded for this job yet.</td></tr>"""
    brief_panel = ""
    if selected_job:
        if selected_job["status"] == "planning":
            brief_panel = f"""
        <section class="panel brief">
          <div class="section-head">
            <h2>Brief</h2>
            <span>Editable while this job is in planning.</span>
          </div>
          <form method="post" action="/contractor/jobs/{selected_job_id}/brief">
            <div class="brief-fields">
              <label>Title<input name="title" value="{esc(selected_job['title'])}" required></label>
              <label>Location<input name="location" value="{esc(selected_job['location'])}" required></label>
            </div>
            <label>Description<textarea name="description" class="description-editor" required>{esc(selected_job['description'])}</textarea></label>
            <textarea name="brief" class="brief-editor" required>{esc(selected_job['brief'])}</textarea>
            <button type="submit">Save brief</button>
          </form>
        </section>
            """
        else:
            brief_panel = f"""
        <section class="panel brief">
          <div class="section-head">
            <h2>Brief</h2>
            <span>Move the job back to planning to edit.</span>
          </div>
          <pre>{esc(selected_job['brief'])}</pre>
        </section>
            """
    selected_header = (
        f"""
        <section class="panel hero-panel">
          <div>
            <p class="eyebrow">Selected job</p>
            <h1>{esc(selected_job['title'])}</h1>
            <p>{esc(selected_job['description'])}</p>
          </div>
          <form method="post" action="/contractor/jobs/{selected_job_id}/status" class="status-form">
            <select name="status">
              {''.join(f'<option value="{status}" {"selected" if selected_job["status"] == status else ""}>{status}</option>' for status in ["planning", "active", "paused", "done"])}
            </select>
            <button type="submit">Update</button>
          </form>
        </section>
        {brief_panel}
        """
        if selected_job
        else """<section class="panel hero-panel"><h1>No jobs yet</h1><p>Create the first contractor job to start planning outreach.</p></section>"""
    )
    agent_notice = ""
    if agent == "started":
        agent_notice = """<p class="notice">Contractor Relief is working this brief now. Refresh for new leads, calls, texts, and transcripts.</p>"""
    elif agent == "error":
        agent_notice = """<p class="warning">Realtime test contractor failed before completing. Check the event log for the captured error.</p>"""
    if test_call == "started":
        agent_notice += """<p class="notice">Test call started. It will appear in call history once Twilio reports back.</p>"""
    if test_cleanup:
        agent_notice += f"""<p class="notice">Cleaned out {esc(test_cleanup)} test call{'s' if test_cleanup != '1' else ''} for this job.</p>"""
    if test_agent:
        agent_notice += f"""<p class="notice">Test contractor agent completed call #{esc(test_agent)}. It consumed one call credit and wrote a transcript.</p>"""
    if outreach_sent or outreach_blocked or outreach_failed:
        agent_notice += f"""<p class="notice">Follow-ups processed: {esc(outreach_sent or 0)} sent, {esc(outreach_blocked or 0)} blocked, {esc(outreach_failed or 0)} failed.</p>"""
    if limit == "jobs":
        agent_notice += """<p class="warning">Active job limit reached. Finish or archive an existing job before creating another.</p>"""
    elif limit == "leads":
        agent_notice += """<p class="warning">Contractor lead limit reached for this job. Skip a lead or add credits before adding more.</p>"""
    elif limit == "credits":
        agent_notice += """<p class="warning">No call credits remain. Add credits before placing more contractor calls.</p>"""
    billing_panel = ""
    if settings.contractor_billing_required and not billing_active:
        billing_panel = """
        <section class="panel billing-panel">
          <div>
            <p class="eyebrow">Billing</p>
            <h2>Start Contractor Relief</h2>
            <p>Subscribe before launching discovery, calls, texts, and email follow-up.</p>
          </div>
          <a class="button-link" href="/contractor/billing">Set up billing</a>
        </section>
        """

    paid_disabled = settings.contractor_billing_required and not billing_active
    paid_disabled_attr = "disabled" if paid_disabled else ""
    paid_disabled_notice = '<p class="warning">Billing is required before launching outreach.</p>' if paid_disabled else ""
    owner_tools = ""
    if _is_owner_user(user):
        owner_tools = f"""
            <form method="post" action="/contractor/jobs/{selected_job_id}/test-call">
              <button type="submit" class="secondary">Test call David</button>
            </form>
            <form method="post" action="/contractor/jobs/{selected_job_id}/test-calls/cleanup" onsubmit="return confirm('Clean out test calls and transcripts for this job? Real contractor calls will stay.');">
              <button type="submit" class="secondary">Clean test calls</button>
            </form>
            <form method="post" action="/contractor/jobs/{selected_job_id}/test-agent">
              <button type="submit" class="secondary">Run test contractor</button>
            </form>
            <form method="post" action="/contractor/jobs/{selected_job_id}/test-agent/realtime">
              <select name="scenario" aria-label="Realtime test contractor scenario">
                <option value="available">Available</option>
                <option value="needs_photos">Needs photos</option>
                <option value="busy">Booked out</option>
              </select>
              <button type="submit" class="secondary">Run Realtime test contractor</button>
            </form>
        """

    agent_panel = (
        f"""
        <section class="panel agent-panel">
          <div>
            <p class="eyebrow">Main workflow</p>
            <h2>Hand the brief to Contractor Relief</h2>
            <p>Fill in the brief, then let Contractor Relief source contractors, pick usable candidates, run outreach, and log what happened.</p>
          </div>
          {agent_notice}
          <div class="agent-actions">
            <form method="post" action="/contractor/jobs/{selected_job_id}/agent">
              <button type="submit" {paid_disabled_attr}>Launch outreach</button>
            </form>
            {owner_tools}
          </div>
          {paid_disabled_notice}
          {'<p class="warning">Caller is disabled on this server, so the agent can source leads but cannot place calls until CALLER_DISABLED=0.</p>' if settings.caller_disabled else ''}
        </section>
        """
        if selected_job_id
        else ""
    )
    followup_button = (
        f"""
          <form method="post" action="/contractor/jobs/{selected_job_id}/followups/execute" onsubmit="return confirm('Send due draft/queued text and email follow-ups for this job?');">
            <button type="submit" class="secondary">Send due follow-ups</button>
          </form>
        """
        if selected_job_id
        else ""
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(settings.contractor_product_name)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#17201b; --muted:#647067; --line:#d7ddd8; --panel:#ffffff; --bg:#f4f6f2; --accent:#0f766e; --accent-2:#a16207; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 24px; border-bottom:1px solid var(--line); background:#fbfcfa; position:sticky; top:0; z-index:1; }}
    header h1 {{ margin:0; font-size:20px; }}
    header span {{ color:var(--muted); }}
    main {{ display:grid; grid-template-columns:280px 1fr; gap:18px; padding:18px; max-width:1440px; margin:0 auto; }}
    aside, .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
    aside {{ padding:12px; height:calc(100vh - 92px); position:sticky; top:74px; overflow:auto; }}
    .job-tab {{ display:block; color:inherit; text-decoration:none; padding:10px; border-radius:6px; border:1px solid transparent; }}
    .job-tab.active {{ border-color:var(--accent); background:#e7f4f1; }}
    .job-tab span, td span {{ display:block; color:var(--muted); font-size:12px; margin-top:2px; }}
    .stack {{ display:grid; gap:18px; min-width:0; }}
    .panel {{ padding:16px; overflow:hidden; }}
    .hero-panel {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start; }}
    .agent-panel, .billing-panel {{ display:grid; grid-template-columns:1fr auto; gap:14px 18px; align-items:center; border-color:#8bbab2; background:#f7fbfa; }}
    .agent-actions {{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; align-items:center; }}
    .agent-actions form {{ display:block; }}
    .execute-panel {{ display:flex; justify-content:space-between; align-items:center; gap:18px; }}
    .source-form {{ grid-template-columns:1fr auto; }}
    .execute-panel p {{ margin:0; color:var(--muted); }}
    .agent-panel p, .billing-panel p {{ margin:0; color:var(--muted); max-width:840px; }}
    .agent-panel h2, .billing-panel h2 {{ margin:2px 0 6px; font-size:22px; }}
    .hero-panel h1 {{ margin:2px 0 6px; font-size:28px; line-height:1.1; }}
    .hero-panel p {{ margin:0; color:var(--muted); max-width:820px; }}
    .eyebrow {{ text-transform:uppercase; letter-spacing:.08em; font-size:11px; color:var(--accent-2) !important; font-weight:700; }}
    h2 {{ margin:0 0 10px; font-size:16px; }}
    .section-head {{ display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin-bottom:10px; }}
    .section-head h2 {{ margin:0; }}
    .section-head span {{ color:var(--muted); font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
    th, td {{ border-top:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }}
    th {{ color:var(--muted); font-size:12px; font-weight:650; }}
    pre {{ margin:0; white-space:pre-wrap; font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; color:#233128; }}
    form {{ display:grid; gap:8px; }}
    .grid-form {{ grid-template-columns:repeat(5,minmax(0,1fr)); align-items:start; }}
    .grid-form textarea {{ grid-column:span 5; min-height:72px; }}
    input, textarea, select {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--ink); }}
    .brief-editor {{ min-height:360px; resize:vertical; font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .description-editor {{ min-height:88px; resize:vertical; }}
    label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:650; }}
    .brief-fields {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    button {{ border:0; border-radius:6px; padding:9px 12px; font-weight:700; background:var(--accent); color:white; cursor:pointer; }}
    button.secondary {{ background:#69756c; }}
    td form {{ display:inline-grid; margin:0 4px 4px 0; }}
    .button-link {{ display:inline-flex; align-items:center; justify-content:center; min-height:32px; padding:7px 10px; border-radius:6px; background:#e7f4f1; color:var(--accent); font-weight:700; text-decoration:none; }}
    .button-link.wide {{ width:100%; }}
    .status-form {{ min-width:180px; grid-template-columns:1fr auto; }}
    .empty {{ color:var(--muted); }}
    .warning {{ margin:0; color:#9a3412; font-size:12px; }}
    .notice {{ margin:0 0 10px; color:#166534; background:#edf9ef; border:1px solid #c8e6ca; border-radius:6px; padding:9px; }}
    .agent-panel .notice, .agent-panel .warning {{ grid-column:1 / -1; }}
    button:disabled {{ background:#aab5ad; cursor:not-allowed; }}
    @media (max-width: 900px) {{ main {{ grid-template-columns:1fr; }} aside {{ position:static; height:auto; }} .hero-panel, .execute-panel {{ display:grid; }} .grid-form, .brief-fields {{ grid-template-columns:1fr; }} .grid-form textarea {{ grid-column:auto; }} }}
  </style>
</head>
<body>
  <header><div><h1>{esc(settings.contractor_product_name)}</h1><span>Write the brief. Launch outreach. Review what happened. Billing: {esc(billing_status)} · Call credits: {call_credits}</span></div><form method="post" action="/contractor/logout"><span>{esc(user['display_name'] or user['email'])}</span><button type="submit">Sign out</button></form></header>
  <main>
    <aside>
      <h2>Jobs</h2>
      {job_tabs or '<p class="empty">No jobs yet.</p>'}
      <hr>
      <a class="button-link wide" href="/contractor/jobs/new">Create job</a>
    </aside>
    <div class="stack">
      {selected_header}
      {billing_panel}
      {agent_panel}
      <section class="panel"><h2>Contractors found</h2><table><thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Status</th><th>Priority</th><th>Notes / latest result</th></tr></thead><tbody>{lead_rows}</tbody></table></section>
      <section class="panel"><h2>Call history</h2><table><thead><tr><th>When</th><th>Lead</th><th>Direction</th><th>Status</th><th>Outcome</th><th>Summary</th><th>Review</th></tr></thead><tbody>{call_rows}</tbody></table></section>
      <section class="panel"><h2>Texts</h2><table><thead><tr><th>When</th><th>Lead</th><th>Direction</th><th>From</th><th>To</th><th>Status</th><th>Body</th></tr></thead><tbody>{text_rows}</tbody></table></section>
      <section class="panel"><h2>Emails</h2><table><thead><tr><th>When</th><th>Lead</th><th>Direction</th><th>From</th><th>To</th><th>Subject</th><th>Body</th></tr></thead><tbody>{email_rows}</tbody></table></section>
      <section class="panel">
        <div class="section-head">
          <h2>Next actions</h2>
          {followup_button}
        </div>
        <table><thead><tr><th>Channel</th><th>Target</th><th>Status</th><th>Due</th><th>Body / notes</th></tr></thead><tbody>{action_rows}</tbody></table>
      </section>
    </div>
  </main>
</body>
</html>
"""


@app.get("/contractor/calls/{call_id}", response_class=HTMLResponse)
def call_detail(request: Request, call_id: int) -> str:
    user = require_user(request)
    call = call_for_id(call_id)

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    if call is None:
        return HTMLResponse(_auth_page("Call not found", '<p><a href="/contractor">Back to dashboard</a></p>'), status_code=404)

    job_id = int(call["job_id"]) if call["job_id"] is not None else None
    back_href = f"/contractor?job_id={job_id}" if job_id else "/contractor"
    transcript = call["transcript"] or "No transcript was captured for this call."
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Call Transcript · Contractor Relief</title>
  <style>
    :root {{ color-scheme: light; --ink:#17201b; --muted:#647067; --line:#d7ddd8; --panel:#ffffff; --bg:#f4f6f2; --accent:#0f766e; --accent-2:#a16207; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 24px; border-bottom:1px solid var(--line); background:#fbfcfa; position:sticky; top:0; z-index:1; }}
    header h1 {{ margin:0; font-size:20px; }}
    header span, .meta {{ color:var(--muted); }}
    main {{ max-width:1040px; margin:0 auto; padding:18px; display:grid; gap:18px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; overflow:hidden; }}
    h2 {{ margin:0 0 10px; font-size:16px; }}
    dl {{ display:grid; grid-template-columns:140px 1fr; gap:8px 14px; margin:0; }}
    dt {{ color:var(--muted); font-weight:700; }}
    dd {{ margin:0; overflow-wrap:anywhere; }}
    pre {{ margin:0; white-space:pre-wrap; font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; color:#233128; }}
    a, .button-link {{ color:var(--accent); font-weight:700; }}
    .button-link {{ display:inline-flex; align-items:center; justify-content:center; min-height:34px; padding:8px 11px; border-radius:6px; background:#e7f4f1; text-decoration:none; }}
    form {{ display:grid; gap:8px; }}
    button {{ border:0; border-radius:6px; padding:9px 12px; font-weight:700; background:var(--accent); color:white; cursor:pointer; }}
    @media (max-width:700px) {{ dl {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <header><div><h1>Contractor Relief</h1><span>Call transcript review</span></div><form method="post" action="/contractor/logout"><span>{esc(user['display_name'] or user['email'])}</span><button type="submit">Sign out</button></form></header>
  <main>
    <a class="button-link" href="{back_href}">Back to dashboard</a>
    <section class="panel">
      <h2>{esc(call['lead_name'])}</h2>
      <dl>
        <dt>Job</dt><dd>{esc(call['job_title'] or '')}</dd>
        <dt>Phone</dt><dd>{esc(call['lead_phone'])}</dd>
        <dt>Created</dt><dd>{esc(call['created_at'])}</dd>
        <dt>Status</dt><dd>{esc(call['status'])}</dd>
        <dt>Outcome</dt><dd>{esc(call['outcome'] or '')}</dd>
        <dt>Twilio SID</dt><dd>{esc(call['twilio_sid'] or '')}</dd>
        <dt>Summary</dt><dd>{esc(call['summary'] or '')}</dd>
      </dl>
    </section>
    <section class="panel">
      <h2>Transcript</h2>
      <pre>{esc(transcript)}</pre>
    </section>
  </main>
</body>
</html>
"""


@app.get("/contractor/jobs/new", response_class=HTMLResponse)
def new_contractor_job(request: Request) -> str:
    user = require_user(request)
    settings = get_settings()

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    starter_brief = default_job_brief(
        "New contractor job",
        "Describe the work, materials already owned, constraints, photos or measurements needed, and what counts as a good contractor.",
        settings.project_address,
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Create Job · Contractor Relief</title>
  <style>
    :root {{ color-scheme: light; --ink:#17201b; --muted:#647067; --line:#d7ddd8; --panel:#ffffff; --bg:#f4f6f2; --accent:#0f766e; --accent-2:#a16207; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 24px; border-bottom:1px solid var(--line); background:#fbfcfa; position:sticky; top:0; z-index:1; }}
    header h1 {{ margin:0; font-size:20px; }}
    header span {{ color:var(--muted); }}
    main {{ max-width:1120px; margin:0 auto; padding:18px; display:grid; gap:18px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; overflow:hidden; }}
    .hero-panel {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start; }}
    .hero-panel h1 {{ margin:2px 0 6px; font-size:28px; line-height:1.1; }}
    .hero-panel p {{ margin:0; color:var(--muted); max-width:760px; }}
    .eyebrow {{ text-transform:uppercase; letter-spacing:.08em; font-size:11px; color:var(--accent-2); font-weight:700; margin:0; }}
    form {{ display:grid; gap:10px; }}
    .brief-fields {{ display:grid; grid-template-columns:1fr 220px 1fr; gap:10px; }}
    label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:650; }}
    input, textarea {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--ink); }}
    .description-editor {{ min-height:92px; resize:vertical; }}
    .brief-editor {{ min-height:460px; resize:vertical; font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .form-actions {{ display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; }}
    button, .button-link {{ border:0; border-radius:6px; padding:9px 12px; font-weight:700; background:var(--accent); color:white; cursor:pointer; text-decoration:none; }}
    .button-link.secondary {{ background:#e7f4f1; color:var(--accent); }}
    @media (max-width:800px) {{ .brief-fields, .hero-panel {{ display:grid; grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <header><div><h1>Contractor Relief</h1><span>Create a contractor job brief</span></div><form method="post" action="/contractor/logout"><span>{esc(user['display_name'] or user['email'])}</span><button type="submit">Sign out</button></form></header>
  <main>
    <section class="panel hero-panel">
      <div>
        <p class="eyebrow">New job</p>
        <h1>Create the brief</h1>
        <p>This is the source of truth Contractor Relief will use for search, calls, texts, emails, and follow-ups.</p>
      </div>
      <a class="button-link secondary" href="/contractor">Back</a>
    </section>
    <section class="panel">
      <form method="post" action="/contractor/jobs">
        <div class="brief-fields">
          <label>Title<input name="title" placeholder="Interior door fitting" required></label>
          <label>Type<input name="job_type" placeholder="door_installation" value="general"></label>
          <label>Location<input name="location" value="{esc(settings.project_address)}" required></label>
        </div>
        <label>Description<textarea name="description" class="description-editor" placeholder="Short plain-English job summary" required></textarea></label>
        <label>Full brief<textarea name="brief" class="brief-editor" required>{esc(starter_brief)}</textarea></label>
        <div class="form-actions">
          <a class="button-link secondary" href="/contractor">Cancel</a>
          <button type="submit">Create job</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>
"""


@app.post("/contractor/jobs")
def create_contractor_job(
    request: Request,
    title: str = Form(...),
    job_type: str = Form("general"),
    description: str = Form(...),
    location: str = Form(""),
    brief: str = Form(""),
) -> RedirectResponse:
    user = require_user(request)
    user_id = int(user["id"])
    if get_settings().contractor_billing_required and not can_create_paid_job(user_id):
        if not can_use_paid_workflows(user_id):
            return RedirectResponse("/contractor/billing?required=1", status_code=303)
        return RedirectResponse("/contractor?limit=jobs", status_code=303)
    job_id = create_job(title=title, job_type=job_type, description=description, location=location, user_id=user_id)
    if brief.strip():
        update_job_brief(job_id, brief, title=title, description=description, location=location)
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/status")
def set_contractor_job_status(request: Request, job_id: int, status: str = Form(...)) -> RedirectResponse:
    require_user(request)
    update_job_status(job_id, status)
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/brief")
def set_contractor_job_brief(
    request: Request,
    job_id: int,
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    brief: str = Form(...),
) -> RedirectResponse:
    require_user(request)
    update_job_brief(job_id, brief, title=title, description=description, location=location)
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/leads")
def add_contractor_lead(
    request: Request,
    job_id: int,
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(""),
    category: str = Form("contractor"),
    source_url: str = Form(""),
    notes: str = Form(""),
    priority: int = Form(50),
) -> RedirectResponse:
    user = require_user(request)
    user_id = int(user["id"])
    if get_settings().contractor_billing_required and not can_add_paid_lead(user_id, job_id):
        return RedirectResponse(f"/contractor?job_id={job_id}&limit=leads", status_code=303)
    upsert_lead(
        job_id=job_id,
        name=name,
        phone=phone,
        email=email,
        category=category,
        source_url=source_url,
        notes=notes,
        priority=priority,
        status="pending",
    )
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/discover")
def discover_contractor_leads(
    request: Request,
    job_id: int,
    query: str = Form(""),
) -> RedirectResponse:
    user = require_user(request)
    if not can_use_paid_workflows(int(user["id"])):
        return RedirectResponse("/contractor/billing?required=1", status_code=303)
    if not can_add_paid_lead(int(user["id"]), job_id):
        return RedirectResponse(f"/contractor?job_id={job_id}&limit=leads", status_code=303)
    result = discover_leads_for_job(job_id, query=query)
    return RedirectResponse(
        f"/contractor?job_id={job_id}&discovered={int(result['created'])}&searched={int(result['searched'])}",
        status_code=303,
    )


@app.post("/contractor/jobs/{job_id}/leads/{lead_id}/approve")
def approve_contractor_lead(request: Request, job_id: int, lead_id: int) -> RedirectResponse:
    require_user(request)
    mark_job_lead_status(job_id, lead_id, "pending")
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/leads/{lead_id}/skip")
def skip_contractor_lead(request: Request, job_id: int, lead_id: int) -> RedirectResponse:
    require_user(request)
    mark_job_lead_status(job_id, lead_id, "skipped")
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/followups")
def add_contractor_followup(
    request: Request,
    job_id: int,
    channel: str = Form("text"),
    body: str = Form(""),
    due_at: str = Form(""),
) -> RedirectResponse:
    require_user(request)
    create_outreach_action(job_id=job_id, lead_id=None, channel=channel, body=body, due_at=due_at or None)
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/followups/execute")
def execute_contractor_followups(request: Request, job_id: int) -> RedirectResponse:
    user = require_user(request)
    if not can_use_paid_workflows(int(user["id"])):
        return RedirectResponse("/contractor/billing?required=1", status_code=303)
    result = execute_outreach_actions(job_id)
    return RedirectResponse(
        f"/contractor?job_id={job_id}"
        f"&outreach_sent={result['sent']}"
        f"&outreach_blocked={result['blocked']}"
        f"&outreach_failed={result['failed']}",
        status_code=303,
    )


@app.post("/contractor/jobs/{job_id}/call-loop")
def run_call_loop(request: Request, background_tasks: BackgroundTasks, job_id: int) -> RedirectResponse:
    user = require_user(request)
    if not can_use_paid_workflows(int(user["id"])):
        return RedirectResponse("/contractor/billing?required=1", status_code=303)
    if call_credits_remaining(int(user["id"])) <= 0:
        return RedirectResponse(f"/contractor?job_id={job_id}&limit=credits", status_code=303)
    background_tasks.add_task(place_calls, job_id=job_id, include_unknown_travel=True, user_id=int(user["id"]))
    return RedirectResponse(f"/contractor?job_id={job_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/test-call")
def run_test_call(request: Request, background_tasks: BackgroundTasks, job_id: int) -> RedirectResponse:
    _require_owner_user(request)
    background_tasks.add_task(place_test_call, job_id=job_id, to_number=get_settings().owner_phone)
    return RedirectResponse(f"/contractor?job_id={job_id}&test_call=started", status_code=303)


@app.post("/contractor/jobs/{job_id}/test-calls/cleanup")
def cleanup_test_calls(request: Request, job_id: int) -> RedirectResponse:
    _require_owner_user(request)
    deleted = delete_test_calls_for_job(job_id)
    return RedirectResponse(f"/contractor?job_id={job_id}&test_cleanup={deleted}", status_code=303)


@app.post("/contractor/jobs/{job_id}/test-agent")
def run_test_contractor_agent(request: Request, job_id: int, scenario: str = Form("available")) -> RedirectResponse:
    user = _require_owner_user(request)
    try:
        call_id = simulate_test_contractor_call(job_id=job_id, user_id=int(user["id"]), scenario=scenario)
    except RuntimeError:
        return RedirectResponse(f"/contractor?job_id={job_id}&limit=credits", status_code=303)
    return RedirectResponse(f"/contractor?job_id={job_id}&test_agent={call_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/test-agent/realtime")
async def run_realtime_test_contractor_agent(request: Request, job_id: int, scenario: str = Form("available")) -> RedirectResponse:
    user = _require_owner_user(request)
    try:
        call_id = await simulate_realtime_test_contractor_call(job_id=job_id, user_id=int(user["id"]), scenario=scenario)
    except RuntimeError as exc:
        if "credits" in str(exc).lower():
            return RedirectResponse(f"/contractor?job_id={job_id}&limit=credits", status_code=303)
        append_event(None, "realtime_test_agent_error", {"job_id": job_id, "error": str(exc)})
        return RedirectResponse(f"/contractor?job_id={job_id}&agent=error", status_code=303)
    return RedirectResponse(f"/contractor?job_id={job_id}&test_agent={call_id}", status_code=303)


@app.post("/contractor/jobs/{job_id}/agent")
def hand_job_to_agent(request: Request, background_tasks: BackgroundTasks, job_id: int) -> RedirectResponse:
    user = require_user(request)
    if not can_use_paid_workflows(int(user["id"])):
        return RedirectResponse("/contractor/billing?required=1", status_code=303)
    if call_credits_remaining(int(user["id"])) <= 0:
        return RedirectResponse(f"/contractor?job_id={job_id}&limit=credits", status_code=303)
    background_tasks.add_task(run_job_agent, job_id, int(user["id"]))
    return RedirectResponse(f"/contractor?job_id={job_id}&agent=started", status_code=303)


@app.post("/greenhouse/incoming")
async def incoming(request: Request) -> Response:
    form = await request.form()
    payload = dict(form)
    from_number = normalize_phone(str(payload.get("From", "")))
    lead = resolve_lead_for_phone(from_number, fallback_name=from_number or "Inbound caller")
    if lead is None:
        append_event(None, "incoming_call_unmatched", payload)
        body = """
<Response>
  <Say voice="alice">Hi, this is the customer's assistant. I could not find the current job context, so please text this number with your name, availability, and what you are calling about. Thank you.</Say>
</Response>
""".strip()
        return Response(body, media_type="application/xml")

    call_id = create_call(int(lead["id"]), direction="inbound")
    append_event(call_id, "incoming_call", payload)
    call_sid = str(payload.get("CallSid", ""))
    if call_sid:
        update_call(call_id, twilio_sid=call_sid, status="answered")

    settings = get_settings()
    host = settings.app_host.replace("https://", "").replace("http://", "")
    lead_name = html.escape(str(lead["name"]))
    body = f"""
<Response>
  <Connect>
    <Stream url="wss://{host}/greenhouse/stream/{call_id}">
      <Parameter name="lead_name" value="{lead_name}" />
      <Parameter name="direction" value="inbound" />
    </Stream>
  </Connect>
</Response>
""".strip()
    return Response(body, media_type="application/xml")


@app.post("/greenhouse/sms")
async def sms(request: Request) -> Response:
    form = await request.form()
    payload = dict(form)
    from_number = normalize_phone(str(payload.get("From", "")))
    to_number = normalize_phone(str(payload.get("To", "")))
    lead = resolve_lead_for_phone(from_number, fallback_name=from_number or "Inbound text")
    create_sms_message(
        direction="inbound",
        from_number=from_number,
        to_number=to_number,
        body=str(payload.get("Body", "")),
        twilio_sid=str(payload.get("MessageSid", "")) or None,
        status=str(payload.get("SmsStatus", "")) or None,
        raw_payload=payload,
    )
    if lead is not None and lead["job_id"] is not None:
        create_outreach_action(
            job_id=int(lead["job_id"]),
            lead_id=int(lead["id"]),
            channel="text",
            direction="inbound",
            status="received",
            body=str(payload.get("Body", "")),
            notes="Inbound contractor text received.",
        )
    append_event(None, "incoming_sms", payload)
    return Response("<Response></Response>", media_type="application/xml")


@app.post("/greenhouse/email")
async def inbound_email(request: Request):
    settings = get_settings()
    expected = settings.contractor_email_ingest_secret
    authorization = request.headers.get("authorization", "")
    if not expected or authorization != f"Bearer {expected}":
        return Response("unauthorized", status_code=401)

    payload = await request.json()
    from_email = str(payload.get("from", "")).strip().lower()
    to_email = str(payload.get("to", "")).strip().lower()
    lead = resolve_lead_for_email(from_email, fallback_name=from_email or "Inbound email")
    create_email_message(
        direction="inbound",
        from_email=from_email,
        to_email=to_email,
        subject=str(payload.get("subject", "")),
        body=str(payload.get("text", "")),
        message_id=str(payload.get("message_id", "")) or None,
        status="received",
        raw_payload=payload,
    )
    if lead is not None and lead["job_id"] is not None:
        create_outreach_action(
            job_id=int(lead["job_id"]),
            lead_id=int(lead["id"]),
            channel="email",
            direction="inbound",
            status="received",
            body=str(payload.get("text", "")),
            notes=f"Inbound contractor email received: {payload.get('subject', '')}",
        )
    append_event(None, "incoming_email", payload)
    return {"ok": "true"}


@app.post("/greenhouse/twiml/{call_id}")
async def twiml(call_id: int, request: Request) -> Response:
    lead = lead_for_call(call_id)
    if lead is None:
        return Response("<Response><Say>Call configuration not found.</Say></Response>", media_type="application/xml")

    form = await request.form()
    append_event(call_id, "twiml", dict(form))
    call_sid = str(form.get("CallSid", ""))
    if call_sid:
        update_call(call_id, twilio_sid=call_sid, status="answered")

    settings = get_settings()
    host = settings.app_host.replace("https://", "").replace("http://", "")
    lead_name = html.escape(str(lead["name"]))
    body = f"""
<Response>
  <Connect>
    <Stream url="wss://{host}/greenhouse/stream/{call_id}">
      <Parameter name="lead_name" value="{lead_name}" />
    </Stream>
  </Connect>
</Response>
""".strip()
    return Response(body, media_type="application/xml")


@app.post("/greenhouse/status/{call_id}")
async def status(call_id: int, request: Request) -> dict[str, str]:
    form = await request.form()
    payload = dict(form)
    append_event(call_id, "twilio_status", payload)
    call_status = str(payload.get("CallStatus", ""))
    if call_status:
        update_call(call_id, status=call_status)
        if call_status == "completed":
            lead = lead_for_call(call_id)
            if lead is not None:
                mark_lead_status(int(lead["id"]), "called")
        elif call_status in {"busy", "failed", "no-answer", "canceled"}:
            lead = lead_for_call(call_id)
            if lead is not None:
                mark_lead_status(int(lead["id"]), "failed")
    return {"ok": "true"}


@app.websocket("/greenhouse/stream/{call_id}")
async def stream(call_id: int, websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await bridge_call(call_id, websocket)
    except WebSocketDisconnect:
        append_event(call_id, "websocket_disconnect", {})
