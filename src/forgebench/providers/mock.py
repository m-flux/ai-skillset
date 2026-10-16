"""Deterministic offline provider for tests and honest demonstrations."""
from __future__ import annotations
from pathlib import Path
from time import perf_counter
from forgebench.schemas import ModelOutput, PatchProposal, ProviderOutput, TaskSpec

# Each old_text must match exactly once in its corresponding seed fixture.
RECIPES: dict[str, tuple[str, str, str]] = {
    "fix-zero-classification": (
        '    if number > 0:\n        return "positive"\n    return "negative"',
        '    if number > 0:\n        return "positive"\n    if number < 0:\n        return "negative"\n    return "zero"',
        "Handle zero as a separate numeric category.",
    ),
    "fix-safe-divide": (
        '    return numerator / denominator',
        '    if denominator == 0:\n        return None\n    return numerator / denominator',
        "Handle a zero denominator before division.",
    ),
    "fix-inclusive-range": (
        '    return start < value < end',
        '    return start <= value <= end',
        "Include both boundary values in the interval.",
    ),
}


class MockProvider:
    model_name = "forgebench-deterministic-demo-v1"
    provider_kind = "mock"

    def complete(self, task: TaskSpec, skill_text: str, workspace: Path) -> ProviderOutput:
        start = perf_counter()
        if task.id not in RECIPES:
            raise ValueError(f"No deterministic recipe exists for task {task.id!r}")
        old_text, new_text, summary = RECIPES[task.id]
        target = workspace / task.target_file
        source = target.read_text(encoding="utf-8")
        if source.count(old_text) != 1:
            raise ValueError(f"Mock recipe expected one source match in {task.target_file}")
        result = ModelOutput(
            selected_skill=task.required_skill,
            patch=PatchProposal(path=task.target_file, old_text=old_text, new_text=new_text),
            summary=summary,
        )
        return ProviderOutput(
            output=result,
            model=self.model_name,
            latency_ms=max(0, round((perf_counter() - start) * 1000)),
            prompt_tokens=None,
            completion_tokens=None,
            provider_kind="mock",
        )
