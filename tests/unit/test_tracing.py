import json
from pathlib import Path
from forgebench.schemas import RunEvent, RunRecord
from forgebench.tracing.store import TraceStore, redact, replay_recorded_tools


def _record(store, run_id="r1"):
    run = RunRecord(id=run_id, task_id="task", provider="mock", model="mock-v1", status="failed", required_skill="skill")
    store.save_run(run)
    return run


def test_run_and_events_persist(store):
    _record(store)
    store.add_event(RunEvent(run_id="r1", event_type="run.started", metadata={"task": "hello"}))
    assert store.get_run("r1").task_id == "task"
    assert store.events("r1")[0].metadata["task"] == "hello"


def test_export_import_jsonl_and_replay(store, tmp_path):
    _record(store)
    event = RunEvent(run_id="r1", event_type="tool.result", step=2,
                     metadata={"tool": "read_file", "input": {"path": "solution.py"}, "output": {"text": "x=1"}})
    store.add_event(event)
    path = store.export_jsonl("r1", tmp_path / "trace.jsonl")
    second = TraceStore(tmp_path / "second.sqlite3")
    report = second.import_jsonl(path)
    assert report["imported"] == 1
    replay = replay_recorded_tools(second.events("r1"))
    assert replay[0]["output"] == {"text": "x=1"}
    assert replay[0]["recorded_replay"] is True


def test_malformed_and_repeated_events_handled(store, tmp_path):
    _record(store)
    ev = RunEvent(run_id="r1", event_type="run.started")
    path = tmp_path / "bad.jsonl"
    path.write_text(ev.model_dump_json() + "\nnot-json\n" + ev.model_dump_json() + "\n", encoding="utf-8")
    result = store.import_jsonl(path)
    assert result["imported"] == 2
    assert len(result["rejected"]) == 1
    assert len(store.events("r1")) == 1  # duplicate event id ignored


def test_incomplete_trace_is_replayable_as_empty(store, tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert store.import_jsonl(path)["imported"] == 0


def test_size_cap(store, tmp_path):
    path = tmp_path / "huge.jsonl"
    path.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    import pytest
    with pytest.raises(ValueError, match="exceeds"):
        store.import_jsonl(path)


def test_redaction_redacts_sensitive_keys_and_patterns():
    result = redact({"api_key": "supersecret", "note": "password=hunter2", "nested": {"access_token": "abc"}})
    assert result["api_key"] == "[REDACTED]"
    assert "hunter2" not in result["note"]
    assert result["nested"]["access_token"] == "[REDACTED]"


def test_delete_run(store):
    _record(store)
    store.add_event(RunEvent(run_id="r1", event_type="run.started"))
    assert store.delete_run("r1") is True
    assert store.get_run("r1") is None


def test_shipped_failure_fixture_replays_without_execution(store, project_root):
    fixture = project_root / "examples" / "traces" / "failed-policy-rejection.jsonl"
    report = store.import_jsonl(fixture)
    assert report["imported"] == 4
    replay = replay_recorded_tools(store.events("fixture-failed-policy-rejection"))
    assert len(replay) == 1
    assert replay[0]["output"]["accepted"] is False
    assert replay[0]["recorded_replay"] is True


def test_imported_trace_does_not_become_a_benchmark_run(store, project_root):
    fixture = project_root / "examples" / "traces" / "failed-policy-rejection.jsonl"
    store.import_jsonl(fixture)
    assert store.list_runs() == []
    assert len(store.events("fixture-failed-policy-rejection")) == 4


def test_delete_imported_trace_without_run_record(store, project_root):
    fixture = project_root / "examples" / "traces" / "failed-policy-rejection.jsonl"
    store.import_jsonl(fixture)
    assert store.delete_run("fixture-failed-policy-rejection") is True
    assert store.events("fixture-failed-policy-rejection") == []
