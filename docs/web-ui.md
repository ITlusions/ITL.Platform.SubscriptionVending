---
layout: default
title: Web Management UI
---

# Web Management UI

The `vending ui` command starts a browser-based management dashboard for ITL Subscription Vending.  
It is built on FastAPI + HTMX + Tailwind CSS and served by Uvicorn on the local machine.

---

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/dashboard` | Health status, queue statistics, recent jobs (auto-refresh every 30 s) |
| Jobs | `/jobs` | Job queue viewer, dead-letter queue, DLQ purge |
| Provision | `/provision` | Run or preflight a subscription provisioning workflow |
| Config | `/config` | Active configuration (secrets redacted) |

---

## Installation

```bash
pip install "itl-subscription-vending[ui]"
```

The `[ui]` extra adds `click`, `uvicorn`, `itsdangerous` (session middleware), and `msal` (Entra ID SSO).

---

## Starting the UI

```bash
# Minimal — no auth
vending ui --remote http://vending-api:8000

# With SSO (recommended)
vending ui --remote http://vending-api:8000 \
           --tenant-id <tid> \
           --client-id <cid>

# Open browser automatically
vending ui --remote http://vending-api:8000 --open
```

All options can be set via environment variables — see [Configuration](#configuration) below.

---

## Authentication

When `--tenant-id` and `--client-id` are configured (or built into the package — see below), the UI requires authentication before granting access.  
When auth is disabled (no tenant/client ID), the UI is openly accessible to anyone who can reach the port.

### Login page

The login page (`/auth/login`) detects credentials automatically and presents the most convenient option first:

#### 1. Azure session auto-detected (green card)

On page load the server checks the following sources **in order**:

| Priority | Source | Set by |
|----------|--------|--------|
| 1 | `ARM_ACCESS_TOKEN` env var | Azure Pipelines, Terraform |
| 2 | `AZURE_ACCESS_TOKEN` env var | Manually exported |
| 3 | `VENDING_TOKEN` env var | `vending --token <t>` or shell export |
| 4 | `az account get-access-token` | User ran `az login` |

If any source returns a valid JWT, a green card appears:

> **Azure session detected**  
> Found a token for **user@example.com** via Azure CLI.  
> [Continue as user@example.com →]

One click — session created, user lands on the dashboard.

#### 2. Sign in with Microsoft

Starts a browser-based PKCE/OAuth 2.0 flow:

1. User clicks "Sign in with Microsoft"
2. Redirected to `login.microsoftonline.com`
3. Signs in with their organisation account (MFA and Conditional Access apply normally)
4. Redirected back to `/auth/callback`
5. Group and/or role membership checked (if `--required-group` / `--required-role` configured)
6. Session and API token stored; user lands on the dashboard

No client secret is required — the PKCE flow (`PublicClientApplication`) is used by default.  
Set `--client-secret` (or `VENDING_UI_ENTRA_CLIENT_SECRET`) to switch to a confidential client flow.

#### 3. Paste a token

For users without a browser redirect flow available. The page shows the exact Azure CLI command to run:

```bash
az account get-access-token --query accessToken -o tsv
```

The user copies the output, pastes it into the text field, and clicks submit.  
The JWT payload is decoded locally to extract the display name — signature verification is enforced by the API on every actual API call.

---

## Entra ID App Registration (one-time, admin)

1. Go to **Azure Portal → Entra ID → App registrations → New registration**
2. Platform: **Web**
3. Add redirect URI: `http://127.0.0.1:8080/auth/callback`  
   (adjust port if `--port` differs)
4. Under **Authentication**, enable **"Allow public client flows"**  
   (required for PKCE without a client secret)
5. Note the **Application (client) ID** and **Directory (tenant) ID** — these are the values for `--client-id` and `--tenant-id`

### Optional: group-based access control

To restrict access to members of a specific Entra ID group:

1. Under **Token configuration**, add a **Groups claim** → select **Security groups** → save
2. Pass the group's **Object ID** as `--required-group` (or `VENDING_UI_ENTRA_REQUIRED_GROUP`)

### Optional: role-based access control

To restrict access using App Roles:

1. Under **App roles**, create a role (e.g. value `VendingUI.Access`)
2. Assign users or groups to the role under **Enterprise applications → [your app] → Users and groups**
3. Pass the role value as `--required-role` (or `VENDING_UI_ENTRA_REQUIRED_ROLE`)

---

## Built-in defaults

To ship SSO pre-configured so users need no flags at all, set the constants at the top of `src/subscription_vending/cli/ui.py`:

```python
_DEFAULT_TENANT_ID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
_DEFAULT_CLIENT_ID = "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"
_DEFAULT_API_SCOPE = None   # set to "api://<api-cid>/.default" only if API auth is on
```

With these set, `vending ui --remote http://...` is all a user needs.  
CLI flags and environment variables always override the built-in defaults.

---

## Configuration

### Environment variables

| Variable | CLI flag | Default | Description |
|----------|----------|---------|-------------|
| `VENDING_API_URL` | `--remote` | *(none)* | Base URL of the running vending API to proxy |
| `VENDING_UI_HOST` | `--host` | `127.0.0.1` | Host to bind the UI server to |
| `VENDING_UI_PORT` | `--port` | `8080` | Port for the web UI |
| `VENDING_UI_ENTRA_TENANT_ID` | `--tenant-id` | *(none)* | Entra ID tenant ID. Enables SSO when set together with client ID |
| `VENDING_UI_ENTRA_CLIENT_ID` | `--client-id` | *(none)* | App registration client ID |
| `VENDING_UI_ENTRA_CLIENT_SECRET` | `--client-secret` | *(none)* | Client secret. Omit to use PKCE (no secret) |
| `VENDING_UI_REDIRECT_URI` | `--redirect-uri` | `http://127.0.0.1:<port>/auth/callback` | OAuth2 redirect URI |
| `VENDING_UI_ENTRA_REQUIRED_GROUP` | `--required-group` | *(none)* | Entra ID group Object ID — only members are granted access |
| `VENDING_UI_ENTRA_REQUIRED_ROLE` | `--required-role` | *(none)* | App role value — only users with this role are granted access |
| `VENDING_UI_ENTRA_API_SCOPE` | `--api-scope` | *(none)* | API scope for access token delegation (needed only when API auth is enabled and users log in via SSO) |

### Token auto-detection env vars

The login page also checks these env vars for a pre-existing token (checked before attempting `az cli`):

| Variable | Typical source |
|----------|---------------|
| `ARM_ACCESS_TOKEN` | Azure Pipelines, Terraform |
| `AZURE_ACCESS_TOKEN` | Manually exported |
| `VENDING_TOKEN` | `vending --token <t>` or `$env:VENDING_TOKEN` |

---

## Auth routes

| Route | Method | Description |
|-------|--------|-------------|
| `/auth/login` | `GET` | Login page (auto-detects existing session, shows all sign-in options) |
| `/auth/az-login` | `GET` | One-click login using detected env var or Azure CLI token |
| `/auth/sso` | `GET` | Starts the Entra ID PKCE browser redirect flow |
| `/auth/callback` | `GET` | OAuth2 callback — validates state, PKCE, group/role, creates session |
| `/auth/token` | `POST` | Accepts a pasted Bearer token, decodes claims, creates session |
| `/auth/logout` | `GET` | Clears the session and redirects to the login page |

---

## API scope (when is it needed?)

`--api-scope` is only required when **both** of these are true:

1. The vending API has `VENDING_API_ENTRA_TENANT_ID` set (API Bearer auth is enabled)
2. Users log in via the **SSO (Microsoft button)** flow — not via token paste or env var detection

In that case, MSAL must request an `access_token` scoped to the API alongside the `id_token` used for the UI session.  
For token-paste and env-var flows, the token supplied already contains the correct audience — no extra scope needed.

---

## Relationship to the API's Bearer auth

When `VENDING_API_ENTRA_TENANT_ID` is set on the API server, every endpoint requires a valid Entra ID Bearer token.  
The UI forwards the stored `api_token` as `Authorization: Bearer <token>` on every proxied request automatically.  
See [API Reference → Authentication](api.md#authentication) for the API-side configuration.
