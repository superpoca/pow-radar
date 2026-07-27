import os
from dataclasses import dataclass
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    github_token: str | None
    database_url: str
    telegram_token: str | None
    telegram_chat_id: str | None
    keywords_file: Path
    rules_file: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(os.getenv("GITHUB_TOKEN") or None, os.getenv("DATABASE_URL", "sqlite:///pow-radar.db"), os.getenv("TELEGRAM_BOT_TOKEN") or None, os.getenv("TELEGRAM_CHAT_ID") or None, Path(os.getenv("KEYWORDS_FILE", "config/keywords.yaml")), Path(os.getenv("RULES_FILE", "config/score_rules.yaml")))

    def keywords(self) -> dict:
        return yaml.safe_load(self.keywords_file.read_text())

    def rules(self) -> dict:
        return yaml.safe_load(self.rules_file.read_text())
