"""Integrated run lifecycle: skill → model → patch → independent verification → trace."""
from __future__ import annotations
import time
from pathlib import Path
from uuid import uuid4
from forgebench.providers.base import ModelProvider
from forgebench.repository.workspace import SafeWorkspace, WorkspacePolicyError
from forgebench.schemas import RunEvent, RunRecord, TaskSpec
from forgebench.skills.validator import SkillValidator
from forgebench.tracing.store import TraceStore


class AgentRuntime:
    def __init__(self, store: TraceStore, timeout_seconds: int = 30, output_limit: int = 12000):
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit

    def run(self, task: TaskSpec, provider: ModelProvider, fixture_dir: Path, skill_dir: Path,
            workspace_dir: Path, approve_tests: bool = False) -> RunRecord:
        run_id = str(uuid4())
        started = time.perf_counter()
        workspace_dir.mkdir(parents=True, exist_ok=False)
        self._copy_fixture(fixture_dir, workspace_dir)
        run = RunRecord(id=run_id, task_id=task.id, provider=provider.provider_kind,
                        model=provider.model_name, status="error", required_skill=task.required_skill,
                        workspace_path=str(workspace_dir), suite_version=task.suite_version)
        self.store.save_run(run)
        self._event(run_id, "run.started", 0, {"task_id": task.id, "provider": provider.provider_kind, "model": provider.model_name})
        validator = SkillValidator()
        skill_report = validator.validate(skill_dir)
        self._event(run_id, "skill.validation", 1, {"valid": skill_report.valid, "errors": [d.model_dump() for d in skill_report.errors], "skill_name": skill_report.name})
        if not skill_report.valid:
            run.status = "error"
            run.failure_category = "invalid_skill"
            run.error = f"Required skill failed validation: {skill_dir}"
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            self.store.save_run(run)
            self._event(run_id, "run.completed", 99, run.model_dump(mode="json"))
            return run
        self._event(run_id, "skill.selected", 2, {"required": task.required_skill, "loaded": skill_report.name})
        tool = SafeWorkspace(workspace_dir, self.output_limit)
        try:
            self._event(run_id, "model.request", 3, {"task": task.description, "target_file": task.target_file,
                                                    "skill": skill_report.name, "request_kind": provider.provider_kind})
            provider_result = provider.complete(task, _skill_document(skill_dir), workspace_dir)
            output = provider_result.output
            run.structured_output_valid = True
            run.latency_ms = provider_result.latency_ms
            run.prompt_tokens = provider_result.prompt_tokens
            run.completion_tokens = provider_result.completion_tokens
            run.selected_skill = output.selected_skill
            self._event(run_id, "model.response", 4, {"selected_skill": output.selected_skill,
                                                       "summary": output.summary, "patch_path": output.patch.path,
                                                       "provider": provider_result.provider_kind,
                                                       "latency_ms": provider_result.latency_ms,
                                                       "prompt_tokens": provider_result.prompt_tokens,
                                                       "completion_tokens": provider_result.completion_tokens})
            patch_input = {"path": output.patch.path, "old_text": output.patch.old_text, "new_text": output.patch.new_text}
            correlation_id = str(uuid4())
            try:
                diff = tool.apply_patch(output.patch.path, output.patch.old_text, output.patch.new_text)
                run.patch_applied = True
                self._event(run_id, "tool.result", 5, {"tool": "apply_patch", "input": {"path": output.patch.path},
                                                        "output": {"accepted": True, "diff": diff[:self.output_limit]},
                                                        "policy": "allowed"}, correlation_id)
                self._event(run_id, "patch.applied", 6, {"path": output.patch.path, "diff": diff[:self.output_limit]})
            except WorkspacePolicyError as exc:
                run.policy_rejections += 1
                run.failure_category = "tool_policy_rejected"
                self._event(run_id, "tool.rejected", 5, {"tool": "apply_patch", "input": {"path": output.patch.path},
                                                          "reason": str(exc), "policy": "rejected"}, correlation_id)
                raise
            if not approve_tests:
                run.status = "unverified"
                run.verified = False
                run.failure_category = run.failure_category or "verification_not_approved"
                run.error = "Patch was applied in a disposable fixture, but test execution was not approved."
                self._event(run_id, "verification.skipped", 7, {"reason": "explicit approval required"})
            else:
                self._event(run_id, "tool.request", 7, {"tool": "run_tests", "input": {"command_policy": "fixed pytest allowlist"}})
                verify = tool.run_tests(timeout_seconds=min(task.timeout_seconds, self.timeout_seconds), approved=True)
                run.test_exit_code = verify.exit_code
                run.verified = verify.exit_code == 0 and output.selected_skill == task.required_skill
                if verify.exit_code == 0 and output.selected_skill == task.required_skill:
                    run.status = "passed"
                    run.failure_category = None
                elif verify.exit_code != 0:
                    run.status = "failed"
                    run.failure_category = "tests_failed" if not verify.timed_out else "tests_timeout"
                else:
                    run.status = "failed"
                    run.failure_category = "wrong_skill_selection"
                self._event(run_id, "tool.result", 8, {"tool": "run_tests", "input": {"command": verify.command},
                                                        "output": {"exit_code": verify.exit_code,
                                                                   "duration_ms": verify.duration_ms,
                                                                   "stdout": verify.stdout[-self.output_limit:],
                                                                   "stderr": verify.stderr[-self.output_limit:],
                                                                   "timed_out": verify.timed_out},
                                                        "policy": "allowed"})
                self._event(run_id, "tests.completed", 9, {"exit_code": verify.exit_code, "verified": run.verified,
                                                            "duration_ms": verify.duration_ms})
                if not run.verified:
                    run.error = "Objective verification did not meet every configured success criterion."
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            self.store.save_run(run)
            self._event(run_id, "run.completed", 99, run.model_dump(mode="json"))
            return run
        except Exception as exc:
            if "invalid structured response" in str(exc).lower() or "invalid structured" in str(exc).lower():
                run.structured_output_valid = False
                run.failure_category = "invalid_structured_output"
            run.status = "error"
            run.verified = False
            run.error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            if run.failure_category is None:
                run.failure_category = "provider_or_runtime_error"
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            self.store.save_run(run)
            self._event(run_id, "error", 98, {"type": type(exc).__name__, "message": str(exc)[:1000]})
            self._event(run_id, "run.completed", 99, run.model_dump(mode="json"))
            return run

    def _event(self, run_id: str, event_type: str, step: int, metadata: dict, correlation_id: str | None = None) -> None:
        event = RunEvent(run_id=run_id, event_type=event_type, step=step, metadata=metadata,
                         correlation_id=correlation_id or str(uuid4()))
        self.store.add_event(event)

    @staticmethod
    def _copy_fixture(source: Path, destination: Path) -> None:
        import shutil
        source = source.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Fixture directory not found: {source}")
        # A fixture is an input, not the user's active repository; do not copy symlinks.
        for item in source.rglob("*"):
            if item.is_symlink():
                raise WorkspacePolicyError(f"Fixture contains a symlink, refusing to copy: {item}")
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _skill_document(skill_dir: Path) -> str:
    report = SkillValidator().validate(skill_dir)
    return (skill_dir / "SKILL.md").read_text(encoding="utf-8")[:16000] if report.valid else ""
