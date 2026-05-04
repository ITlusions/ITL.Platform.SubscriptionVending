"""vending jobs / vending events — monitor running jobs and Azure resources.

Commands
--------
    vending jobs list    Peek pending messages in the provisioning queue.
    vending jobs dlq     Peek messages in the dead-letter queue (failed jobs).
    vending jobs stats   Show approximate message count for both queues.
    vending jobs watch   Poll the provisioning queue and print new messages as they arrive.
    vending events test  Test connectivity to the configured Event Grid topic endpoint.

Remote mode (--remote / VENDING_API_URL)
-----------------------------------------
When --remote is supplied the commands call the vending API instead of
connecting to Azure Storage directly:
    jobs stats  →  GET  /jobs/stats
    jobs list   →  GET  /jobs/list?count=N
    jobs dlq    →  GET  /jobs/dlq?count=N
    jobs watch  →  polls GET /jobs/list every N seconds via the API
    events test →  GET  /health  (basic reachability check)

Local mode (no --remote)
-------------------------
Commands connect directly to the Azure Storage Queue using the account name
or connection string provided.  Requires azure-storage-queue + credentials.
"""

from __future__ import annotations

import base64
import json
import time

import click
import httpx

_REMOTE_ENVVAR = "VENDING_API_URL"

# ── shared options ─────────────────────────────────────────────────────────────

_REMOTE_OPT   = click.option("--remote",   default=None, envvar=_REMOTE_ENVVAR, help="Base URL of a running vending API.  When set, queries the API instead of Azure directly.")
_ACCOUNT_OPT  = click.option("--account",  default=None, envvar="VENDING_STORAGE_ACCOUNT_NAME", help="Azure Storage account name (local mode only).")
_CONN_OPT     = click.option("--conn-str", default=None, envvar="VENDING_STORAGE_CONNECTION_STRING", help="Azure Storage connection string (local mode only).")
_OUTPUT_OPT   = click.option("-o", "--output", default="table", type=click.Choice(["table", "json"]), help="Output format.")
_VERBOSE_OPT  = click.option("-v", "--verbose", is_flag=True, envvar="VENDING_VERBOSE", help="Show request URL, status code, and elapsed time on stderr.")


def _queue_client(account: str | None, queue_name: str, conn_str: str | None):
    """Return a QueueClient, preferring connection string, then DefaultAzureCredential."""
    try:
        from azure.storage.queue import QueueClient  # noqa: PLC0415
    except ImportError:
        raise click.ClickException(
            "azure-storage-queue is not installed.  Run: pip install azure-storage-queue"
        )

    if conn_str:
        return QueueClient.from_connection_string(conn_str, queue_name)

    if not account:
        raise click.ClickException(
            "No storage account specified.  "
            "Set --account / VENDING_STORAGE_ACCOUNT_NAME or provide --conn-str."
        )

    try:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    except ImportError:
        raise click.ClickException(
            "azure-identity is not installed.  Run: pip install azure-identity"
        )

    return QueueClient(
        account_url=f"https://{account}.queue.core.windows.net",
        queue_name=queue_name,
        credential=DefaultAzureCredential(),
    )


def _decode_message(raw_content: str) -> dict:
    """Base64-decode and JSON-parse a queue message body."""
    try:
        decoded = base64.b64decode(raw_content).decode()
        return json.loads(decoded)
    except Exception:  # noqa: BLE001
        return {"raw": raw_content}


def _queue_names(settings_queue: str, settings_dlq: str) -> tuple[str, str]:
    """Return (queue_name, dlq_name) from settings (imported lazily to avoid heavy init)."""
    try:
        from ..core.config import get_settings  # noqa: PLC0415
        s = get_settings()
        return s.provisioning_queue_name, s.provisioning_dlq_name
    except Exception:  # noqa: BLE001
        return settings_queue, settings_dlq


# ── remote helpers ────────────────────────────────────────────────────────────

def _api_get(base_url: str, path: str, *, verbose: bool = False, **params) -> dict:
    """GET from the vending API, return parsed JSON.  Exits on error."""
    url = base_url.rstrip("/") + path
    if verbose:
        qs = "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        click.echo(click.style(f"> GET {url}{'?' + qs if qs else ''}", fg="blue"), err=True)
    t0 = time.monotonic()
    try:
        resp = httpx.get(url, params=params or None, timeout=30)
        elapsed = int((time.monotonic() - t0) * 1000)
        if verbose:
            color = "green" if resp.status_code < 400 else "red"
            click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        raise click.ClickException(f"Connection error: {exc}") from exc


def _api_delete(base_url: str, path: str, *, verbose: bool = False) -> dict:
    """DELETE on the vending API, return parsed JSON.  Exits on error."""
    url = base_url.rstrip("/") + path
    if verbose:
        click.echo(click.style(f"> DELETE {url}", fg="blue"), err=True)
    t0 = time.monotonic()
    try:
        resp = httpx.delete(url, timeout=30)
        elapsed = int((time.monotonic() - t0) * 1000)
        if verbose:
            color = "green" if resp.status_code < 400 else "red"
            click.echo(click.style(f"< HTTP {resp.status_code}  {elapsed}ms", fg=color), err=True)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
    except httpx.RequestError as exc:
        raise click.ClickException(f"Connection error: {exc}") from exc


def _print_jobs_table(data: dict, label: str) -> None:
    msgs = data.get("messages", [])
    queue = data.get("queue", "?")
    if not msgs:
        click.echo(f"{label} queue '{queue}' is empty.")
        return
    click.echo(f"\n{'JOB ID':<38}  {'SUB ID':<38}  {'ATTEMPT':<8}  NAME")
    click.echo("─" * 110)
    for row in msgs:
        click.echo(
            f"{row.get('job_id', '?'):<38}  "
            f"{row.get('subscription_id', '?'):<38}  "
            f"{str(row.get('attempt', '?')):<8}  "
            f"{row.get('subscription_name', '?')}"
        )
    click.echo(f"\n{len(msgs)} message(s) peeked from '{queue}'.")


# ── jobs group ─────────────────────────────────────────────────────────────────

@click.group()
def jobs() -> None:
    """Inspect and monitor provisioning queue jobs."""


# ── jobs list ─────────────────────────────────────────────────────────────────

@jobs.command("list")
@_REMOTE_OPT
@_ACCOUNT_OPT
@_CONN_OPT
@click.option("--queue", default=None, envvar="VENDING_QUEUE_NAME", help="Queue name (local mode).  Defaults to provisioning-jobs.")
@click.option("--count", default=10, show_default=True, help="Number of messages to peek (max 32).")
@_OUTPUT_OPT
@_VERBOSE_OPT
def jobs_list(remote, account, conn_str, queue, count, output, verbose) -> None:
    """Peek pending messages in the provisioning queue (non-destructive).

    Remote mode: GET /jobs/list on the vending API.
    Local mode:  connect directly to Azure Storage Queue.
    """
    if remote:
        data = _api_get(remote, "/jobs/list", verbose=verbose, count=count)
        if output == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            _print_jobs_table(data, "Provisioning")
        return

    q_name, _ = _queue_names("provisioning-jobs", "provisioning-jobs-deadletter")
    queue = queue or q_name
    client = _queue_client(account, queue, conn_str)

    try:
        msgs = list(client.peek_messages(max_messages=min(count, 32)))
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Failed to peek queue '{queue}': {exc}") from exc

    rows = [_decode_message(m.content) for m in msgs]
    if output == "json":
        click.echo(json.dumps(rows, indent=2))
    else:
        _print_jobs_table({"queue": queue, "messages": rows}, "Provisioning")


# ── jobs dlq ──────────────────────────────────────────────────────────────────

@jobs.command("dlq")
@_REMOTE_OPT
@_ACCOUNT_OPT
@_CONN_OPT
@click.option("--queue", default=None, envvar="VENDING_DLQ_NAME", help="Dead-letter queue name (local mode).")
@click.option("--count", default=10, show_default=True, help="Number of messages to peek (max 32).")
@_OUTPUT_OPT
@_VERBOSE_OPT
def jobs_dlq(remote, account, conn_str, queue, count, output, verbose) -> None:
    """Peek failed jobs in the dead-letter queue (non-destructive).

    Remote mode: GET /jobs/dlq on the vending API.
    Local mode:  connect directly to Azure Storage Queue.
    """
    if remote:
        data = _api_get(remote, "/jobs/dlq", verbose=verbose, count=count)
        if output == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            n = data.get("count", 0)
            if n == 0:
                click.echo(click.style("DLQ is empty — no failed jobs.", fg="green"))
            else:
                click.echo(click.style(f"\n{n} failed job(s):", fg="red"))
                _print_jobs_table(data, "DLQ")
        return

    _, dlq_name = _queue_names("provisioning-jobs", "provisioning-jobs-deadletter")
    queue = queue or dlq_name
    client = _queue_client(account, queue, conn_str)

    try:
        msgs = list(client.peek_messages(max_messages=min(count, 32)))
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Failed to peek DLQ '{queue}': {exc}") from exc

    rows = [_decode_message(m.content) for m in msgs]
    if output == "json":
        click.echo(json.dumps(rows, indent=2))
    elif not rows:
        click.echo(click.style(f"DLQ '{queue}' is empty — no failed jobs.", fg="green"))
    else:
        click.echo(click.style(f"\n{len(rows)} failed job(s) in DLQ '{queue}':", fg="red"))
        _print_jobs_table({"queue": queue, "messages": rows}, "DLQ")


# ── jobs stats ────────────────────────────────────────────────────────────────

@jobs.command("stats")
@_REMOTE_OPT
@_ACCOUNT_OPT
@_CONN_OPT
@_OUTPUT_OPT
@_VERBOSE_OPT
def jobs_stats(remote, account, conn_str, output, verbose) -> None:
    """Show approximate message counts for both queues.

    Remote mode: GET /jobs/stats on the vending API.
    Local mode:  connect directly to Azure Storage Queue.
    """
    if remote:
        data = _api_get(remote, "/jobs/stats", verbose=verbose)
        if output == "json":
            click.echo(json.dumps(data, indent=2))
            return
        click.echo("\nQueue stats (approximate counts):")
        for label in ("provisioning", "dead_letter"):
            info  = data.get(label, {})
            count = info.get("approximate_message_count")
            err   = info.get("error")
            color = "red" if err or (label == "dead_letter" and count) else "green"
            val   = click.style(str(count) if count is not None else f"ERROR: {err}", fg=color)
            click.echo(f"  {label:<15} {info.get('queue', '?'):<45} {val}")
        return

    q_name, dlq_name = _queue_names("provisioning-jobs", "provisioning-jobs-deadletter")
    results = {}
    for label, name in [("provisioning", q_name), ("dead_letter", dlq_name)]:
        client = _queue_client(account, name, conn_str)
        try:
            props = client.get_queue_properties()
            results[label] = {"queue": name, "approximate_message_count": props.approximate_message_count}
        except Exception as exc:  # noqa: BLE001
            results[label] = {"queue": name, "error": str(exc)}

    if output == "json":
        click.echo(json.dumps(results, indent=2))
        return

    click.echo("\nQueue stats (approximate counts):")
    for label, info in results.items():
        count = info.get("approximate_message_count")
        err   = info.get("error")
        color = "red" if err or (count and count > 0 and label == "dead_letter") else "green"
        val   = click.style(str(count) if count is not None else f"ERROR: {err}", fg=color)
        click.echo(f"  {label:<15} {info['queue']:<45} {val}")


# ── jobs watch ────────────────────────────────────────────────────────────────

@jobs.command("watch")
@_REMOTE_OPT
@_ACCOUNT_OPT
@_CONN_OPT
@click.option("--queue", default=None, envvar="VENDING_QUEUE_NAME", help="Queue name (local mode).")
@click.option("--interval", default=5, show_default=True, help="Poll interval in seconds.")
@_VERBOSE_OPT
def jobs_watch(remote, account, conn_str, queue, interval, verbose) -> None:
    """Poll the provisioning queue and print new messages as they arrive.

    Runs until interrupted with Ctrl+C.  Messages are peeked (not consumed).
    Remote mode: polls GET /jobs/list on the vending API.
    Local mode:  polls Azure Storage Queue directly.
    """
    seen: set[str] = set()

    if remote:
        click.echo(f"Watching via API {remote} (poll every {interval}s) — Ctrl+C to stop …\n")
        try:
            while True:
                try:
                    data = _api_get(remote, "/jobs/list", verbose=verbose, count=32)
                    for row in data.get("messages", []):
                        key = row.get("job_id") or row.get("subscription_id", "?")
                        if key not in seen:
                            seen.add(key)
                            ts = click.style(time.strftime("%H:%M:%S"), fg="cyan")
                            click.echo(
                                f"[{ts}] job={row.get('job_id', '?')}  "
                                f"sub={row.get('subscription_id', '?')}  "
                                f"attempt={row.get('attempt', '?')}  "
                                f"name={row.get('subscription_name', '')}"
                            )
                except click.ClickException as exc:
                    click.echo(click.style(f"[error] {exc.format_message()}", fg="red"), err=True)
                time.sleep(interval)
        except KeyboardInterrupt:
            click.echo("\nStopped.")
        return

    q_name, _ = _queue_names("provisioning-jobs", "provisioning-jobs-deadletter")
    queue = queue or q_name
    client = _queue_client(account, queue, conn_str)

    click.echo(f"Watching '{queue}' (poll every {interval}s) — Ctrl+C to stop …\n")
    try:
        while True:
            try:
                msgs = list(client.peek_messages(max_messages=32))
            except Exception as exc:  # noqa: BLE001
                click.echo(click.style(f"[error] {exc}", fg="red"), err=True)
                time.sleep(interval)
                continue

            for m in msgs:
                if m.id not in seen:
                    seen.add(m.id)
                    row = _decode_message(m.content)
                    ts  = click.style(time.strftime("%H:%M:%S"), fg="cyan")
                    click.echo(
                        f"[{ts}] job={row.get('job_id', '?')}  "
                        f"sub={row.get('subscription_id', '?')}  "
                        f"attempt={row.get('attempt', '?')}  "
                        f"name={row.get('subscription_name', '')}"
                    )
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nStopped.")


# ── events group ──────────────────────────────────────────────────────────────

@click.group()
def events() -> None:
    """Inspect and test Event Grid configuration."""


@events.command("test")
@_REMOTE_OPT
@click.option("--endpoint", default=None, envvar="VENDING_EVENT_GRID_TOPIC_ENDPOINT",
              help="Event Grid topic endpoint (local mode).  Falls back to VENDING_EVENT_GRID_TOPIC_ENDPOINT.")
@click.option("--key",      default=None, envvar="VENDING_EVENT_GRID_SAS_KEY",
              help="SAS key (local mode).  Falls back to VENDING_EVENT_GRID_SAS_KEY.")
@_VERBOSE_OPT
def events_test(remote: str | None, endpoint: str | None, key: str | None, verbose: bool) -> None:
    """Test connectivity to the Event Grid topic endpoint.

    Remote mode: GET /health on the vending API (confirms the API is up).
    Local mode:  HTTP OPTIONS to the Event Grid topic endpoint directly.
    """
    if remote:
        data = _api_get(remote, "/health", verbose=verbose)
        click.echo(f"Testing vending API: {remote.rstrip('/')}/health")
        status = data.get("status", "?")
        color  = "green" if status == "ok" else "yellow"
        click.echo(click.style(f"API status: {status}", fg=color))
        return

    if not endpoint:
        try:
            from ..core.config import get_settings  # noqa: PLC0415
            s = get_settings()
            endpoint = s.event_grid_topic_endpoint
            key = key or s.event_grid_sas_key
        except Exception:  # noqa: BLE001
            pass

    if not endpoint:
        raise click.ClickException(
            "No Event Grid endpoint specified.  "
            "Set --endpoint, VENDING_EVENT_GRID_TOPIC_ENDPOINT, or use --remote."
        )

    click.echo(f"Testing Event Grid endpoint: {endpoint}")
    headers = {"aeg-sas-key": key} if key else {}

    try:
        resp = httpx.options(endpoint, headers=headers, timeout=10)
    except httpx.RequestError as exc:
        raise click.ClickException(f"Connection failed: {exc}") from exc

    if resp.status_code < 500:
        click.echo(click.style(f"Reachable  (HTTP {resp.status_code})", fg="green"))
        if not key:
            click.echo(click.style("Warning: no SAS key provided — actual publishing may fail.", fg="yellow"))
    else:
        click.echo(click.style(f"Endpoint returned HTTP {resp.status_code} — check configuration.", fg="red"))
        raise SystemExit(1)


# ── jobs purge ────────────────────────────────────────────────────────────────

@jobs.command("purge")
@_REMOTE_OPT
@_ACCOUNT_OPT
@_CONN_OPT
@_VERBOSE_OPT
@click.confirmation_option(prompt="This will permanently delete ALL messages in the DLQ.  Continue?")
def jobs_purge(remote, account, conn_str, verbose) -> None:
    """Delete all messages from the dead-letter queue.

    Remote mode: DELETE /jobs/dlq on the vending API.
    Local mode:  calls clear_messages() on the Azure Storage Queue directly.

    WARNING: this is non-reversible.
    """
    if remote:
        data = _api_delete(remote, "/jobs/dlq", verbose=verbose)
        deleted = data.get("deleted")
        queue   = data.get("queue", "DLQ")
        msg = f"Purged '{queue}'"
        if deleted is not None:
            msg += f" (~{deleted} messages removed)"
        click.echo(click.style(msg, fg="green"))
        return

    _, dlq_name = _queue_names("provisioning-jobs", "provisioning-jobs-deadletter")
    client = _queue_client(account, dlq_name, conn_str)
    try:
        props  = client.get_queue_properties()
        approx = props.approximate_message_count
    except Exception:  # noqa: BLE001
        approx = None
    client.clear_messages()
    msg = f"Purged '{dlq_name}'"
    if approx is not None:
        msg += f" (~{approx} messages removed)"
    click.echo(click.style(msg, fg="green"))


# ── jobs get ──────────────────────────────────────────────────────────────────

@jobs.command("get")
@click.argument("job_id")
@_REMOTE_OPT
@_ACCOUNT_OPT
@_CONN_OPT
@_OUTPUT_OPT
@_VERBOSE_OPT
def jobs_get(job_id: str, remote, account, conn_str, output, verbose) -> None:
    """Look up a specific job by ID (peeks both queues).

    Remote mode: GET /jobs/<job_id> on the vending API.
    Local mode:  peeks provisioning queue then DLQ directly.
    """
    if remote:
        data = _api_get(remote, f"/jobs/{job_id}", verbose=verbose)
        if output == "json":
            click.echo(json.dumps(data, indent=2))
            return
        if not data.get("found"):
            click.echo(click.style(f"Job '{job_id}' not found in any queue.", fg="yellow"))
            return
        job   = data.get("job", {})
        queue = data.get("queue", "?")
        click.echo(f"\nFound in queue: {queue}")
        for k, v in job.items():
            click.echo(f"  {k:<25} {v}")
        return

    # local — peek both queues manually
    q_name, dlq_name = _queue_names("provisioning-jobs", "provisioning-jobs-deadletter")
    for queue_name in (q_name, dlq_name):
        try:
            client = _queue_client(account, queue_name, conn_str)
            msgs = list(client.peek_messages(max_messages=32))
        except Exception as exc:  # noqa: BLE001
            click.echo(click.style(f"[warn] Could not peek '{queue_name}': {exc}", fg="yellow"), err=True)
            continue
        for m in msgs:
            row = _decode_message(m.content)
            if row.get("job_id") == job_id:
                if output == "json":
                    click.echo(json.dumps({"found": True, "queue": queue_name, "job": row}, indent=2))
                else:
                    click.echo(f"\nFound in queue: {queue_name}")
                    for k, v in row.items():
                        click.echo(f"  {k:<25} {v}")
                return

    if output == "json":
        click.echo(json.dumps({"found": False}, indent=2))
    else:
        click.echo(click.style(f"Job '{job_id}' not found in any queue.", fg="yellow"))
