import pytest
from pydantic import ValidationError
from forgebench.schemas import PatchProposal, RunEvent, TaskSpec


def test_task_requires_stable_fields():
    task = TaskSpec(id="t", description="desc", fixture="fixture", target_file="x.py", required_skill="python-bugfix")
    assert task.timeout_seconds == 30


def test_patch_rejects_extra_fields():
    with pytest.raises(ValidationError):
        PatchProposal(path="x.py", old_text="a", new_text="b", command="rm -rf /")


def test_event_rejects_oversized_metadata():
    with pytest.raises(ValidationError):
        RunEvent(run_id="x", event_type="test", metadata={"large": "x" * 21000})
