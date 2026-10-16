"""Configuration loaded from environment and optional local .env file."""
from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class Settings(BaseModel):
    provider: str = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    database_path: Path = Path("forgebench.sqlite3")
    runs_dir: Path = Path("runs")
    reports_dir: Path = Path("reports")
    timeout_seconds: int = Field(default=30, ge=1, le=180)
    max_tool_output_chars: int = Field(default=12000, ge=500, le=50000)


def load_settings(project_root: Path | None = None) -> Settings:
    root = (project_root or Path.cwd()).resolve()
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    def resolve(raw: str, default: str) -> Path:
        path = Path(raw or default).expanduser()
        return path if path.is_absolute() else root / path

    return Settings(
        provider=os.getenv("FORGEBENCH_PROVIDER", "mock").lower().strip(),
        ollama_url=os.getenv("FORGEBENCH_OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("FORGEBENCH_OLLAMA_MODEL", "qwen2.5-coder:7b").strip(),
        database_path=resolve(os.getenv("FORGEBENCH_DB", "forgebench.sqlite3"), "forgebench.sqlite3"),
        runs_dir=resolve(os.getenv("FORGEBENCH_RUNS_DIR", "runs"), "runs"),
        reports_dir=resolve(os.getenv("FORGEBENCH_REPORTS_DIR", "reports"), "reports"),
        timeout_seconds=int(os.getenv("FORGEBENCH_TIMEOUT_SECONDS", "30")),
    )
