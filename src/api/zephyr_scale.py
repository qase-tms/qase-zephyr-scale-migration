import http.client
import time
from datetime import datetime, timezone

import requests

from ..exceptions.api import APIError

_DEFAULT_BASE_URL = "https://api.zephyrscale.smartbear.com/v2"


def _parse_zs_timestamp(value):
    """Zephyr Scale timestamp to epoch seconds, or None if it cannot be read.

    Accepts epoch milliseconds, epoch seconds, and the ISO 8601 form the API
    documents for planned dates (``2018-05-19T13:15:13Z``).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return int(value / 1000) if value > 1e10 else int(value)

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return int(number / 1000) if number > 1e10 else number

    cleaned = text.replace("Z", "+0000")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


class ZephyrScaleApiClient:
    """HTTP client for the Zephyr Scale Cloud REST API.

    Base URL: ``https://api.zephyrscale.smartbear.com/v2``
    Auth: ``Authorization: Bearer <jwt-token>``
    Pagination: ``startAt`` + ``maxResults`` (max 1000 per page).
    """

    def __init__(
        self,
        token: str,
        logger,
        base_url: str = _DEFAULT_BASE_URL,
        max_retries: int = 7,
        backoff_factor: float = 2.0,
        connect_timeout: float = 30.0,
        read_timeout: float = 60.0,
        page_size: int = 100,
    ):
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.logger = logger
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.request_timeout = (float(connect_timeout), float(read_timeout))
        self.page_size = int(page_size)

    # ------------------------------------------------------------------
    # Low-level request helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> dict:
        """GET ``{base_url}/{path}`` and return the parsed JSON body."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params or {},
                    timeout=self.request_timeout,
                )
                if response.status_code == 200:
                    try:
                        return response.json()
                    except (ValueError, requests.exceptions.JSONDecodeError) as e:
                        raise APIError(f"Non-JSON response from {path!r}") from e
                # Fast-fail on deterministic client errors (any 4xx except 408/429)
                if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                    raise APIError(
                        f"HTTP {response.status_code} (non-retryable) for {path!r}"
                    )
                time.sleep(self.backoff_factor * (2 ** attempt))
            except APIError:
                raise
            except (
                requests.exceptions.Timeout,
                http.client.RemoteDisconnected,
                ConnectionResetError,
                requests.exceptions.ConnectionError,
            ):
                time.sleep(self.backoff_factor * (2 ** attempt))

            if attempt == self.max_retries:
                raise APIError(f"Max retries reached for {path!r}")

    def _get_paginated(self, path: str, params: dict = None):
        """Yield all pages from a Zephyr Scale paginated endpoint.

        Zephyr Scale uses ``startAt`` / ``maxResults`` / ``isLast`` for pagination.
        Returns each page's ``values`` list as one batch.
        """
        start_at = 0
        base_params = dict(params or {})
        base_params["maxResults"] = self.page_size
        while True:
            base_params["startAt"] = start_at
            data = self._get(path, base_params)
            values = data.get("values") or []
            if values:
                yield values
            if data.get("isLast", True) or len(values) < self.page_size:
                break
            start_at += len(values)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def get_projects(self):
        """Return all Zephyr Scale–enabled projects."""
        all_projects = []
        for page in self._get_paginated("projects", {"maxResults": 50}):
            all_projects.extend(page)
        return all_projects

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def get_folders(self, project_key: str, folder_type: str = "TEST_CASE"):
        """Return all folders of *folder_type* for *project_key*.

        folder_type: ``TEST_CASE``, ``TEST_CYCLE``, or ``TEST_PLAN``
        """
        all_folders = []
        for page in self._get_paginated(
            "folders", {"projectKey": project_key, "folderType": folder_type}
        ):
            all_folders.extend(page)
        return all_folders

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    def get_test_cases(self, project_key: str, folder_id: int = None):
        """Yield pages of test cases for *project_key*, optionally filtered by *folder_id*."""
        params = {"projectKey": project_key}
        if folder_id is not None:
            params["folderId"] = folder_id
        yield from self._get_paginated("testcases", params)

    def get_test_case(self, test_case_key: str) -> dict:
        """Fetch a single test case with its full detail."""
        return self._get(f"testcases/{test_case_key}")

    def get_test_steps(self, test_case_key: str) -> list:
        """Return test steps for a test case (step-by-step type)."""
        data = self._get(f"testcases/{test_case_key}/teststeps")
        return data.get("values") or []

    # ------------------------------------------------------------------
    # Test cycles
    # ------------------------------------------------------------------

    def get_test_cycles(self, project_key: str, created_after: int = 0):
        """Yield pages of test cycles for *project_key*.

        ``created_after`` is epoch seconds. Zephyr Scale publishes no creation
        timestamp on a test cycle, so the filter reads ``createdOn`` when a
        tenant happens to return it and falls back to the documented
        ``plannedStartDate``. **A cycle carrying neither is kept, not dropped.**
        Filtering must never silently discard data it cannot date, and the
        caller is told how many cycles were kept that way.
        """
        params = {"projectKey": project_key}
        undated = 0
        total = 0
        for page in self._get_paginated("testcycles", params):
            total += len(page)
            if created_after:
                kept = []
                for cycle in page:
                    stamp = _parse_zs_timestamp(
                        cycle.get("createdOn") or cycle.get("plannedStartDate")
                    )
                    if stamp is None:
                        undated += 1
                        kept.append(cycle)
                    elif stamp >= created_after:
                        kept.append(cycle)
                page = kept
            if page:
                yield page

        if created_after and undated and self.logger:
            self.logger.log(
                f"[ZephyrScale] runs.created_after could not be applied to {undated} of "
                f"{total} cycle(s) in {project_key}: neither createdOn nor plannedStartDate "
                f"was present. Those cycles were kept rather than dropped, so the run list "
                f"may be wider than the filter asks for.",
                "warn",
            )

    def get_test_cycle(self, cycle_key: str) -> dict:
        """Fetch a single test cycle."""
        return self._get(f"testcycles/{cycle_key}")

    def get_test_plans(self, project_key: str):
        """Yield pages of test plans for *project_key*."""
        yield from self._get_paginated("testplans", {"projectKey": project_key})

    # ------------------------------------------------------------------
    # Test executions
    # ------------------------------------------------------------------

    def get_test_executions(self, project_key: str, test_cycle_key: str = None):
        """Yield pages of test executions, optionally filtered by cycle key."""
        params = {"projectKey": project_key}
        if test_cycle_key:
            params["testCycle"] = test_cycle_key
        yield from self._get_paginated("testexecutions", params)

    # ------------------------------------------------------------------
    # Statuses and priorities
    # ------------------------------------------------------------------

    def get_priorities(self, project_key: str) -> list:
        data = self._get("priorities", {"projectKey": project_key, "maxResults": 100})
        return data.get("values") or []

    def get_statuses(self, project_key: str, status_type: str = "TEST_CASE") -> list:
        data = self._get(
            "statuses",
            {"projectKey": project_key, "statusType": status_type, "maxResults": 100},
        )
        return data.get("values") or []

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def _get_optional(self, path: str, params: dict = None):
        """Like _get but returns None on 404 instead of raising."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params or {},
                timeout=self.request_timeout,
            )
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return None
            if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                return None
            return None
        except Exception:
            return None

    def get_test_case_attachments(self, tc_key: str) -> list:
        """Return normalised attachment list for a test case.

        The ZS API returns ``{"attachments": [{"id": 123, "name": "file.png"}]}``.
        We normalise each item to ``{"filename": name, "url": <download_url>}``
        so callers can treat file and execution attachments uniformly.
        Download URL: GET /testcases/{key}/attachments/{id} (Bearer token, no CDN).
        """
        data = self._get_optional(f"testcases/{tc_key}/attachments")
        if not data:
            return []
        raw = data.get("attachments") or data.get("values") or []
        result = []
        for a in raw:
            att_id = a.get("id")
            name = a.get("name") or a.get("filename") or "attachment"
            url = a.get("url") or (
                f"{self.base_url}/testcases/{tc_key}/attachments/{att_id}" if att_id else None
            )
            if url:
                result.append({"filename": name, "url": url})
        return result

    def get_test_execution_attachments(self, ex_id) -> list:
        """Return normalised attachment list for a test execution.

        Same normalisation as get_test_case_attachments.
        Download URL: GET /testexecutions/{id}/attachments/{att_id} (Bearer token).
        """
        data = self._get_optional(f"testexecutions/{ex_id}/attachments")
        if not data:
            return []
        raw = data.get("attachments") or data.get("values") or []
        result = []
        for a in raw:
            att_id = a.get("id")
            name = a.get("name") or a.get("filename") or "attachment"
            url = a.get("url") or (
                f"{self.base_url}/testexecutions/{ex_id}/attachments/{att_id}" if att_id else None
            )
            if url:
                result.append({"filename": name, "url": url})
        return result

    def download_attachment_bytes(
        self,
        url: str,
        jira_email: str = None,
        jira_api_token: str = None,
    ) -> bytes:
        """Download attachment binary.

        Tries in order:
        1. ZS Bearer token (Authorization header), for ZS-hosted file attachments
        2. The same token as a ``jwt`` cookie, for ZS CloudFront inline images
        3. Jira Basic auth (email + API token), for Jira-hosted attachments
        """
        jwt_val = self.headers.get("Authorization", "")
        if jwt_val.lower().startswith("bearer "):
            jwt_val = jwt_val[7:]

        attempts: list = [
            # (headers, cookies, auth)
            (self.headers, None, None),
            ({}, {"jwt": jwt_val}, None),
        ]
        if jira_email and jira_api_token:
            attempts.append(({}, None, (jira_email, jira_api_token)))

        for hdrs, cookies, auth in attempts:
            try:
                resp = requests.get(
                    url,
                    headers=hdrs or {},
                    cookies=cookies,
                    auth=auth,
                    timeout=(30.0, 120.0),
                    allow_redirects=True,
                )
                if resp.status_code == 200 and resp.content:
                    return resp.content
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # Custom fields
    # ------------------------------------------------------------------

    def get_custom_fields(self, project_key: str) -> list:
        try:
            all_fields = []
            for page in self._get_paginated(
                "customfields", {"projectKey": project_key}
            ):
                all_fields.extend(page)
            return all_fields
        except APIError:
            return []
