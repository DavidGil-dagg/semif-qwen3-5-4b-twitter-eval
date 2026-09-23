"""FastAPI app: the web UI, the live SSE stream and the run controls."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import PROJECT_ROOT, load_settings
from .runner import Runner

WEB_DIR = PROJECT_ROOT / "web"

settings = load_settings()
runner = Runner(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await runner.shutdown()


app = FastAPI(title="Twitter Eval", version=__version__, lifespan=lifespan)


class StartRequest(BaseModel):
    limit: int | None = Field(default=None, ge=0)
    sample: str | None = None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/snapshot")
def snapshot() -> dict:
    """Full state, so a fresh or reconnecting client can render immediately."""
    return runner.snapshot()


@app.get("/api/semif")
async def semif() -> dict:
    """Ask the SemIf API for its current readiness (does not start a run)."""
    probe = await runner.client.probe()
    runner.semif = probe
    return probe


@app.get("/api/results")
def results() -> dict:
    """Final artifacts written by the last completed run."""
    metrics_file = settings.results_path / "metrics.json"
    if not metrics_file.exists():
        raise HTTPException(status_code=404, detail="no results yet")
    return json.loads(metrics_file.read_text(encoding="utf-8"))


@app.get("/api/misclassified")
def misclassified(limit: int = 100) -> list[dict]:
    """Rows the model got wrong, read back from the persisted predictions."""
    predictions = settings.results_path / "predictions.jsonl"
    if not predictions.exists():
        return []
    rows: list[dict] = []
    with predictions.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("error") or not record.get("correct"):
                rows.append(record)
    return rows[: max(0, limit)]


@app.post("/api/start")
async def start(payload: StartRequest) -> dict:
    if runner.is_running():
        raise HTTPException(status_code=409, detail="a run is already in progress")
    limit = settings.limit if payload.limit is None else payload.limit
    sample = (payload.sample or settings.sample).lower()
    if sample not in {"head", "random"}:
        raise HTTPException(status_code=422, detail="sample must be 'head' or 'random'")
    try:
        runner.start(limit, sample)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"started": True, "limit": limit, "sample": sample}


@app.post("/api/pause")
def pause() -> dict:
    runner.pause()
    return {"status": runner.status}


@app.post("/api/resume")
def resume() -> dict:
    runner.resume()
    return {"status": runner.status}


@app.post("/api/stop")
def stop() -> dict:
    runner.stop()
    return {"status": runner.status}


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-Sent Events: a snapshot first, then one event per classified row."""

    async def stream():
        queue = runner.bus.subscribe()
        try:
            yield _sse({"type": "snapshot", **runner.snapshot()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse(event)
        finally:
            runner.bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# Mounted last so /api and /events above win; serves index.html at "/".
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
