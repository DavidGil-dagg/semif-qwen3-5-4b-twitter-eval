"""Reading the headerless tweet CSV into classification jobs."""

from __future__ import annotations

import csv
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Settings
from .labels import normalize_label


@dataclass(slots=True)
class Job:
    index: int
    row_id: str
    topic: str
    text: str
    gold: str
    gold_raw: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Dataset:
    jobs: list[Job]
    path: str
    total_rows: int
    skipped_empty: int
    skipped_label: int
    gold_distribution: dict[str, int] = field(default_factory=dict)

    def info(self, labels: list[str]) -> dict:
        """Dataset metadata plus the gold distribution in the configured label order."""
        distribution = {label: self.gold_distribution.get(label, 0) for label in labels}
        return {
            "path": self.path,
            "total_rows": self.total_rows,
            "eligible": self.total_rows - self.skipped_empty - self.skipped_label,
            "selected": len(self.jobs),
            "skipped_empty": self.skipped_empty,
            "skipped_label": self.skipped_label,
            "gold_distribution": distribution,
        }


def _cell(row: list[str], column: int) -> str:
    return row[column].strip() if 0 <= column < len(row) else ""


def load_dataset(settings: Settings, limit: int, sample: str) -> Dataset:
    """Load the CSV, drop unusable rows, and take ``limit`` rows (0 means all)."""
    path: Path = settings.csv_file
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    jobs: list[Job] = []
    total_rows = 0
    skipped_empty = 0
    skipped_label = 0
    distribution: dict[str, int] = {}

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            total_rows += 1
            text = _cell(row, settings.text_column)
            if not text or text.lower() in {"nan", "none"}:
                skipped_empty += 1
                continue
            gold_raw = _cell(row, settings.label_column)
            gold = normalize_label(gold_raw)
            if gold is None:
                skipped_label += 1
                continue
            distribution[gold] = distribution.get(gold, 0) + 1
            jobs.append(
                Job(
                    index=len(jobs) + 1,
                    row_id=_cell(row, settings.id_column),
                    topic=_cell(row, settings.topic_column),
                    text=text,
                    gold=gold,
                    gold_raw=gold_raw,
                )
            )

    selected = jobs
    if limit and limit > 0:
        if sample == "random" and limit < len(jobs):
            selected = random.Random(settings.seed).sample(jobs, limit)
        else:
            selected = jobs[:limit]

    # Renumber so ``index`` is the run order (1..N), independent of the file order.
    selected = [
        Job(
            index=position,
            row_id=job.row_id,
            topic=job.topic,
            text=job.text,
            gold=job.gold,
            gold_raw=job.gold_raw,
        )
        for position, job in enumerate(selected, 1)
    ]

    return Dataset(
        jobs=selected,
        path=str(path),
        total_rows=total_rows,
        skipped_empty=skipped_empty,
        skipped_label=skipped_label,
        gold_distribution=distribution,
    )
