"""Benchmark definitions loader and repeatable runner."""
from __future__ import annotations
import json
from pathlib import Path
from forgebench.agent.runtime import AgentRuntime
from forgebench.providers import MockProvider, OllamaProvider
from forgebench.schemas import RunRecord, TaskSpec
from forgebench.tracing.store import TraceStore


def load_tasks(path: str | Path) -> list[TaskSpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = [TaskSpec.model_validate(item) for item in raw.get("tasks", [])]
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Benchmark task IDs must be unique")
    return tasks


class BenchmarkRunner:
    def __init__(self, project_root: Path, store: TraceStore, runs_dir: Path, timeout_seconds: int = 30):
        self.project_root = project_root.resolve()
        self.store = store
        self.runs_dir = runs_dir.resolve()
        self.timeout_seconds = timeout_seconds
        self.runtime = AgentRuntime(store, timeout_seconds=timeout_seconds)
        self.tasks = load_tasks(self.project_root / "benchmarks" / "tasks.json")
        self.by_id = {task.id: task for task in self.tasks}

    def make_provider(self, provider_name: str, model: str | None = None, ollama_url: str = "http://localhost:11434"):
        if provider_name == "mock":
            return MockProvider()
        if provider_name == "ollama":
            if not model:
                raise ValueError("Ollama provider requires a model name")
            return OllamaProvider(ollama_url, model, timeout=max(30, self.timeout_seconds))
        raise ValueError(f"Unknown provider {provider_name!r}; choose mock or ollama")

    def run_one(self, task_id: str, provider_name: str = "mock", model: str | None = None,
                approve_tests: bool = False, ollama_url: str = "http://localhost:11434") -> RunRecord:
        if task_id not in self.by_id:
            raise KeyError(f"Unknown task {task_id!r}. Available: {', '.join(self.by_id)}")
        task = self.by_id[task_id]
        provider = self.make_provider(provider_name, model, ollama_url)
        fixture = (self.project_root / task.fixture).resolve()
        if self.project_root not in fixture.parents:
            raise ValueError("Fixture path must remain inside the ForgeBench project")
        skill_dir = (self.project_root / "examples" / "skills" / task.required_skill).resolve()
        if self.project_root not in skill_dir.parents:
            raise ValueError("Skill path must remain inside the ForgeBench project")
        run_root = self.runs_dir / "workspaces"
        run_root.mkdir(parents=True, exist_ok=True)
        import uuid
        workspace = run_root / str(uuid.uuid4())
        workspace.parent.mkdir(parents=True, exist_ok=True)
        return self.runtime.run(task, provider, fixture, skill_dir, workspace, approve_tests=approve_tests)

    def benchmark(self, task_ids: list[str], provider_name: str = "mock", models: list[str] | None = None,
                  repetitions: int = 1, approve_tests: bool = False, ollama_url: str = "http://localhost:11434") -> list[RunRecord]:
        if repetitions < 1 or repetitions > 50:
            raise ValueError("repetitions must be between 1 and 50")
        if provider_name == "mock":
            models = [None]
        elif not models:
            raise ValueError("At least one --models entry is required for Ollama comparisons")
        results = []
        for model in models or [None]:
            for task_id in task_ids:
                for _ in range(repetitions):
                    results.append(self.run_one(task_id, provider_name, model, approve_tests, ollama_url))
        return results
