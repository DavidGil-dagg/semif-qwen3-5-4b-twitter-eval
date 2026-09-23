"""Async HTTP client for the SemIf decision API."""

from __future__ import annotations

import asyncio

import httpx

from .config import Settings

RETRY_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)


class DecisionError(RuntimeError):
    """A row-level failure (bad payload, token overflow) that will not be retried."""


class SemIfClient:
    """Thin wrapper over ``/ready``, ``/models`` and ``/decide``."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.semif_api_url.rstrip("/")
        self._max_state_chars = settings.max_state_chars
        self._timeout = settings.request_timeout_s
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def probe(self) -> dict:
        """Current API status; never raises."""
        try:
            response = await self._client.get(f"{self._base}/ready", timeout=5.0)
            payload = response.json() if response.content else {}
            return {
                "reachable": True,
                "ready": response.status_code == 200,
                "status": payload.get("status", "unknown"),
                "model": payload.get("model"),
                "device": payload.get("device"),
                "dtype": payload.get("dtype"),
            }
        except httpx.HTTPError as error:
            return {"reachable": False, "ready": False, "status": "unreachable", "error": str(error)}

    async def wait_ready(self, timeout_s: float, on_update) -> bool:
        """Poll ``/ready`` until the model is loaded; report each probe via ``on_update``."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            probe = await self.probe()
            on_update(probe)
            if probe["ready"]:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(2.0)

    async def decide(self, state: str, question: str, options: list[dict]) -> dict:
        """Score one decision, retrying transient failures with backoff."""
        text = state[: self._max_state_chars]
        payload = {"state": text, "question": question, "options": options}
        last_error: Exception | None = None
        for attempt, delay in enumerate((0.0, *RETRY_BACKOFF_S)):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._client.post(f"{self._base}/decide", json=payload)
            except httpx.HTTPError as error:
                last_error = error
                continue
            if response.status_code == 200:
                result = response.json()
                return {
                    "choice": result["choice"],
                    "scores": result["scores"],
                    "option_ids": result.get("option_ids", []),
                    "total_seconds": result.get("total_seconds"),
                }
            if response.status_code in (422,):
                raise DecisionError(_detail(response))
            if response.status_code == 503:
                last_error = RuntimeError("model not ready (503)")
                continue
            last_error = RuntimeError(f"HTTP {response.status_code}: {_detail(response)}")
        raise DecisionError(f"giving up after {1 + len(RETRY_BACKOFF_S)} attempts: {last_error}")


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text
