from forgebench.reporting.reports import make_report, write_reports


def test_all_mock_tasks_pass_with_approval(runner, tmp_path):
    runs = runner.benchmark(list(runner.by_id), provider_name="mock", approve_tests=True)
    assert len(runs) == 3
    assert all(r.status == "passed" and r.verified and r.test_exit_code == 0 for r in runs)
    assert all(r.selected_skill == r.required_skill for r in runs)
    report = make_report(runs)
    assert report["verified_successes"] == 3
    assert report["model_comparison"][0]["verified_success_rate"] == 1.0
    assert report["model_comparison"][0]["structured_output_valid_rate"] == 1.0
    assert report["model_comparison"][0]["tool_policy_violation_rate"] == 0.0
    json_path, md_path = write_reports(runs, tmp_path / "reports")
    assert json_path.is_file() and md_path.is_file()


def test_without_approval_never_claims_verified(runner):
    run = runner.run_one("fix-zero-classification", approve_tests=False)
    assert run.status == "unverified"
    assert not run.verified
    assert run.test_exit_code is None


def test_wrong_skill_selection_cannot_be_verified(runner, monkeypatch):
    from forgebench.providers.mock import MockProvider
    from forgebench.schemas import ProviderOutput, ModelOutput, PatchProposal
    class WrongSkillProvider:
        provider_kind = "mock"
        model_name = "wrong-skill-test"
        def complete(self, task, skill_text, workspace):
            src = (workspace / task.target_file).read_text()
            old = '    if number > 0:\n        return "positive"\n    return "negative"'
            new = '    if number > 0:\n        return "positive"\n    if number < 0:\n        return "negative"\n    return "zero"'
            return ProviderOutput(output=ModelOutput(selected_skill="wrong-skill", patch=PatchProposal(path=task.target_file, old_text=old, new_text=new), summary="patch"), model=self.model_name, latency_ms=1, provider_kind="mock")
    task = runner.by_id["fix-zero-classification"]
    fixture = runner.project_root / task.fixture
    skill = runner.project_root / "examples" / "skills" / task.required_skill
    import uuid
    workspace = runner.runs_dir / "wrong-skill" / str(uuid.uuid4())
    workspace.parent.mkdir(parents=True)
    run = runner.runtime.run(task, WrongSkillProvider(), fixture, skill, workspace, approve_tests=True)
    assert run.test_exit_code == 0
    assert run.status == "failed" and not run.verified
    assert run.failure_category == "wrong_skill_selection"
