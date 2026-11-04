"""Polite async HTTP client with retries and an optional on-disk JSON cache."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_MAILTO = os.getenv("KORA_MAILTO", "dev@example.com")
USER_AGENT = f"KoraAggregator/0.2 (+https://github.com/; mailto:{DEFAULT_MAILTO})"


class HttpClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        cache_ttl: float = 24 * 3600,
        timeout: float = 20.0,
        max_retries: int = 2,
        max_retry_wait: float = 6.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path | None:
        if not self.cache_dir:
            return None
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        path = self._cache_path(url, params)
        if path and path.exists() and time.time() - path.stat().st_mtime < self.cache_ttl:
            return json.loads(path.read_text(encoding="utf-8"))

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"retryable {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                data = resp.json()
                if path:
                    path.write_text(json.dumps(data), encoding="utf-8")
                return data
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                if status and status < 500 and status != 429:
                    break  # non-retryable client error
                delay = 0.8 * (2**attempt)
                if status == 429 and response is not None:
                    retry_after = _retry_after_seconds(response)
                    if retry_after is not None and retry_after > self.max_retry_wait:
                        break  # don't block the whole request for long rate-limit windows
                    delay = max(delay, retry_after or 0)
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc


def _retry_after_seconds(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header and header.strip().isdigit():
        return float(header)
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("retryAfter"), (int, float)):
            return float(body["retryAfter"])
    except ValueError:
        pass
    return None
