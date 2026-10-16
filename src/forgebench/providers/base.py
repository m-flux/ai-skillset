"""Provider interface for structured agent responses."""
from __future__ import annotations
from pathlib import Path
from typing import Protocol
from forgebench.schemas import ProviderOutput, TaskSpec


class ModelProvider(Protocol):
    @property
    def model_name(self) -> str: ...
    @property
    def provider_kind(self) -> str: ...
    def complete(self, task: TaskSpec, skill_text: str, workspace: Path) -> ProviderOutput: ...
