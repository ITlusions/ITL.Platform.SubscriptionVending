"""vending â€” CLI for ITL Subscription Vending.

Usage â€” local (runs WorkflowEngine in-process)
------
    vending provision  --sub-id <id> --sub-name <name> [--mg-id <mg>] [--dry-run]
    vending preflight  --sub-id <id> --sub-name <name> [--mg-id <mg>]
    vending status

Usage â€” remote (calls a running vending API)
------
    vending provision  --sub-id <id> --sub-name <name> --remote http://my-host:8000
    vending preflight  --sub-id <id> --sub-name <name> --remote http://my-host:8000

Install
-------
    pip install "itl-subscription-vending[cli]"
"""

from __future__ import annotations

import asyncio
import json
import sys

import click
import httpx

from ..core.config import Settings
from .monitor import events, jobs

_REMOTE_ENVVAR = "VENDING_API_URL"


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_settings() -> Settings:
    """Load Settings from env / .env file.  Exits with a clear message on error."""
    try:
        return Settings()
    except Exception as exc:  # pydantic ValidationError or similar
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(2)


def _print_result(result, *, output: str) -> None:
    """Print a ProvisioningResult as JSON or human-readable table."""
    data = {
        "subscription_id": result.subscription_id,
        "management_group": result.management_group,
        "initiative_id": result.initiative_id,
        "rbac_roles": result.rbac_roles,
        "success": result.success,
        "errors": result.errors,
    }

    if output == "json":
        click.echo(json.dumps(data, indent=2))
        return

    # table (default)
    status_label = click.style("SUCCESS", fg="green") if result.success else click.style("FAILED", fg="red")
    click.echo(f"\nResult: {status_label}")
    click.echo(f"  Subscription  : {result.subscription_id}")
    click.echo(f"  Mgmt Group    : {result.management_group or '(not set)'}")
    click.echo(f"  Initiative    : {result.initiative_id or '(none)'}")
    click.echo(f"  RBAC roles    : {len(result.rbac_roles)}")
    if result.errors:
        click.echo("  Errors:")
        for err in result.errors:
            click.echo(f"    - {err}")


def _print_remote_response(resp_data: dict, *, output: str) -> bool:
    """Print a remote API response dict.  Returns True when status is 'ok'."""
    success = resp_data.get("status") == "ok"

    if output == "json":
        click.echo(json.dumps(resp_data, indent=2))
        return success

    status_label = click.style("OK", fg="green") if success else click.style("ERROR", fg="red")
    click.echo(f"\nResult: {status_label}")
    click.echo(f"  Subscription  : {resp_data.get('subscription_id', '?')}")

    plan = resp_data.get("plan", [])
    if plan:
        click.echo("  Plan:")
        for step in plan:
            click.echo(f"    - {step}")

    errors = resp_data.get("errors", [])
    if errors:
        click.echo("  Errors:")
        for err in errors:
            click.echo(f"    - {err}")

    return success


def _remote_replay(
    base_url: str,
    sub_id: str,
    sub_name: str,
    mg_id: str,
    *,
    dry_run: bool,
    secret: str | None,
    output: str,
    verbose: bool = False,
) -> None:
    """POST to /webhook/replay on the remote vending API."""
    url = base_url.rstrip("/") + "/webhook/replay"
    headers = {}
    if secret:
        headers["x-replay-secret"] = secret

    payload = {
        "subscription_id": sub_id,
        "subscription_name": sub_name,
        "management_group_id": mg_id,
        "dry_run": dry_run,
    }

    if verbose:
        click.echo(click.style(f"> POST {url}", fg="blue"), err=True)
    click.echo(f"Calling {url} â€¦")
    import time  # noqa: PLC0415
    t0 = time.monotonic()
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=120)
        elapsed = int((time.monotonic() - t0) * 1000)
        if verbose:
            color = "green" if resp.status_code < 400 else "red"
            click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        click.echo(f"HTTP {exc.response.status_code}: {exc.response.text}", err=True)
        sys.exit(1)
    except httpx.RequestError as exc:
        click.echo(f"Connection error: {exc}", err=True)
        sys.exit(1)

    success = _print_remote_response(resp.json(), output=output)
    sys.exit(0 if success else 1)


def _remote_preflight(
    base_url: str,
    sub_id: str,
    sub_name: str,
    mg_id: str,
    *,
    output: str,
    verbose: bool = False,
) -> None:
    """POST to /webhook/preflight on the remote vending API."""
    url = base_url.rstrip("/") + "/webhook/preflight"
    payload = {
        "subscription_id": sub_id,
        "subscription_name": sub_name,
        "management_group_id": mg_id,
    }

    if verbose:
        click.echo(click.style(f"> POST {url}", fg="blue"), err=True)
    click.echo(f"Calling {url} â€¦")
    import time  # noqa: PLC0415
    t0 = time.monotonic()
    try:
        resp = httpx.post(url, json=payload, timeout=60)
        elapsed = int((time.monotonic() - t0) * 1000)
        if verbose:
            color = "green" if resp.status_code < 400 else "red"
            click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        click.echo(f"HTTP {exc.response.status_code}: {exc.response.text}", err=True)
        sys.exit(1)
    except httpx.RequestError as exc:
        click.echo(f"Connection error: {exc}", err=True)
        sys.exit(1)

    success = _print_remote_response(resp.json(), output=output)
    sys.exit(0 if success else 1)


# â”€â”€ CLI root â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@click.group()
@click.version_option(package_name="itl-subscription-vending", prog_name="vending")
def cli() -> None:
    """ITL Subscription Vending â€” manage Azure subscription provisioning.

    By default commands run in-process (local mode).
    Pass --remote <URL> to target a running vending API instead.
    """


# â”€â”€ provision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@cli.command()
@click.option("--sub-id",   required=True, envvar="VENDING_SUB_ID",   help="Azure subscription ID.")
@click.option("--sub-name", required=True, envvar="VENDING_SUB_NAME", help="Display name of the subscription.")
@click.option("--mg-id",    default="",    envvar="VENDING_MG_ID",    help="Target management group ID (falls back to root MG).")
@click.option("--dry-run",  is_flag=True,  help="Simulate the workflow without making Azure changes.")
@click.option("--remote",   default=None,  envvar=_REMOTE_ENVVAR,     help="Base URL of a running vending API (e.g. https://vending.example.com). Uses POST /webhook/replay.")
@click.option("--secret",   default=None,  envvar="VENDING_REPLAY_SECRET", help="x-replay-secret header value (required when the API has replay_secret set).")
@click.option("-o", "--output", default="table", type=click.Choice(["table", "json"]), help="Output format.")
@click.option("-v", "--verbose", is_flag=True, envvar="VENDING_VERBOSE", help="Show request details (remote mode).")
def provision(sub_id: str, sub_name: str, mg_id: str, dry_run: bool, remote: str | None, secret: str | None, output: str, verbose: bool) -> None:
    """Run the full provisioning workflow for a subscription.

    Local mode:  runs WorkflowEngine in-process (needs Azure credentials in env).
    Remote mode: POSTs to POST /webhook/replay on the target API.
    """
    if remote:
        _remote_replay(remote, sub_id, sub_name, mg_id, dry_run=dry_run, secret=secret, output=output, verbose=verbose)
        return

    from ..workflow import WorkflowEngine  # noqa: PLC0415

    settings = _load_settings()

    if dry_run:
        click.echo(click.style("DRY RUN â€” no Azure changes will be made.", fg="yellow"))

    click.echo(f"Provisioning '{sub_name}' ({sub_id}) â€¦")

    result = asyncio.run(
        WorkflowEngine(settings).run(
            subscription_id=sub_id,
            subscription_name=sub_name,
            management_group_id=mg_id,
            dry_run=dry_run,
        )
    )

    _print_result(result, output=output)
    sys.exit(0 if result.success else 1)


# â”€â”€ preflight â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@cli.command()
@click.option("--sub-id",   required=True, envvar="VENDING_SUB_ID",   help="Azure subscription ID.")
@click.option("--sub-name", required=True, envvar="VENDING_SUB_NAME", help="Display name of the subscription.")
@click.option("--mg-id",    default="",    envvar="VENDING_MG_ID",    help="Target management group ID.")
@click.option("--remote",   default=None,  envvar=_REMOTE_ENVVAR,     help="Base URL of a running vending API. Uses POST /webhook/preflight.")
@click.option("-o", "--output", default="table", type=click.Choice(["table", "json"]), help="Output format.")
@click.option("-v", "--verbose", is_flag=True, envvar="VENDING_VERBOSE", help="Show request details (remote mode).")
def preflight(sub_id: str, sub_name: str, mg_id: str, remote: str | None, output: str, verbose: bool) -> None:
    """Dry-run the workflow â€” validate gates and steps without touching Azure.

    Local mode:  runs WorkflowEngine(dry_run=True) in-process.
    Remote mode: POSTs to POST /webhook/preflight on the target API.
    """
    if remote:
        _remote_preflight(remote, sub_id, sub_name, mg_id, output=output, verbose=verbose)
        return

    from ..workflow import WorkflowEngine  # noqa: PLC0415

    settings = _load_settings()

    click.echo(f"Running preflight for '{sub_name}' ({sub_id}) â€¦")

    result = asyncio.run(
        WorkflowEngine(settings).run(
            subscription_id=sub_id,
            subscription_name=sub_name,
            management_group_id=mg_id,
            dry_run=True,
        )
    )

    _print_result(result, output=output)
    sys.exit(0 if result.success else 1)


# â”€â”€ status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@cli.command()
@click.option("-o", "--output", default="table", type=click.Choice(["table", "json"]), help="Output format.")
def status(output: str) -> None:
    """Show active configuration (env vars / .env file)."""
    settings = _load_settings()

    data = {
        "azure_tenant_id":          settings.azure_tenant_id,
        "azure_client_id":          settings.azure_client_id or "(managed identity)",
        "root_management_group":    settings.root_management_group,
        "retry_strategy":           str(settings.retry_strategy.value),
        "mock_mode":                settings.mock_mode,
        "authorization_service_url": settings.authorization_service_url,
        "event_grid_topic_endpoint": settings.event_grid_topic_endpoint or "(not set)",
        "storage_account_name":     settings.storage_account_name or "(not set)",
    }

    if output == "json":
        click.echo(json.dumps(data, indent=2))
        return

    click.echo("\nActive configuration:")
    for key, val in data.items():
        click.echo(f"  {key:<35} {val}")


# â”€â”€ entry-point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


# â”€â”€ enqueue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@cli.command()
@click.option("--sub-id",   required=True, envvar="VENDING_SUB_ID",   help="Azure subscription ID.")
@click.option("--sub-name", required=True, envvar="VENDING_SUB_NAME", help="Display name of the subscription.")
@click.option("--mg-id",    default="",    envvar="VENDING_MG_ID",    help="Target management group ID.")
@click.option("--job-id",   default="",    help="Explicit job ID (UUID).  Auto-generated when omitted.")
@click.option("--remote",   default=None,  envvar=_REMOTE_ENVVAR,     help="Base URL of a running vending API.  Uses POST /jobs/enqueue.")
@click.option("-v", "--verbose", is_flag=True, envvar="VENDING_VERBOSE", help="Show request details (remote mode).")
def enqueue(sub_id: str, sub_name: str, mg_id: str, job_id: str, remote: str | None, verbose: bool) -> None:
    """Push a job directly onto the provisioning queue.

    Remote mode: POST /jobs/enqueue on the vending API.
    Local mode:  connects to Azure Storage Queue directly.

    Unlike 'provision', this does not run the workflow immediately â€” the
    worker picks it up asynchronously (requires retry_strategy=queue).
    """
    payload = {
        "job_id": job_id,
        "subscription_id": sub_id,
        "subscription_name": sub_name,
        "management_group_id": mg_id,
    }

    if remote:
        import time  # noqa: PLC0415
        url = remote.rstrip("/") + "/jobs/enqueue"
        if verbose:
            click.echo(click.style(f"> POST {url}", fg="blue"), err=True)
        t0 = time.monotonic()
        try:
            resp = httpx.post(url, json=payload, timeout=30)
            elapsed = int((time.monotonic() - t0) * 1000)
            if verbose:
                color = "green" if resp.status_code < 400 else "red"
                click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            click.echo(f"HTTP {exc.response.status_code}: {exc.response.text}", err=True)
            sys.exit(1)
        except httpx.RequestError as exc:
            click.echo(f"Connection error: {exc}", err=True)
            sys.exit(1)
        data = resp.json()
        click.echo(f"Enqueued  job_id={data['job_id']}  queue={data['queue']}")
        return

    settings = _load_settings()
    try:
        import base64  # noqa: PLC0415
        import uuid    # noqa: PLC0415
        from ..infrastructure.queue import get_queue_client  # noqa: PLC0415 â€” best-effort
    except ImportError:
        click.echo(
            "Local enqueue requires azure-storage-queue.\n"
            "Use --remote to target the vending API, or 'pip install azure-storage-queue'.",
            err=True,
        )
        sys.exit(2)

    final_job_id = job_id or str(uuid.uuid4())
    payload["job_id"]  = final_job_id
    payload["attempt"] = 1
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    client  = get_queue_client(settings, settings.provisioning_queue_name)
    result  = client.send_message(encoded)
    click.echo(f"Enqueued  job_id={final_job_id}  message_id={result.id}  queue={settings.provisioning_queue_name}")


# â”€â”€ config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@cli.group()
def config() -> None:
    """Show and validate the vending configuration."""


@config.command("show")
@click.option("--remote", default=None, envvar=_REMOTE_ENVVAR,
              help="Base URL of a running vending API.  Returns GET /config (secrets redacted).")
@click.option("-o", "--output", default="table", type=click.Choice(["table", "json"]), help="Output format.")
@click.option("-v", "--verbose", is_flag=True, envvar="VENDING_VERBOSE", help="Show request details.")
def config_show(remote: str | None, output: str, verbose: bool) -> None:
    """Show active configuration.

    Remote mode: GET /config on the vending API (secrets are redacted server-side).
    Local mode:  reads Settings from environment / .env file.
    """
    if remote:
        import time  # noqa: PLC0415
        url = remote.rstrip("/") + "/config"
        if verbose:
            click.echo(click.style(f"> GET {url}", fg="blue"), err=True)
        t0 = time.monotonic()
        try:
            resp = httpx.get(url, timeout=15)
            elapsed = int((time.monotonic() - t0) * 1000)
            if verbose:
                color = "green" if resp.status_code < 400 else "red"
                click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            click.echo(f"HTTP {exc.response.status_code}: {exc.response.text}", err=True)
            sys.exit(1)
        except httpx.RequestError as exc:
            click.echo(f"Connection error: {exc}", err=True)
            sys.exit(1)
        data = resp.json()
        if output == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            click.echo(f"\nConfiguration from {remote}:")
            for k, v in data.items():
                click.echo(f"  {k:<35} {v}")
        return

    settings = _load_settings()
    data = {
        "azure_tenant_id":           settings.azure_tenant_id,
        "azure_client_id":           settings.azure_client_id or "(managed identity)",
        "root_management_group":     settings.root_management_group,
        "retry_strategy":            str(settings.retry_strategy.value),
        "mock_mode":                 settings.mock_mode,
        "authorization_service_url": settings.authorization_service_url,
        "event_grid_topic_endpoint": settings.event_grid_topic_endpoint or "(not set)",
        "storage_account_name":      settings.storage_account_name or "(not set)",
    }
    if output == "json":
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo("\nActive configuration:")
        for key, val in data.items():
            click.echo(f"  {key:<35} {val}")


@config.command("validate")
@click.option("--remote", default=None, envvar=_REMOTE_ENVVAR,
              help="Base URL of a running vending API.  Checks /health and /config.")
@click.option("-v", "--verbose", is_flag=True, envvar="VENDING_VERBOSE", help="Show request details.")
def config_validate(remote: str | None, verbose: bool) -> None:
    """Validate the vending configuration.

    Remote mode: checks GET /health and GET /config on the running API.
    Local mode:  boots Settings() from environment and validates required fields.
    """
    if remote:
        import time  # noqa: PLC0415
        errors: list[str] = []

        for path, label in [("/health", "health"), ("/config", "config")]:
            url = remote.rstrip("/") + path
            if verbose:
                click.echo(click.style(f"> GET {url}", fg="blue"), err=True)
            t0 = time.monotonic()
            try:
                resp = httpx.get(url, timeout=15)
                elapsed = int((time.monotonic() - t0) * 1000)
                if verbose:
                    color = "green" if resp.status_code < 400 else "red"
                    click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
                resp.raise_for_status()
                data = resp.json()
                if label == "health" and data.get("status") != "ok":
                    errors.append(f"/health returned status='{data.get('status')}'")
                else:
                    click.echo(click.style(f"  {label:<10} OK", fg="green"))
            except httpx.RequestError as exc:
                errors.append(f"{path} unreachable: {exc}")
            except httpx.HTTPStatusError as exc:
                errors.append(f"{path} HTTP {exc.response.status_code}")

        if errors:
            for err in errors:
                click.echo(click.style(f"  FAIL  {err}", fg="red"))
            sys.exit(1)
        click.echo(click.style("\nConfiguration valid.", fg="green"))
        return

    # Local validation
    errors = []
    try:
        settings = Settings()  # re-instantiate to catch validation errors
    except Exception as exc:  # pydantic ValidationError
        click.echo(click.style(f"Settings load failed: {exc}", fg="red"))
        sys.exit(1)

    required_checks = [
        ("azure_tenant_id",          settings.azure_tenant_id,          "VENDING_AZURE_TENANT_ID"),
        ("authorization_service_url", settings.authorization_service_url, "VENDING_AUTHORIZATION_SERVICE_URL"),
    ]
    for label, value, envvar in required_checks:
        if not value:
            errors.append(f"{label} is not set (env: {envvar})")
            click.echo(click.style(f"  FAIL  {label}", fg="red"))
        else:
            click.echo(click.style(f"  OK    {label}", fg="green"))

    if settings.retry_strategy.value == "queue" and not settings.storage_account_name:
        errors.append("storage_account_name required when retry_strategy=queue")
        click.echo(click.style("  FAIL  storage_account_name (required for queue strategy)", fg="red"))

    if settings.event_grid_topic_endpoint:
        click.echo(click.style("  OK    event_grid_topic_endpoint", fg="green"))
    else:
        click.echo(click.style("  WARN  event_grid_topic_endpoint not set (outbound events disabled)", fg="yellow"))

    if errors:
        click.echo(click.style(f"\n{len(errors)} validation error(s).", fg="red"))
        sys.exit(1)
    click.echo(click.style("\nConfiguration valid.", fg="green"))
def main() -> None:
    cli()


cli.add_command(jobs)
cli.add_command(events)
