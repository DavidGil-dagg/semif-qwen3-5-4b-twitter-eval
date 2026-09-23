"""Orchestration: classify the dataset row by row and publish live events."""

from __future__ import annotations

import asyncio
import json
import time

from .client import DecisionError, SemIfClient
from .config import Settings
from .dataset import Dataset, Job, load_dataset
from .labels import label_ids, to_options
from .metrics import Metrics

MAX_RECENT = 60


class EventBus:
    """Fan-out of JSON events to every connected SSE client."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


class Runner:
    """Owns one classification run, its metrics and the live event stream."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bus = EventBus()
        self.client = SemIfClient(settings)
        self.status = "idle"
        self.error: str | None = None
        self.semif: dict = {"reachable": False, "ready": False, "status": "unknown"}
        self.dataset: Dataset | None = None
        self.metrics: Metrics | None = None
        self.recent: list[dict] = []
        self.current: dict | None = None
        self.total = 0
        self.done = 0
        self.started_at: float | None = None
        self.finished_at: float | None = None

        self._task: asyncio.Task | None = None
        self._pause = asyncio.Event()
        self._pause.set()
        self._stop = asyncio.Event()
        self._results_handle = None

    # ---- control -------------------------------------------------------
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, limit: int, sample: str) -> None:
        if self.is_running():
            raise RuntimeError("a run is already in progress")
        self._stop.clear()
        self._pause.set()
        self._task = asyncio.create_task(self._run(limit, sample))

    def pause(self) -> None:
        if self.is_running():
            self._pause.clear()
            self._set_status("paused")

    def resume(self) -> None:
        if self.is_running():
            self._pause.set()
            self._set_status("running")

    def stop(self) -> None:
        self._stop.set()
        self._pause.set()

    async def shutdown(self) -> None:
        self.stop()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        await self.client.close()

    # ---- state ---------------------------------------------------------
    def _set_status(self, status: str) -> None:
        self.status = status
        self.bus.publish({"type": "status", "status": status, "error": self.error})

    def _on_probe(self, probe: dict) -> None:
        self.semif = probe
        self.bus.publish({"type": "semif", "semif": probe})

    def progress(self) -> dict:
        reference = self.finished_at or time.perf_counter()
        elapsed = (reference - self.started_at) if self.started_at else 0.0
        # Prefer measured inference time over wall clock so pauses do not distort the ETA.
        seconds = self.metrics.seconds if self.metrics else elapsed
        average = (seconds / self.done) if self.done else 0.0
        remaining = max(self.total - self.done, 0)
        return {
            "done": self.done,
            "total": self.total,
            "elapsed_s": round(elapsed, 1),
            "avg_ms": round(average * 1000, 1),
            "eta_s": round(average * remaining, 1) if self.done else None,
        }

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "error": self.error,
            "semif": self.semif,
            "progress": self.progress(),
            "metrics": self.metrics.snapshot() if self.metrics else None,
            "recent": self.recent,
            "dataset": self.dataset.info(label_ids(self.settings.labels)) if self.dataset else None,
            "settings": self.settings.summary(),
        }

    # ---- run -----------------------------------------------------------
    async def _run(self, limit: int, sample: str) -> None:
        self.error = None
        self.done = 0
        self.total = 0
        self.recent = []
        self.current = None
        self.metrics = None
        self.dataset = None
        self.finished_at = None
        self._set_status("waiting_ready")
        try:
            ready = await self.client.wait_ready(self.settings.ready_timeout_s, self._on_probe)
            if not ready:
                self.error = f"SemIf API not ready at {self.settings.semif_api_url}"
                self._set_status("error")
                self.bus.publish({"type": "done", "status": "error", "error": self.error})
                return

            dataset = load_dataset(self.settings, limit, sample)
            labels = label_ids(self.settings.labels)
            options = to_options(self.settings.labels)
            self.dataset = dataset
            self.metrics = Metrics(labels)
            self.total = len(dataset.jobs)
            self.bus.publish(
                {
                    "type": "dataset",
                    "dataset": dataset.info(labels),
                    "settings": self.settings.summary(),
                }
            )

            self.settings.results_path.mkdir(parents=True, exist_ok=True)
            self._results_handle = (self.settings.results_path / "predictions.jsonl").open(
                "w", encoding="utf-8"
            )
            self._set_status("running")
            self.started_at = time.perf_counter()
            try:
                for job in dataset.jobs:
                    if self._stop.is_set():
                        break
                    await self._pause.wait()
                    if self._stop.is_set():
                        break
                    await self._classify(job, options)
            finally:
                if self._results_handle is not None:
                    self._results_handle.close()
                    self._results_handle = None

            self.finished_at = time.perf_counter()
            final_status = "stopped" if self.done < self.total else "done"
            self._write_final_metrics()
            self._set_status(final_status)
            self.bus.publish(
                {
                    "type": "done",
                    "status": final_status,
                    "progress": self.progress(),
                    "metrics": self.metrics.snapshot() if self.metrics else None,
                }
            )
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.error = f"{type(error).__name__}: {error}"
            self._set_status("error")
            self.bus.publish({"type": "done", "status": "error", "error": self.error})

    async def _classify(self, job: Job, options: list[dict]) -> None:
        start = time.perf_counter()
        predicted: str | None = None
        scores: dict[str, float] = {}
        error: str | None = None
        try:
            result = await self.client.decide(job.text, self.settings.question, options)
            predicted = result["choice"]
            scores = result["scores"]
        except DecisionError as exc:
            error = str(exc)
        elapsed = time.perf_counter() - start

        self.metrics.add(job.gold, predicted, elapsed, error)
        self.done += 1
        record = {
            "index": job.index,
            "row_id": job.row_id,
            "topic": job.topic,
            "text": job.text,
            "gold": job.gold,
            "gold_raw": job.gold_raw,
            "predicted": predicted,
            "scores": scores,
            "correct": None if error else predicted == job.gold,
            "error": error,
            "elapsed_ms": round(elapsed * 1000, 1),
        }

        if self._results_handle is not None:
            self._results_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._results_handle.flush()

        self.current = record
        self.recent.append(record)
        if len(self.recent) > MAX_RECENT:
            self.recent.pop(0)
        self.bus.publish(
            {
                "type": "row",
                "row": record,
                "progress": self.progress(),
                "metrics": self.metrics.snapshot(),
            }
        )

    def _write_final_metrics(self) -> None:
        if self.metrics is None:
            return
        results = self.settings.results_path
        results.mkdir(parents=True, exist_ok=True)
        payload = {
            "dataset": self.dataset.info(label_ids(self.settings.labels)) if self.dataset else None,
            "progress": self.progress(),
            "semif": self.semif,
            "metrics": self.metrics.snapshot(),
        }
        (results / "metrics.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (results / "confusion_matrix.csv").write_text(
            self.metrics.confusion_csv(), encoding="utf-8"
        )
