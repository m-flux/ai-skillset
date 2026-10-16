"""Shared typed contracts used by the provider, runtime, trace store, and reports."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TaskSpec(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    fixture: str = Field(min_length=1, max_length=240)
    target_file: str = Field(min_length=1, max_length=240)
    required_skill: str = Field(min_length=1, max_length=64)
    timeout_seconds: int = Field(default=30, ge=1, le=180)
    suite_version: str = "1.0"
    tags: list[str] = Field(default_factory=list)


class PatchProposal(StrictModel):
    path: str = Field(min_length=1, max_length=240)
    old_text: str = Field(min_length=1, max_length=12000)
    new_text: str = Field(max_length=12000)


class ModelOutput(StrictModel):
    selected_skill: str = Field(min_length=1, max_length=64)
    patch: PatchProposal
    summary: str = Field(min_length=1, max_length=2000)


class ProviderOutput(StrictModel):
    output: ModelOutput
    model: str
    latency_ms: int = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    provider_kind: Literal["mock", "ollama"]


class RunRecord(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    provider: str
    model: str
    status: Literal["passed", "failed", "unverified", "error"]
    verified: bool = False
    test_exit_code: int | None = None
    selected_skill: str | None = None
    required_skill: str
    patch_applied: bool = False
    structured_output_valid: bool | None = None
    policy_rejections: int = 0
    duration_ms: int = 0
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    failure_category: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    workspace_path: str | None = None
    suite_version: str = "1.0"


class RunEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    timestamp: str = Field(default_factory=utc_now)
    event_type: str = Field(min_length=1, max_length=80)
    step: int = Field(default=0, ge=0)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_size_limit(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json
        if len(json.dumps(value, default=str, ensure_ascii=False)) > 20_000:
            raise ValueError("event metadata exceeds 20 KB")
        return value
