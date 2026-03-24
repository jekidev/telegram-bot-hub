"""
Render helper CLI for Valkyrie Cloud.

Why this exists:
- Render UI setup is easy to misconfigure (wrong startCommand, missing env vars).
- This script lets you inspect/update a service via the Render Public API.

Safety:
- Reads your Render API key from the environment (RENDER_API_KEY).
- Never prints secret values (only keys and metadata).
- Does not store secrets in git.

Usage examples (PowerShell):
  $env:RENDER_API_KEY = "<your Render API key>"
  python .\\deploy\\render_tools.py services --name valkyrie-cloud
  python .\\deploy\\render_tools.py set-start-command --service valkyrie-cloud --start "python server.py"
  python .\\deploy\\render_tools.py sync-env --service valkyrie-cloud --env-file .\\.env --keys-from .\\.env.example
  python .\\deploy\\render_tools.py restart --service valkyrie-cloud
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from dotenv import dotenv_values


RENDER_API_BASE = "https://api.render.com/v1"


class RenderError(RuntimeError):
    pass


def _require_api_key() -> str:
    key = (os.environ.get("RENDER_API_KEY") or "").strip()
    if not key:
        raise RenderError(
            "Missing RENDER_API_KEY. Set it in your shell environment (do not commit it)."
        )
    return key


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(
    api_key: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any | None = None,
) -> Any:
    url = f"{RENDER_API_BASE}{path}"
    resp = requests.request(
        method=method.upper(),
        url=url,
        headers=_headers(api_key),
        params=params,
        data=None if body is None else json.dumps(body),
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RenderError(f"{method.upper()} {path} failed: {resp.status_code} {resp.text}")
    if resp.status_code == 204:
        return None
    if not resp.text.strip():
        return None
    return resp.json()


@dataclass(frozen=True)
class ServiceRef:
    id: str
    name: str
    type: str
    repo: str | None
    branch: str | None


def _iter_services(api_key: str, *, name: str | None = None, limit: int = 100) -> Iterable[ServiceRef]:
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": limit}
        if name:
            params["name"] = name
        if cursor:
            params["cursor"] = cursor
        data = _request(api_key, "GET", "/services", params=params)
        if not data:
            return

        # list-services returns: [{ "service": {...}, "cursor": "..." }, ...]
        for item in data:
            svc = item.get("service", {}) if isinstance(item, dict) else {}
            yield ServiceRef(
                id=str(svc.get("id", "")),
                name=str(svc.get("name", "")),
                type=str(svc.get("type", "")),
                repo=svc.get("repo"),
                branch=svc.get("branch"),
            )

        # Use the cursor from the last element if present, otherwise stop.
        last = data[-1] if isinstance(data, list) and data else None
        next_cursor = last.get("cursor") if isinstance(last, dict) else None
        if not next_cursor or next_cursor == cursor:
            return
        cursor = str(next_cursor)


def _resolve_service(api_key: str, ident: str) -> ServiceRef:
    ident = ident.strip()
    if ident.startswith("srv-"):
        svc = _request(api_key, "GET", f"/services/{ident}")
        return ServiceRef(
            id=str(svc.get("id", ident)),
            name=str(svc.get("name", ident)),
            type=str(svc.get("type", "")),
            repo=svc.get("repo"),
            branch=svc.get("branch"),
        )

    matches = [s for s in _iter_services(api_key, name=ident) if s.name == ident]
    if not matches:
        # fallback: scan all services in case name filter is fuzzy on the API side
        matches = [s for s in _iter_services(api_key) if s.name == ident]
    if not matches:
        raise RenderError(f"Service not found by name: {ident}")
    if len(matches) > 1:
        ids = ", ".join(s.id for s in matches)
        raise RenderError(f"Multiple services named '{ident}': {ids}. Use --service srv-... instead.")
    return matches[0]


def _mask_value(value: str) -> str:
    value = value or ""
    if len(value) <= 6:
        return "***"
    return value[:2] + "***" + value[-2:]


def _load_env_file(path: str) -> dict[str, str]:
    values = dotenv_values(path)
    # dotenv_values returns Optional[str] values
    result: dict[str, str] = {}
    for k, v in values.items():
        if not k:
            continue
        if v is None:
            continue
        result[str(k)] = str(v)
    return result


def _load_key_whitelist(path: str) -> set[str]:
    keys = set()
    for k in _load_env_file(path).keys():
        keys.add(k)
    return keys


def cmd_services(args: argparse.Namespace) -> int:
    api_key = _require_api_key()
    services = list(_iter_services(api_key, name=args.name))
    if not services:
        print("No services found.")
        return 0
    for s in services:
        repo = s.repo or "-"
        branch = s.branch or "-"
        print(f"{s.name}\t{s.id}\t{s.type}\t{repo}\t{branch}")
    return 0


def cmd_set_start_command(args: argparse.Namespace) -> int:
    api_key = _require_api_key()
    svc = _resolve_service(api_key, args.service)

    # For native runtime services, patch serviceDetails.envSpecificDetails.startCommand
    payload = {
        "serviceDetails": {
            "envSpecificDetails": {
                "startCommand": args.start,
            }
        }
    }
    _request(api_key, "PATCH", f"/services/{svc.id}", body=payload)
    print(f"Updated startCommand for {svc.name} ({svc.id}).")
    return 0


def cmd_sync_env(args: argparse.Namespace) -> int:
    api_key = _require_api_key()
    svc = _resolve_service(api_key, args.service)

    env_values = _load_env_file(args.env_file)
    if not env_values:
        raise RenderError(f"No values found in env file: {args.env_file}")

    whitelist: set[str] | None = None
    if args.keys_from:
        whitelist = _load_key_whitelist(args.keys_from)

    # Optional allow-list of keys (comma separated) on top of keys_from file.
    if args.only_keys:
        only = {k.strip() for k in args.only_keys.split(",") if k.strip()}
        whitelist = only if whitelist is None else (whitelist & only)

    keys_to_set = sorted(env_values.keys())
    if whitelist is not None:
        keys_to_set = [k for k in keys_to_set if k in whitelist]

    if not keys_to_set:
        print("No env keys selected for sync.")
        return 0

    print(f"Syncing {len(keys_to_set)} env vars to {svc.name} ({svc.id})")
    for key in keys_to_set:
        value = env_values.get(key, "")
        if value == "" and not args.include_empty:
            continue
        if args.dry_run:
            # Never print full secrets.
            print(f"DRY-RUN set {key}={_mask_value(value)}")
            continue

        _request(api_key, "PUT", f"/services/{svc.id}/env-vars/{key}", body={"value": value})
        print(f"Set {key}")

    print("Done.")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    api_key = _require_api_key()
    svc = _resolve_service(api_key, args.service)
    _request(api_key, "POST", f"/services/{svc.id}/restart")
    print(f"Restart triggered for {svc.name} ({svc.id}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render helper CLI for Valkyrie Cloud")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("services", help="List services")
    ps.add_argument("--name", help="Filter by service name", default=None)
    ps.set_defaults(func=cmd_services)

    psc = sub.add_parser("set-start-command", help="Patch a service startCommand")
    psc.add_argument("--service", required=True, help="Service name (exact) or service id (srv-...)")
    psc.add_argument("--start", required=True, help="Start command, e.g. 'python server.py'")
    psc.set_defaults(func=cmd_set_start_command)

    pse = sub.add_parser("sync-env", help="Sync env vars from a local .env file to a service")
    pse.add_argument("--service", required=True, help="Service name (exact) or service id (srv-...)")
    pse.add_argument("--env-file", required=True, help="Path to local env file (e.g. ./.env)")
    pse.add_argument(
        "--keys-from",
        default=None,
        help="Optional env file used as a whitelist of allowed keys (e.g. ./.env.example)",
    )
    pse.add_argument(
        "--only-keys",
        default=None,
        help="Optional comma-separated allow-list of keys to set (intersected with --keys-from if provided)",
    )
    pse.add_argument("--include-empty", action="store_true", help="Also set empty values")
    pse.add_argument("--dry-run", action="store_true", help="Show what would be set without calling Render")
    pse.set_defaults(func=cmd_sync_env)

    pr = sub.add_parser("restart", help="Restart a service")
    pr.add_argument("--service", required=True, help="Service name (exact) or service id (srv-...)")
    pr.set_defaults(func=cmd_restart)

    return p


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RenderError as exc:
        print(f"[render_tools] {exc}", file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        print(f"[render_tools] Network error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

