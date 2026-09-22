"""Preflight check, validate config and connectivity BEFORE running the migration.

Run:  python preflight.py [config.json]

Checks, in order:
  1. Config file parses; required keys present, no placeholder values, project
     selection unambiguous, status/priority overrides use real Qase slugs
  2. Zephyr Scale API auth works (GET /projects) and every projects.import key
     exists on the tenant
  3. Per-project data sanity: test case / cycle / execution counts (a zeroed
     project usually means the wrong project key, not an API problem)
  4. Jira credentials, if set, are complete (optional, attachments only)
  5. Qase API auth works (GET /v1/project) and users.default resolves

Exit code 0 = all green; 1 = at least one failure.
"""

import json
import os
import sys

import requests

from src.support.config_manager import ConfigManager, ConfigError
from src.support.logger import Logger
from src.api.zephyr_scale import ZephyrScaleApiClient
from src.exceptions.api import APIError

# Python 3.11 minimum. asyncio.TaskGroup is used by the
# entity importers and does not exist before 3.11; 3.10 reaches end of life in
# October 2026. Fail here rather than partway into a run.
if sys.version_info < (3, 11):
    sys.exit(
        f"This migration requires Python 3.11 or newer "
        f"(found {sys.version_info.major}.{sys.version_info.minor})."
    )


_PLACEHOLDER_MARKERS = ("<", ">", "your-", "YOUR_", "changeme", "xxxx")

# Qase slugs the mapping code can actually emit
_VALID_PRIORITY = {"critical", "high", "normal", "low"}
_VALID_CASE_STATUS = {"actual", "draft", "deprecated"}
_VALID_RESULT_STATUS = {
    "passed", "failed", "blocked", "skipped", "in_progress", "untested", "invalid",
}

_results = []


def _report(name: str, ok: bool, detail: str = ""):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}" + (f": {detail}" if detail else ""))
    _results.append(ok)


def _warn(name: str, detail: str = ""):
    print(f"  ⚠️  {name}" + (f": {detail}" if detail else ""))


def _looks_placeholder(value: str) -> bool:
    return any(marker in value for marker in _PLACEHOLDER_MARKERS)


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "./config.json"

    print("\n- Config -")
    config = ConfigManager(config_file=config_path)
    try:
        config.load_config()
    except ConfigError as e:
        _report(f"Config file {config_path}", False, str(e))
        return _finish()
    _report(f"Config file {config_path}", True, "parses OK")

    required = {
        "qase.api_token": "Qase API token",
        "zephyr.api_token": "Zephyr Scale API token (Jira → Apps → Zephyr Scale → API Access Tokens)",
    }
    config_ok = True
    for key, label in required.items():
        value = str(config.get(key) or "").strip()
        if not value:
            _report(f"{key} ({label})", False, "missing/empty")
            config_ok = False
        elif _looks_placeholder(value):
            _report(f"{key} ({label})", False, f"looks like a placeholder: {value[:40]!r}")
            config_ok = False
        else:
            _report(f"{key} ({label})", True)

    import_all = bool(config.get("projects.import_all"))
    projects = [str(p).strip() for p in (config.get("projects.import") or []) if str(p).strip()]
    exclude = [str(p).strip() for p in (config.get("projects.exclude") or []) if str(p).strip()]
    projects = [p for p in projects if not _looks_placeholder(p)]

    if import_all:
        _report(
            "projects.import_all", True,
            "every Zephyr Scale project on the tenant"
            + (f", excluding {exclude}" if exclude else ""),
        )
    elif not projects:
        _report(
            "projects.import", False,
            "empty, list the Jira project keys to migrate (or set projects.import_all: true)",
        )
        config_ok = False
    else:
        overlap = sorted(set(projects) & set(exclude))
        if overlap:
            _report(
                "projects.import", False,
                f"{overlap} appear in BOTH projects.import and projects.exclude, "
                f"remove them from one side",
            )
            config_ok = False
        else:
            _report("projects.import", True, f"{len(projects)} project key(s): {projects}")

    for cfg_key, valid, label in (
        ("cases.priority_map", _VALID_PRIORITY, "Qase priority"),
        ("cases.status_map", _VALID_CASE_STATUS, "Qase case status"),
        ("runs.status_map", _VALID_RESULT_STATUS, "Qase result status"),
    ):
        mapping = config.get(cfg_key) or {}
        bad = {k: v for k, v in mapping.items() if str(v).strip().lower() not in valid}
        if bad:
            _report(cfg_key, False, f"invalid {label} slug(s): {bad}, valid: {sorted(valid)}")
            config_ok = False
        elif mapping:
            _report(cfg_key, True, f"{len(mapping)} override(s)")

    created_after = config.get("runs.created_after")
    if created_after and not str(created_after).isdigit():
        _report("runs.created_after", False, f"must be epoch seconds, got {created_after!r}")
        config_ok = False

    level = str(config.get("logging.level") or "info").strip().lower()
    if level not in Logger.LEVELS and level not in Logger._ALIASES:
        _warn(
            f"logging.level {level!r} is not recognised",
            f"falling back to 'info'; valid: {sorted(Logger.LEVELS)}",
        )

    if not config_ok:
        return _finish()

    logger = Logger(level="error", write_to_file=False)

    # ---------------- Zephyr Scale ----------------
    print("\n- Zephyr Scale -")
    client = ZephyrScaleApiClient(
        token=str(config.get("zephyr.api_token")),
        logger=logger,
        base_url=str(config.get("zephyr.base_url") or "") or None,
        max_retries=1,
    )
    try:
        tenant_projects = {p.get("key"): p for p in client.get_projects()}
        _report(
            "GET /projects", True,
            f"{len(tenant_projects)} Zephyr Scale project(s): {sorted(k for k in tenant_projects if k)}",
        )
    except (APIError, requests.exceptions.RequestException) as e:
        _report("GET /projects", False, f"{client.base_url} → {str(e)[:200]}")
        _warn(
            "Hint",
            "401 here usually means the token was revoked or belongs to a different "
            "Jira site; regenerate it in Jira → Apps → Zephyr Scale → API Access Tokens",
        )
        return _finish()

    unknown_excludes = sorted(set(exclude) - set(tenant_projects))
    if unknown_excludes:
        _warn(
            f"projects.exclude key(s) not on the tenant: {unknown_excludes}",
            "harmless, but check for typos",
        )

    if import_all:
        projects = [k for k in sorted(tenant_projects) if k and k not in exclude]
        if not projects:
            _report(
                "Resolved project list", False,
                "projects.import_all resolved to zero projects "
                + (f"(everything excluded: {exclude})" if exclude else
                   "(no Zephyr Scale projects on this tenant)"),
            )
            return _finish()
        _report("Resolved project list", True, f"{len(projects)} project(s): {projects}")
    else:
        projects = [k for k in projects if k not in exclude]

    for key in projects:
        if key not in tenant_projects:
            _report(f"Project {key}", False, "not found / not Zephyr Scale-enabled on this tenant")
            continue
        counts = {}
        for label, path in (
            ("cases", "testcases"),
            ("cycles", "testcycles"),
            ("executions", "testexecutions"),
            ("plans", "testplans"),
        ):
            try:
                data = client._get(path, {"projectKey": key, "maxResults": 1})
                counts[label] = data.get("total", "?")
            except APIError:
                counts[label] = "ERR"
        _report(f"Project {key}", True, ", ".join(f"{k}={v}" for k, v in counts.items()))
        if counts.get("cases") == 0:
            _warn(f"Project {key} has 0 test cases", "wrong project key? (not an API problem)")

    # ---------------- Jira (optional, attachment downloads only) ----------------
    print("\n- Jira (optional) -")
    jira_email = str(config.get("jira.email") or "").strip()
    jira_token = str(config.get("jira.api_token") or "").strip()
    jira_set = [v for v in (jira_email, jira_token) if v and not _looks_placeholder(v)]
    if not jira_set:
        _warn(
            "Jira credentials not set",
            "attachments hosted in Jira rather than Zephyr will be skipped with a "
            "warning. Zephyr-hosted attachments are unaffected.",
        )
    elif len(jira_set) < 2:
        _report(
            "Jira credentials", False,
            "partially configured, set both jira.email and jira.api_token or neither",
        )
    else:
        _report("Jira credentials", True, f"{jira_email}")

    # ---------------- Qase ----------------
    print("\n- Qase -")
    from src.service.qase import qase_api_url, is_dedicated_cluster

    qase_host = str(config.get("qase.host") or "qase.io")
    api_url = qase_api_url(config)
    if is_dedicated_cluster(qase_host):
        _report("Qase host", True, f"{qase_host} treated as a dedicated cluster: {api_url}")
    try:
        resp = requests.get(
            f"{api_url}/v1/project",
            headers={"Token": str(config.get("qase.api_token"))},
            params={"limit": 1},
            timeout=(15, 30),
        )
        if resp.status_code == 200 and (resp.json() or {}).get("status"):
            total = ((resp.json().get("result") or {}).get("total")) or 0
            _report("Qase auth (GET /v1/project)", True, f"{total} project(s) in workspace")
        else:
            _report(
                "Qase auth (GET /v1/project)", False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return _finish()
    except requests.exceptions.RequestException as e:
        _report("Qase auth (GET /v1/project)", False, str(e)[:200])
        return _finish()

    # users.default resolves to a real Qase user (email or numeric id)
    from src.service.qase import QaseService

    try:
        qase = QaseService(config, logger)
        user_id = qase.resolve_user_id(config.get("users.default"))
        _report("users.default", True, f"resolves to Qase user id {user_id}")
    except ValueError as e:
        _report("users.default", False, str(e))
    except Exception as e:
        _report("users.default", False, f"could not be checked: {e!r}")

    return _finish()


def _finish():
    failed = _results.count(False)
    print()
    if failed:
        print(f"❌ Preflight FAILED, {failed} check(s) failed. Fix the items above before migrating.")
        sys.exit(1)
    print("✅ Preflight passed, ready to run: python start.py")
    sys.exit(0)


if __name__ == "__main__":
    main()
