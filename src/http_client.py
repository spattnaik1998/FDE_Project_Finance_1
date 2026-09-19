"""Shared HTTP session with retry, timeout and structured logging.

Every provider call in this project goes through :func:`get_json` or
:func:`post_json` so that retry policy, timeouts and logging are defined once
rather than re-implemented per source.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

LOG = logging.getLogger("fetch")

DEFAULT_TIMEOUT = 90
MAX_ATTEMPTS = 4
BACKOFF_BASE = 2.0


class FetchError(RuntimeError):
    """A provider request failed in a way retrying will not fix."""


def _request(method: str, url: str, *, source: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    last_exc: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            resp = requests.request(method, url, **kwargs)
            duration_ms = int((time.perf_counter() - started) * 1000)

            if resp.status_code == 200:
                LOG.info("source=%s status=ok http=%s duration_ms=%s",
                         source, resp.status_code, duration_ms)
                return resp

            # 4xx other than rate-limiting will not change on retry.
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise FetchError(
                    f"{source}: HTTP {resp.status_code} for {url} :: {resp.text[:300]}"
                )

            LOG.warning("source=%s status=retry http=%s attempt=%s duration_ms=%s",
                        source, resp.status_code, attempt, duration_ms)
            last_exc = FetchError(f"{source}: HTTP {resp.status_code}")

        except requests.RequestException as exc:
            LOG.warning("source=%s status=retry error=%s attempt=%s",
                        source, type(exc).__name__, attempt)
            last_exc = exc

        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_BASE ** attempt)

    raise FetchError(f"{source}: exhausted {MAX_ATTEMPTS} attempts for {url}") from last_exc


def get_json(url: str, *, source: str, params: dict[str, Any] | None = None) -> Any:
    """GET and decode JSON, raising :class:`FetchError` with provider context."""
    resp = _request("GET", url, source=source, params=params)
    try:
        return resp.json()
    except ValueError as exc:
        raise FetchError(f"{source}: non-JSON response :: {resp.text[:300]}") from exc


def post_json(url: str, *, source: str, payload: dict[str, Any]) -> Any:
    """POST a JSON body and decode the JSON response."""
    resp = _request("POST", url, source=source, json=payload,
                    headers={"Content-Type": "application/json"})
    try:
        return resp.json()
    except ValueError as exc:
        raise FetchError(f"{source}: non-JSON response :: {resp.text[:300]}") from exc
