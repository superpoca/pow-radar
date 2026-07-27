from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    github_token: str | None
    database_url: str
    telegram_token: str | None
    telegram_chat_id: str | None
    keywords_file: Path
    rules_file: Path
    github_api_base: str
    github_timeout_seconds: float
    github_max_pages: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            github_token=os.getenv("GITHUB_TOKEN") or None,
            database_url=os.getenv("DATABASE_URL", "sqlite:///pow-radar.db"),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            keywords_file=_resolve_path(os.getenv("KEYWORDS_FILE", "config/keywords.yaml")),
            rules_file=_resolve_path(os.getenv("RULES_FILE", "config/score_rules.yaml")),
            github_api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
            github_timeout_seconds=float(os.getenv("GITHUB_TIMEOUT_SECONDS", "20")),
            github_max_pages=int(os.getenv("GITHUB_MAX_PAGES", "3")),
        )

    def keywords(self) -> dict[str, Any]:
        return _read_yaml(self.keywords_file)

    def rules(self) -> dict[str, Any]:
        return _read_yaml(self.rules_file)


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (BASE_DIR / path).resolve()


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
