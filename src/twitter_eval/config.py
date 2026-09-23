"""Configuration: config.toml merged with environment overrides."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


class LabelOption(BaseModel):
    """One class the model chooses from."""

    id: str
    description: str


DEFAULT_LABELS: list[LabelOption] = [
    LabelOption(
        id="positive",
        description="The tweet expresses a positive, favorable or supportive sentiment about the topic.",
    ),
    LabelOption(
        id="negative",
        description="The tweet expresses a negative, critical or unfavorable sentiment about the topic.",
    ),
    LabelOption(
        id="neutral",
        description="The tweet is factual or informational and expresses no clear positive or negative sentiment about the topic.",
    ),
    LabelOption(
        id="irrelevant",
        description="The tweet is not actually about the topic, or is off-topic noise.",
    ),
]


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    semif_api_url: str = "http://localhost:8000"
    csv_path: str = "archive/twitter_training.csv"
    limit: int = 300
    sample: str = "head"
    seed: int = 13

    request_timeout_s: float = 120.0
    ready_timeout_s: float = 300.0
    max_state_chars: int = 4000

    id_column: int = 0
    topic_column: int = 1
    label_column: int = 2
    text_column: int = 3

    question: str = "What is the sentiment of this tweet about the given topic?"
    labels: list[LabelOption] = Field(default_factory=lambda: list(DEFAULT_LABELS))

    host: str = "127.0.0.1"
    preferred_port: int = 8050
    results_dir: str = "results"

    @property
    def csv_file(self) -> Path:
        path = Path(self.csv_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def results_path(self) -> Path:
        path = Path(self.results_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def summary(self) -> dict:
        """The parts of the configuration the UI shows."""
        return {
            "question": self.question,
            "labels": [{"id": label.id, "description": label.description} for label in self.labels],
            "sample": self.sample,
            "max_state_chars": self.max_state_chars,
            "results_dir": self.results_dir,
        }


_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "SEMIF_API_URL": ("semif_api_url", str),
    "TWITTER_EVAL_CSV": ("csv_path", str),
    "TWITTER_EVAL_LIMIT": ("limit", int),
    "TWITTER_EVAL_RESULTS_DIR": ("results_dir", str),
}


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or DEFAULT_CONFIG_PATH
    data: dict = {}
    if path.exists():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    for env_key, (field, cast) in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_key)
        if raw:
            data[field] = cast(raw)
    return Settings(**data)
