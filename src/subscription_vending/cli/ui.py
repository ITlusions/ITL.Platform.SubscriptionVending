"""vending ui — local web management dashboard for ITL Subscription Vending.

Start with:
    vending ui [--port 8080] [--remote http://vending-host:8000]

Remote mode: all API calls are proxied to the target vending API.
Local mode (no --remote):
  - /config  reads Settings from environment / .env file.
  - /health  always returns OK (the UI server itself is healthy).
  - /jobs and /provision show a "configure --remote" prompt.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

logger = logging.getLogger(__name__)

# ── Built-in Entra ID defaults ────────────────────────────────────────────────
# Set these to ship SSO out of the box.  Users can still override with CLI
# flags or env vars — explicit values always win.
_DEFAULT_TENANT_ID: str | None = None   # e.g. "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
_DEFAULT_CLIENT_ID: str | None = None   # e.g. "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"
_DEFAULT_API_SCOPE: str | None = None   # e.g. "api://<client-id>/.default"

# Module-level config — set by configure() before uvicorn starts
_remote_url: str | None = None
_port: int = 8080
_auth_config: dict | None = None  # None = SSO disabled


def configure(
    *,
    remote_url: str | None,
    tenant_id: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    required_group: str | None = None,
    required_role: str | None = None,
    api_scope: str | None = None,
    port: int = 8080,
) -> None:
    global _remote_url, _auth_config, _port
    _remote_url = remote_url.rstrip("/") if remote_url else None
    _port = port
    # Fall back to built-in defaults when the caller passes nothing.
    # Explicit None means "not provided by caller", so only override when still None.
    effective_tenant_id = tenant_id or _DEFAULT_TENANT_ID
    effective_client_id = client_id or _DEFAULT_CLIENT_ID
    effective_api_scope = api_scope or _DEFAULT_API_SCOPE
    # SessionMiddleware is always registered — auth routes and future use require it
    app.add_middleware(
        SessionMiddleware,
        secret_key=secrets.token_hex(32),
        https_only=False,
        same_site="lax",
    )
    if effective_tenant_id and effective_client_id:
        _auth_config = {
            "tenant_id": effective_tenant_id,
            "client_id": effective_client_id,
            "client_secret": client_secret,  # None = public client / PKCE
            "redirect_uri": redirect_uri or f"http://127.0.0.1:{port}/auth/callback",
            "authority": f"https://login.microsoftonline.com/{effective_tenant_id}",
            "required_group": required_group,  # group object ID; None = no check
            "required_role":  required_role,    # app role value; None = no check
            "api_scope": effective_api_scope,   # API scope to request an access_token for
        }


# ── HTML helpers ──────────────────────────────────────────────────────────────

_TAILWIND = '<script src="https://cdn.tailwindcss.com"></script>'
_HTMX = '<script src="https://unpkg.com/htmx.org@2.0.0/dist/htmx.min.js"></script>'
_SPINNER_CSS = """<style>
  .htmx-indicator { display: none; }
  .htmx-request .htmx-indicator { display: inline; }
  .htmx-request.htmx-indicator { display: inline; }
</style>"""


def _layout(title: str, content: str, *, active: str = "", user: dict | None = None) -> str:
    nav_items = [
        ("dashboard", "/dashboard", "Dashboard"),
        ("jobs",      "/jobs",      "Jobs"),
        ("provision", "/provision", "Provision"),
        ("config",    "/config",    "Config"),
    ]
    nav_html = ""
    for key, href, label in nav_items:
        active_cls = (
            "bg-blue-700 text-white"
            if active == key
            else "text-gray-300 hover:bg-gray-700 hover:text-white"
        )
        nav_html += (
            f'<a href="{href}" '
            f'class="px-3 py-1.5 rounded {active_cls} text-sm font-medium transition-colors">'
            f"{label}</a>\n"
        )

    user_section = ""
    if user and _auth_config:
        name = user.get("name") or user.get("email", "User")
        email = user.get("email", "")
        user_section = (
            f'<div class="ml-auto flex items-center gap-3">'
            f'<span class="text-xs text-gray-400" title="{email}">&#x1F464; {name}</span>'
            f'<a href="/auth/logout" class="text-xs bg-red-900 hover:bg-red-800 '
            f'text-red-300 px-2.5 py-1 rounded transition-colors">Sign out</a>'
            f'</div>'
        )
    elif _remote_url:
        user_section = (
            f'<span class="ml-auto text-xs text-gray-400 font-mono">{_remote_url}</span>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Vending UI</title>
  {_TAILWIND}
  {_HTMX}
  {_SPINNER_CSS}
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
  <nav class="bg-gray-800 border-b border-gray-700 px-6 py-2.5 flex items-center gap-3 shadow-md">
    <span class="font-bold text-blue-400 mr-3 text-sm tracking-wide">
      &#8853; Subscription Vending
    </span>
    {nav_html}
    {user_section}
  </nav>
  <main class="p-6 max-w-5xl mx-auto">
    {content}
  </main>
</body>
</html>"""


def _error_html(msg: str) -> str:
    return (
        f'<div class="bg-red-950 border border-red-700 text-red-300 rounded p-3 text-sm">'
        f"{msg}</div>"
    )


def _warn_html(msg: str) -> str:
    return (
        f'<div class="bg-yellow-950 border border-yellow-700 text-yellow-300 rounded p-3 text-sm">'
        f"{msg}</div>"
    )


def _badge(ok: bool) -> str:
    if ok:
        return (
            '<span class="inline-block bg-green-800 text-green-200 text-xs '
            'px-2 py-0.5 rounded font-mono">OK</span>'
        )
    return (
        '<span class="inline-block bg-red-800 text-red-200 text-xs '
        'px-2 py-0.5 rounded font-mono">ERROR</span>'
    )


def _no_remote_html() -> str:
    return _warn_html(
        "No remote API configured. Pass <code>--remote &lt;URL&gt;</code> "
        "to connect to a running vending API."
    )


# ── proxy helpers ─────────────────────────────────────────────────────────────

async def _api_get(path: str, request: Request | None = None, params: dict | None = None) -> dict:
    """GET from remote API. Raises RuntimeError when no remote is configured."""
    if not _remote_url:
        raise RuntimeError("No remote URL configured — pass --remote <URL>")
    token = (request.session.get("api_token") if request else None) if _auth_config else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{_remote_url}{path}", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _api_post(path: str, body: dict, request: Request | None = None) -> dict:
    if not _remote_url:
        raise RuntimeError("No remote URL configured — pass --remote <URL>")
    token = (request.session.get("api_token") if request else None) if _auth_config else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{_remote_url}{path}", json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _api_delete(path: str, request: Request | None = None) -> dict:
    if not _remote_url:
        raise RuntimeError("No remote URL configured — pass --remote <URL>")
    token = (request.session.get("api_token") if request else None) if _auth_config else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(f"{_remote_url}{path}", headers=headers)
        resp.raise_for_status()
        return resp.json()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# ── Auth infrastructure ───────────────────────────────────────────────────────

class _NotAuthenticatedException(Exception):
    def __init__(self, next_url: str) -> None:
        self.next_url = next_url


@app.exception_handler(_NotAuthenticatedException)
async def _not_auth_handler(
    request: Request, exc: _NotAuthenticatedException
) -> RedirectResponse:
    return RedirectResponse(url=f"/auth/login?next={exc.next_url}")


async def require_auth(request: Request) -> dict:
    """FastAPI dependency — enforces SSO when configured.

    Returns the signed-in user dict ``{name, email, oid}``.
    When SSO is disabled (no --tenant-id/--client-id/--client-secret),
    returns a placeholder so routes work without branching.
    """
    if _auth_config is None:
        return {"name": "Local", "email": ""}
    user = request.session.get("user")
    if not user:
        raise _NotAuthenticatedException(next_url=str(request.url.path))
    return user


@app.get("/", response_class=RedirectResponse)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(require_auth)) -> HTMLResponse:
    content = """
<h1 class="text-2xl font-bold mb-6">Dashboard</h1>
<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
  <div hx-get="/fragment/health" hx-trigger="load, every 30s" hx-swap="outerHTML">
    <div class="bg-gray-800 rounded-lg p-4 animate-pulse">
      <p class="text-gray-500 text-xs">Loading health…</p>
    </div>
  </div>
  <div class="col-span-2"
       hx-get="/fragment/stats" hx-trigger="load, every 15s" hx-swap="outerHTML">
    <div class="bg-gray-800 rounded-lg p-4 animate-pulse">
      <p class="text-gray-500 text-xs">Loading queue stats…</p>
    </div>
  </div>
</div>
<div hx-get="/fragment/jobs/recent" hx-trigger="load, every 20s" hx-swap="outerHTML">
  <div class="bg-gray-800 rounded-lg p-4 animate-pulse">
    <p class="text-gray-500 text-xs">Loading recent jobs…</p>
  </div>
</div>
"""
    return HTMLResponse(_layout("Dashboard", content, active="dashboard", user=user))


@app.get("/fragment/health", response_class=HTMLResponse)
async def frag_health(request: Request) -> HTMLResponse:
    try:
        data = await _api_get("/health", request)
        ok = data.get("status") == "ok"
        inner = f"""<div class="flex items-center gap-2 mb-1">
  <span class="font-semibold text-sm">API Health</span>
  {_badge(ok)}
</div>
<p class="text-gray-400 text-xs mt-1">{_remote_url or "local"}</p>"""
    except RuntimeError:
        inner = f"""<div class="flex items-center gap-2 mb-1">
  <span class="font-semibold text-sm">API Health</span>
  <span class="inline-block bg-gray-700 text-gray-400 text-xs px-2 py-0.5 rounded font-mono">N/A</span>
</div>
<p class="text-gray-500 text-xs mt-1">No remote configured</p>"""
    except Exception as exc:
        inner = f"""<div class="flex items-center gap-2 mb-1">
  <span class="font-semibold text-sm">API Health</span>
  {_badge(False)}
</div>
<p class="text-red-400 text-xs mt-1">{exc}</p>"""

    return HTMLResponse(
        f'<div class="bg-gray-800 rounded-lg p-4"'
        f' hx-get="/fragment/health" hx-trigger="every 30s" hx-swap="outerHTML">'
        f"{inner}</div>"
    )


@app.get("/fragment/stats", response_class=HTMLResponse)
async def frag_stats(request: Request) -> HTMLResponse:
    try:
        data = await _api_get("/jobs/stats", request)
        rows = ""
        for stat in data.get("queues", []):
            count = stat.get("approximate_message_count", "?")
            count_class = "text-yellow-300 font-bold" if isinstance(count, int) and count > 0 else "text-gray-300"
            rows += (
                f"<tr class=\"border-t border-gray-700\">"
                f"<td class=\"py-2 pr-6 font-mono text-xs text-gray-400\">{stat.get('queue', '')}</td>"
                f"<td class=\"py-2 pr-6 text-right text-sm {count_class}\">{count}</td>"
                f"<td class=\"py-2 text-xs text-gray-500\">{stat.get('description', '')}</td>"
                f"</tr>"
            )
        inner = f"""<div class="font-semibold text-sm mb-3">Queue Statistics</div>
<table class="w-full text-left">
  <thead>
    <tr class="text-xs text-gray-500">
      <th class="py-1.5 pr-6">Queue</th>
      <th class="py-1.5 pr-6 text-right">Messages</th>
      <th class="py-1.5">Description</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""
    except RuntimeError:
        inner = _no_remote_html()
    except Exception as exc:
        inner = _error_html(f"Could not load stats: {exc}")

    return HTMLResponse(
        f'<div class="col-span-2 bg-gray-800 rounded-lg p-4"'
        f' hx-get="/fragment/stats" hx-trigger="every 15s" hx-swap="outerHTML">'
        f"{inner}</div>"
    )


@app.get("/fragment/jobs/recent", response_class=HTMLResponse)
async def frag_jobs_recent(request: Request) -> HTMLResponse:
    try:
        data = await _api_get("/jobs/list", request, params={"count": 5})
        rows = _jobs_rows(data.get("jobs", []))
        inner = (
            '<div class="font-semibold text-sm mb-3">Recent Jobs</div>'
            + _jobs_table(rows, empty_msg="No pending jobs in the provisioning queue")
        )
    except RuntimeError:
        inner = _no_remote_html()
    except Exception as exc:
        inner = _error_html(f"Could not load jobs: {exc}")

    return HTMLResponse(
        f'<div class="bg-gray-800 rounded-lg p-4"'
        f' hx-get="/fragment/jobs/recent" hx-trigger="every 20s" hx-swap="outerHTML">'
        f"{inner}</div>"
    )


# ── Jobs page ─────────────────────────────────────────────────────────────────

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, user: dict = Depends(require_auth)) -> HTMLResponse:
    content = """
<div class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-bold">Jobs</h1>
  <button class="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-3 py-1.5 rounded transition-colors"
          hx-get="/fragment/jobs/list" hx-target="#jobs-list" hx-swap="innerHTML">
    &#8635; Refresh
  </button>
</div>

<div id="jobs-list"
     hx-get="/fragment/jobs/list" hx-trigger="load" hx-swap="innerHTML">
  <p class="text-gray-500 text-sm">Loading…</p>
</div>

<div class="flex items-center justify-between mt-10 mb-4">
  <h2 class="text-xl font-semibold text-red-400">Dead-Letter Queue</h2>
  <button class="text-xs bg-red-950 hover:bg-red-900 text-red-300 border border-red-700 px-3 py-1.5 rounded transition-colors"
          hx-delete="/fragment/jobs/dlq"
          hx-target="#dlq-list"
          hx-swap="innerHTML"
          hx-confirm="Purge ALL messages from the dead-letter queue?">
    Purge DLQ
  </button>
</div>

<div id="dlq-list"
     hx-get="/fragment/jobs/dlq" hx-trigger="load" hx-swap="innerHTML">
  <p class="text-gray-500 text-sm">Loading…</p>
</div>
"""
    return HTMLResponse(_layout("Jobs", content, active="jobs", user=user))


@app.get("/fragment/jobs/list", response_class=HTMLResponse)
async def frag_jobs_list(request: Request) -> HTMLResponse:
    try:
        data = await _api_get("/jobs/list", request, params={"count": 32})
        rows = _jobs_rows(data.get("jobs", []))
        html = _jobs_table(rows, empty_msg="No pending jobs in the provisioning queue")
    except RuntimeError:
        html = _no_remote_html()
    except Exception as exc:
        html = _error_html(f"Could not load jobs: {exc}")
    return HTMLResponse(html)


@app.get("/fragment/jobs/dlq", response_class=HTMLResponse)
async def frag_jobs_dlq(request: Request) -> HTMLResponse:
    try:
        data = await _api_get("/jobs/dlq", request, params={"count": 32})
        rows = _jobs_rows(data.get("jobs", []))
        html = _jobs_table(rows, empty_msg="Dead-letter queue is empty")
    except RuntimeError:
        html = _no_remote_html()
    except Exception as exc:
        html = _error_html(f"Could not load DLQ: {exc}")
    return HTMLResponse(html)


@app.delete("/fragment/jobs/dlq", response_class=HTMLResponse)
async def frag_jobs_dlq_purge(request: Request) -> HTMLResponse:
    try:
        await _api_delete("/jobs/dlq", request)
        html = '<p class="text-green-400 text-sm">DLQ purged successfully.</p>'
    except RuntimeError:
        html = _no_remote_html()
    except Exception as exc:
        html = _error_html(f"Purge failed: {exc}")
    return HTMLResponse(html)


def _jobs_rows(jobs: list[dict[str, Any]]) -> str:
    rows = ""
    for job in jobs:
        job_id    = job.get("job_id", "?")
        sub_name  = job.get("subscription_name", "?")
        sub_id    = job.get("subscription_id", "?")
        attempt   = job.get("attempt", "?")
        enqueued  = job.get("enqueued_at", "")
        rows += (
            f'<tr class="border-t border-gray-700 hover:bg-gray-750">'
            f'<td class="py-2 pr-4 font-mono text-xs text-gray-400" title="{job_id}">'
            f'{job_id[:8]}…</td>'
            f'<td class="py-2 pr-4 text-sm">{sub_name}</td>'
            f'<td class="py-2 pr-4 font-mono text-xs text-gray-400" title="{sub_id}">'
            f'{sub_id[:8]}…</td>'
            f'<td class="py-2 pr-4 text-sm text-center">{attempt}</td>'
            f'<td class="py-2 text-xs text-gray-500">{enqueued}</td>'
            f"</tr>"
        )
    return rows


def _jobs_table(rows: str, *, empty_msg: str) -> str:
    if not rows:
        return f'<p class="text-gray-500 text-sm italic">{empty_msg}</p>'
    return (
        '<div class="overflow-x-auto">'
        '<table class="w-full text-left">'
        "<thead>"
        '<tr class="text-xs text-gray-500">'
        '<th class="py-2 pr-4">Job ID</th>'
        '<th class="py-2 pr-4">Subscription</th>'
        '<th class="py-2 pr-4">Sub ID</th>'
        '<th class="py-2 pr-4 text-center">Attempt</th>'
        '<th class="py-2">Enqueued</th>'
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></div>"
    )


# ── Provision page ────────────────────────────────────────────────────────────

_INPUT_CLS = (
    "w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm "
    "font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
)

@app.get("/provision", response_class=HTMLResponse)
async def provision_page(request: Request, user: dict = Depends(require_auth)) -> HTMLResponse:
    content = f"""
<h1 class="text-2xl font-bold mb-6">Provision / Preflight</h1>

<div class="bg-gray-800 rounded-lg p-6 max-w-xl">
  <form hx-post="/fragment/provision"
        hx-target="#provision-result"
        hx-swap="innerHTML"
        hx-indicator="#prov-spinner">

    <div class="mb-4">
      <label class="block text-sm text-gray-400 mb-1.5">
        Subscription ID <span class="text-red-400">*</span>
      </label>
      <input name="sub_id" required type="text"
             placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
             class="{_INPUT_CLS}">
    </div>

    <div class="mb-4">
      <label class="block text-sm text-gray-400 mb-1.5">
        Subscription Name <span class="text-red-400">*</span>
      </label>
      <input name="sub_name" required type="text"
             placeholder="my-subscription"
             class="{_INPUT_CLS}">
    </div>

    <div class="mb-5">
      <label class="block text-sm text-gray-400 mb-1.5">
        Management Group ID
        <span class="text-gray-600 text-xs">(optional — falls back to root)</span>
      </label>
      <input name="mg_id" type="text" placeholder="my-management-group"
             class="{_INPUT_CLS}">
    </div>

    <div class="mb-6 flex items-center gap-2">
      <input name="dry_run" type="checkbox" id="dry_run" value="true"
             class="w-4 h-4 rounded bg-gray-700 border-gray-600 text-blue-500
                    focus:ring-blue-500 focus:ring-offset-gray-900">
      <label for="dry_run" class="text-sm text-gray-300">
        Dry run <span class="text-gray-500 text-xs">(skip Azure mutations)</span>
      </label>
    </div>

    <div class="flex gap-3 items-center">
      <button type="submit" name="action" value="provision"
              class="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded
                     text-sm font-medium transition-colors">
        Provision
      </button>
      <button type="submit" name="action" value="preflight"
              class="bg-gray-600 hover:bg-gray-500 text-white px-4 py-2 rounded
                     text-sm font-medium transition-colors">
        Preflight only
      </button>
      <span id="prov-spinner" class="htmx-indicator text-gray-400 text-sm ml-2">
        Running&#8230;
      </span>
    </div>

  </form>
</div>

<div id="provision-result" class="mt-6 max-w-xl"></div>
"""
    return HTMLResponse(_layout("Provision", content, active="provision", user=user))


@app.post("/fragment/provision", response_class=HTMLResponse)
async def frag_provision(
    request: Request,
    sub_id: str = Form(...),
    sub_name: str = Form(...),
    mg_id: str = Form(""),
    dry_run: str = Form(""),
    action: str = Form("provision"),
) -> HTMLResponse:
    if not _remote_url:
        return HTMLResponse(_no_remote_html())

    is_dry = dry_run.lower() == "true" or action == "preflight"
    endpoint = "/webhook/preflight" if action == "preflight" else "/webhook/replay"
    payload: dict[str, Any] = {
        "subscription_id": sub_id,
        "subscription_name": sub_name,
        "management_group_id": mg_id,
    }
    if action != "preflight":
        payload["dry_run"] = is_dry

    try:
        data = await _api_post(endpoint, payload, request)
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(
            _error_html(f"HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        )
    except Exception as exc:
        return HTMLResponse(_error_html(str(exc)))

    success = data.get("status") == "ok"
    errors  = data.get("errors", [])
    plan    = data.get("plan", [])

    error_items = ""
    if errors:
        lis = "".join(f'<li class="font-mono text-xs text-red-300 py-0.5">&#8226; {e}</li>' for e in errors)
        error_items = (
            f'<div class="mt-3">'
            f'<p class="text-xs text-gray-500 mb-1">Errors:</p>'
            f'<ul class="space-y-0.5">{lis}</ul></div>'
        )

    plan_items = ""
    if plan:
        lis = "".join(f'<li class="font-mono text-xs text-gray-400 py-0.5">&#8226; {s}</li>' for s in plan)
        plan_items = (
            f'<div class="mt-3">'
            f'<p class="text-xs text-gray-500 mb-1">Plan:</p>'
            f'<ul class="space-y-0.5">{lis}</ul></div>'
        )

    return HTMLResponse(
        f'<div class="bg-gray-800 rounded-lg p-4">'
        f'<div class="flex items-center gap-2 mb-2">'
        f'<span class="text-sm font-semibold">{action.title()} result</span>'
        f"{_badge(success)}"
        f"</div>"
        f"{plan_items}"
        f"{error_items}"
        f"</div>"
    )


# ── Config page ────────────────────────────────────────────────────────────────

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, user: dict = Depends(require_auth)) -> HTMLResponse:
    content = """
<div class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-bold">Configuration</h1>
  <button class="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-3 py-1.5 rounded transition-colors"
          hx-get="/fragment/config" hx-target="#config-content" hx-swap="innerHTML">
    &#8635; Refresh
  </button>
</div>
<div id="config-content"
     hx-get="/fragment/config" hx-trigger="load" hx-swap="innerHTML">
  <p class="text-gray-500 text-sm">Loading…</p>
</div>
"""
    return HTMLResponse(_layout("Config", content, active="config", user=user))


@app.get("/fragment/config", response_class=HTMLResponse)
async def frag_config(request: Request) -> HTMLResponse:
    # Remote mode: proxy to /config (secrets already redacted server-side)
    if _remote_url:
        try:
            data = await _api_get("/config", request)
        except Exception as exc:
            return HTMLResponse(_error_html(f"Could not load config: {exc}"))
        source_label = f"Source: <code>{_remote_url}/config</code>"
    else:
        # Local mode: read Settings directly
        try:
            from ..core.config import get_settings  # noqa: PLC0415
            settings = get_settings()
            _SECRET_FIELDS = {"azure_client_secret", "worker_secret", "event_grid_sas_key"}
            data = settings.model_dump()
            for field in _SECRET_FIELDS:
                if data.get(field):
                    data[field] = "***"
            for key, val in data.items():
                if hasattr(val, "value"):
                    data[key] = val.value
        except Exception as exc:
            return HTMLResponse(_error_html(f"Could not load local settings: {exc}"))
        source_label = "Source: local environment / .env"

    rows = ""
    for key, val in sorted(data.items()):
        if val in (None, ""):
            val_html = '<span class="text-gray-600 italic text-xs">not set</span>'
        elif val == "***":
            val_html = '<span class="text-yellow-500 font-mono text-xs">***</span>'
        else:
            val_html = f'<span class="font-mono text-sm text-gray-300">{val}</span>'

        rows += (
            f'<tr class="border-t border-gray-700">'
            f'<td class="py-2 pr-8 text-sm text-gray-400 whitespace-nowrap">{key}</td>'
            f'<td class="py-2">{val_html}</td>'
            f"</tr>"
        )

    return HTMLResponse(
        f'<p class="text-xs text-gray-600 mb-3">{source_label}</p>'
        f'<div class="bg-gray-800 rounded-lg overflow-hidden">'
        f'<table class="w-full text-left">'
        f'<thead><tr class="text-xs text-gray-500 bg-gray-750">'
        f'<th class="py-2 px-4 pr-8">Setting</th>'
        f'<th class="py-2 px-4">Value</th>'
        f"</tr></thead>"
        f"<tbody class=\"divide-y-0 px-4\">{rows}</tbody>"
        f"</table></div>"
    )


# ── Auth routes (Entra ID SSO) ─────────────────────────────────────────────────

def _decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload claims without signature verification."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        import base64  # noqa: PLC0415
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def _claims_to_identity(claims: dict) -> dict:
    """Extract name/email/oid from JWT claims."""
    name  = claims.get("name") or claims.get("preferred_username") or claims.get("upn", "")
    email = claims.get("email") or claims.get("upn") or claims.get("preferred_username", "")
    oid   = claims.get("oid") or claims.get("sub", "")
    return {"name": name, "email": email, "oid": oid}


# Environment variable names checked in order (highest priority first)
_AZ_TOKEN_ENVVARS = [
    "ARM_ACCESS_TOKEN",        # Terraform / CI-CD convention
    "AZURE_ACCESS_TOKEN",      # explicit Azure token
    "VENDING_TOKEN",           # project-specific (set by `vending --token`)
]


def _try_env_token() -> dict | None:
    """Check well-known environment variables for a pre-set Azure Bearer token.

    Returns a dict with keys ``token``, ``name``, ``email``, ``source``
    or ``None`` when no token is found in the environment.
    """
    import os  # noqa: PLC0415

    for envvar in _AZ_TOKEN_ENVVARS:
        token = os.environ.get(envvar, "").strip()
        if not token:
            continue
        claims  = _decode_jwt_claims(token)
        identity = _claims_to_identity(claims)
        return {**identity, "token": token, "source": envvar}
    return None


def _try_az_token(scope: str | None = None) -> dict | None:
    """Try to get a token from the Azure CLI on the local machine.

    Returns a dict with keys ``token``, ``name``, ``email``, ``source``
    on success, or ``None`` when az is not installed, not logged in, or times out.
    """
    import subprocess  # noqa: PLC0415

    cmd = ["az", "account", "get-access-token", "--output", "json"]
    if scope:
        cmd += ["--scope", scope]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
    except Exception:
        return None

    token = data.get("accessToken")
    if not token:
        return None

    # Also fetch account info for a friendly display name
    name = ""
    email = ""
    try:
        acc = subprocess.run(
            ["az", "account", "show", "--output", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if acc.returncode == 0:
            acc_data = json.loads(acc.stdout)
            name  = acc_data.get("user", {}).get("name", "")
            email = name  # az returns UPN as "name" for user accounts
    except Exception:
        pass

    return {"token": token, "name": name, "email": email, "source": "az cli"}


def _try_any_token(scope: str | None = None) -> dict | None:
    """Check env vars first, then fall back to the Azure CLI."""
    return _try_env_token() or _try_az_token(scope)


def _msal_app():
    """Return an MSAL app instance for the current auth config.

    - ConfidentialClientApplication when client_secret is set.
    - PublicClientApplication (PKCE, no secret) otherwise.
      Requires "Allow public client flows" enabled on the app registration.
    """
    try:
        import msal  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "msal is not installed. Run: pip install msal"
        ) from e
    cfg = _auth_config
    if cfg["client_secret"]:
        return msal.ConfidentialClientApplication(
            cfg["client_id"],
            authority=cfg["authority"],
            client_credential=cfg["client_secret"],
        )
    return msal.PublicClientApplication(
        cfg["client_id"],
        authority=cfg["authority"],
    )


@app.get("/auth/login", response_class=HTMLResponse, response_model=None)
async def auth_login(
    request: Request, next: str = "/dashboard"
) -> HTMLResponse | RedirectResponse:
    """Show login page with SSO and token-paste options."""
    if _auth_config is None:
        return RedirectResponse(url="/dashboard")
    if request.session.get("user"):
        return RedirectResponse(url=next)

    api_scope = (_auth_config or {}).get("api_scope", "")

    # Detect a token from env vars or an existing Azure CLI session
    import asyncio  # noqa: PLC0415
    loop = asyncio.get_event_loop()
    az_session = await loop.run_in_executor(None, _try_any_token, api_scope or None)

    az_card = ""
    if az_session:
        display = az_session["name"] or az_session["email"] or "your Azure account"
        source  = az_session.get("source", "az cli")
        source_label = (
            f"environment variable <code>{source}</code>"
            if source in _AZ_TOKEN_ENVVARS
            else "Azure CLI"
        )
        az_card = f"""
    <!-- Auto-detect card -->
    <div class="bg-green-950 border border-green-700 rounded-xl p-6 shadow-lg">
      <div class="flex items-center gap-2 mb-1">
        <span class="inline-block w-2 h-2 rounded-full bg-green-400"></span>
        <h2 class="text-base font-semibold text-green-200">Azure session detected</h2>
      </div>
      <p class="text-green-300 text-sm mb-4">
        Found a token for <strong>{display}</strong> via {source_label}.
        Click below to continue — no extra steps needed.
      </p>
      <a href="/auth/az-login?next={next}"
         class="inline-block bg-green-700 hover:bg-green-600 text-white font-medium
                px-5 py-2.5 rounded-lg transition-colors text-sm">
        Continue as {display} &rsaquo;
      </a>
    </div>"""

    if api_scope:
        az_cmd = (
            f"az account get-access-token --scope &quot;{api_scope}&quot; "
            f"--query accessToken -o tsv"
        )
    else:
        az_cmd = "az account get-access-token --query accessToken -o tsv"

    content = f"""
<div class="min-h-[70vh] flex items-center justify-center">
  <div class="w-full max-w-2xl space-y-6">
    <div class="text-center mb-2">
      <h1 class="text-2xl font-bold text-white">Sign in to Subscription Vending</h1>
      <p class="text-gray-400 text-sm mt-1">Choose how you want to access the management UI.</p>
    </div>
    {az_card}

    <!-- SSO card -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-6 shadow-lg">
      <h2 class="text-base font-semibold mb-1">Sign in with your Microsoft account</h2>
      <p class="text-gray-400 text-sm mb-4">
        Log in with your organisation account. You will be redirected to Microsoft
        and returned here automatically.
      </p>
      <a href="/auth/sso?next={next}"
         class="inline-block bg-blue-600 hover:bg-blue-500 text-white font-medium
                px-5 py-2.5 rounded-lg transition-colors text-sm">
        Sign in with Microsoft &rsaquo;
      </a>
    </div>

    <!-- Token card -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-6 shadow-lg">
      <h2 class="text-base font-semibold mb-1">Use an access token</h2>
      <p class="text-gray-400 text-sm mb-3">
        If you have the Azure CLI installed, run the command below to get a token,
        then paste it in the field.
      </p>
      <div class="bg-gray-900 rounded-lg px-4 py-2.5 font-mono text-xs text-green-300
                  break-all mb-4 select-all border border-gray-700">
        {az_cmd}
      </div>
      <form method="post" action="/auth/token" class="space-y-3">
        <input type="hidden" name="next" value="{next}">
        <textarea name="token" rows="3" required
          placeholder="Paste your access token here…"
          class="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2
                 text-xs font-mono text-gray-200 placeholder-gray-600
                 focus:outline-none focus:border-blue-500 resize-none"></textarea>
        <button type="submit"
          class="bg-gray-700 hover:bg-gray-600 text-white font-medium
                 px-5 py-2 rounded-lg transition-colors text-sm">
          Sign in with token &rsaquo;
        </button>
      </form>
    </div>
  </div>
</div>
"""
    return HTMLResponse(_layout("Sign in", content))


@app.get("/auth/az-login", response_model=None)
async def auth_az_login(
    request: Request, next: str = "/dashboard"
) -> HTMLResponse | RedirectResponse:
    """One-click login using an existing Azure CLI session on the local machine."""
    import asyncio  # noqa: PLC0415

    api_scope = (_auth_config or {}).get("api_scope") if _auth_config else None
    loop = asyncio.get_event_loop()
    az_session = await loop.run_in_executor(None, _try_any_token, api_scope)

    if not az_session:
        return HTMLResponse(
            _layout(
                "Sign-in Error",
                _error_html(
                    "No Azure token found in environment variables or Azure CLI. "
                    "Set <code>ARM_ACCESS_TOKEN</code> or run <code>az login</code> and try again."
                ),
            ),
            status_code=401,
        )

    request.session["user"] = {
        "name":  az_session["name"],
        "email": az_session["email"],
        "oid":   "",
    }
    request.session["api_token"] = az_session["token"]
    return RedirectResponse(url=next, status_code=303)


@app.get("/auth/sso")
async def auth_sso(request: Request, next: str = "/dashboard") -> RedirectResponse:
    """Initiate the Entra ID PKCE flow and redirect to the sign-in page."""
    if _auth_config is None:
        return RedirectResponse(url="/dashboard")
    request.session["auth_next"] = next
    msal_instance = _msal_app()
    scopes = ["openid", "profile", "email"]
    api_scope = (_auth_config or {}).get("api_scope")
    if api_scope:
        scopes.append(api_scope)
    flow = msal_instance.initiate_auth_code_flow(
        scopes=scopes,
        redirect_uri=_auth_config["redirect_uri"],
    )
    request.session["auth_flow"] = flow  # stores state + PKCE verifier
    return RedirectResponse(url=flow["auth_uri"])


@app.post("/auth/token", response_model=None)
async def auth_token_submit(
    request: Request,
    token: str = Form(...),
    next: str = Form("/dashboard"),
) -> HTMLResponse | RedirectResponse:
    """Accept a pasted Bearer token, decode claims, and create a UI session.

    Signature verification is intentionally skipped here — the token is validated
    by the API (require_bearer) on every actual API call.  We only decode the
    payload to extract display information (name, email).
    """
    import base64  # noqa: PLC0415

    token = token.strip()
    parts = token.split(".")
    if len(parts) != 3:
        return HTMLResponse(
            _layout(
                "Sign-in Error",
                _error_html("That does not look like a valid JWT. Please try again."),
            ),
            status_code=400,
        )

    try:
        # Base64url-decode the payload (pad to multiple of 4)
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        claims: dict = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return HTMLResponse(
            _layout(
                "Sign-in Error",
                _error_html("Could not decode the token. Make sure you copied it completely."),
            ),
            status_code=400,
        )

    name  = claims.get("name") or claims.get("preferred_username") or claims.get("upn", "")
    email = claims.get("email") or claims.get("upn") or claims.get("preferred_username", "")
    oid   = claims.get("oid") or claims.get("sub", "")

    request.session["user"]      = {"name": name, "email": email, "oid": oid}
    request.session["api_token"] = token
    return RedirectResponse(url=next, status_code=303)


@app.get("/auth/callback", response_class=HTMLResponse, response_model=None)
async def auth_callback(
    request: Request,
    error: str = "",
    error_description: str = "",
) -> HTMLResponse | RedirectResponse:
    """Handle the Entra ID authorization code callback."""
    if _auth_config is None:
        return RedirectResponse(url="/dashboard")

    if error:
        return HTMLResponse(
            _layout(
                "Sign-in Error",
                _error_html(f"Entra ID error: {error} — {error_description}"),
            )
        )

    flow = request.session.pop("auth_flow", None)
    if not flow:
        return HTMLResponse(
            _layout(
                "Sign-in Error",
                _error_html(
                    "No active login session found. Please try signing in again."
                ),
            ),
            status_code=400,
        )

    msal_instance = _msal_app()
    # acquire_token_by_auth_code_flow validates state + PKCE verifier automatically.
    result = msal_instance.acquire_token_by_auth_code_flow(
        flow,
        dict(request.query_params),
    )

    if "error" in result:
        return HTMLResponse(
            _layout(
                "Sign-in Error",
                _error_html(
                    f"{result['error']}: {result.get('error_description', '')}"
                ),
            )
        )

    claims = result.get("id_token_claims", {})

    # ── Access control ───────────────────────────────────────────────────────
    required_group = (_auth_config or {}).get("required_group")
    required_role  = (_auth_config or {}).get("required_role")

    if required_group:
        # 'groups' claim contains group object IDs.
        # If the claim is absent the token was issued without group claims —
        # enable it under "Token configuration" on the app registration.
        user_groups: list[str] = claims.get("groups") or []
        if required_group not in user_groups:
            return HTMLResponse(
                _layout(
                    "Access Denied",
                    _error_html(
                        "Your account is not a member of the required group. "
                        "Contact your administrator to request access."
                    ),
                ),
                status_code=403,
            )

    if required_role:
        # 'roles' claim contains app role values assigned to the user.
        # Define app roles on the app registration and assign users/groups
        # under Enterprise applications → Users and groups.
        user_roles: list[str] = claims.get("roles") or []
        if required_role not in user_roles:
            return HTMLResponse(
                _layout(
                    "Access Denied",
                    _error_html(
                        f"Your account does not have the '{required_role}' role. "
                        "Contact your administrator to request access."
                    ),
                ),
                status_code=403,
            )
    # ─────────────────────────────────────────────────────────────────────────

    request.session["user"] = {
        "name":  claims.get("name") or claims.get("preferred_username", "Unknown"),
        "email": claims.get("preferred_username") or claims.get("email", ""),
        "oid":   claims.get("oid", ""),
    }
    # Store the access_token so the UI can authenticate proxy calls to the API.
    # Present only when an api_scope was requested during login.
    if result.get("access_token"):
        request.session["api_token"] = result["access_token"]
    next_url = request.session.pop("auth_next", "/dashboard")
    return RedirectResponse(url=next_url, status_code=302)


@app.get("/auth/logout")
async def auth_logout(request: Request) -> RedirectResponse:
    """Clear the session and redirect to the Entra ID sign-out endpoint."""
    request.session.pop("user", None)
    request.session.pop("api_token", None)
    if _auth_config:
        post_logout = f"http://127.0.0.1:{_port}/dashboard"
        logout_url = (
            f"{_auth_config['authority']}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={post_logout}"
        )
        return RedirectResponse(url=logout_url)
    return RedirectResponse(url="/dashboard")
