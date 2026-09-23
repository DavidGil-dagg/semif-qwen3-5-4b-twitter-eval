"""Incremental evaluation metrics: confusion matrix, accuracy, per-class P/R/F1."""

from __future__ import annotations


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


class Metrics:
    """Accumulates results one row at a time and derives the full report on demand."""

    def __init__(self, labels: list[str]) -> None:
        self.labels = list(labels)
        self._index = {label: position for position, label in enumerate(self.labels)}
        size = len(self.labels)
        self.confusion = [[0] * size for _ in range(size)]
        self.total = 0
        self.errors = 0
        self.correct = 0
        self.seconds = 0.0

    def add(self, gold: str, predicted: str | None, elapsed_s: float, error: str | None = None) -> None:
        self.total += 1
        self.seconds += elapsed_s
        gold_index = self._index.get(gold)
        predicted_index = self._index.get(predicted) if predicted is not None else None
        if error is not None or gold_index is None or predicted_index is None:
            self.errors += 1
            return
        self.confusion[gold_index][predicted_index] += 1
        if gold_index == predicted_index:
            self.correct += 1

    @property
    def evaluated(self) -> int:
        return self.total - self.errors

    def snapshot(self) -> dict:
        size = len(self.labels)
        per_class = []
        for position, label in enumerate(self.labels):
            true_positive = self.confusion[position][position]
            support = sum(self.confusion[position])
            predicted_total = sum(self.confusion[row][position] for row in range(size))
            false_positive = predicted_total - true_positive
            false_negative = support - true_positive
            precision = _safe_div(true_positive, true_positive + false_positive)
            recall = _safe_div(true_positive, true_positive + false_negative)
            f1 = _safe_div(2 * precision * recall, precision + recall)
            per_class.append(
                {
                    "label": label,
                    "support": support,
                    "predicted": predicted_total,
                    "true_positive": true_positive,
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                }
            )

        macro_pool = [
            row for row in per_class if row["support"] > 0 or row["predicted"] > 0
        ] or per_class
        macro = {
            "precision": _safe_div(sum(row["precision"] for row in macro_pool), len(macro_pool)),
            "recall": _safe_div(sum(row["recall"] for row in macro_pool), len(macro_pool)),
            "f1": _safe_div(sum(row["f1"] for row in macro_pool), len(macro_pool)),
        }
        weighted = {
            key: _safe_div(sum(row[key] * row["support"] for row in per_class), self.evaluated)
            for key in ("precision", "recall", "f1")
        }

        return {
            "labels": self.labels,
            "confusion": self.confusion,
            "total": self.total,
            "evaluated": self.evaluated,
            "errors": self.errors,
            "correct": self.correct,
            "accuracy": _safe_div(self.correct, self.evaluated),
            "per_class": per_class,
            "macro": macro,
            "weighted": weighted,
            "latency_ms_avg": _safe_div(self.seconds * 1000, self.total),
            "seconds": self.seconds,
        }

    def confusion_csv(self) -> str:
        header = ["gold\\predicted", *self.labels]
        lines = [",".join(header)]
        for position, label in enumerate(self.labels):
            lines.append(",".join([label, *(str(value) for value in self.confusion[position])]))
        return "\n".join(lines) + "\n"
