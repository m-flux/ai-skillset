from pathlib import Path
import pytest
from forgebench.repository.workspace import SafeWorkspace, WorkspacePolicyError


def setup_ws(tmp_path):
    (tmp_path / "solution.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_solution.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    (tmp_path / "settings.py").write_text("value = 1\n", encoding="utf-8")
    return SafeWorkspace(tmp_path)

@pytest.mark.parametrize("path", ["../outside.py", "..\\outside.py", "/tmp/secret.py", "C:\\temp\\a.py", "sub/../../x.py"])
def test_traversal_absolute_and_drive_paths_rejected(tmp_path, path):
    ws = setup_ws(tmp_path)
    with pytest.raises(WorkspacePolicyError):
        ws.resolve_file(path)


def test_test_file_write_rejected(tmp_path):
    ws = setup_ws(tmp_path)
    with pytest.raises(WorkspacePolicyError):
        ws.apply_patch("test_solution.py", "assert True", "assert False")


def test_non_python_or_config_write_rejected(tmp_path):
    ws = setup_ws(tmp_path)
    with pytest.raises(WorkspacePolicyError):
        ws.resolve_file("settings.py", for_write=True)
    (tmp_path / "readme.md").write_text("hi")
    with pytest.raises(WorkspacePolicyError):
        ws.resolve_file("readme.md", for_write=True)


def test_patch_requires_unique_anchor_and_valid_syntax(tmp_path):
    ws = setup_ws(tmp_path)
    (tmp_path / "solution.py").write_text("def f():\n    return 1\n\ndef g():\n    return 1\n", encoding="utf-8")
    with pytest.raises(WorkspacePolicyError, match="exactly once"):
        ws.apply_patch("solution.py", "return 1", "return 2")
    with pytest.raises(WorkspacePolicyError, match="syntax error"):
        ws.apply_patch("solution.py", "def f():", "def f( ")


def test_patch_applies_and_creates_diff(tmp_path):
    ws = setup_ws(tmp_path)
    diff = ws.apply_patch("solution.py", "    return 1", "    return 2")
    assert "+    return 2" in diff
    assert "return 2" in (tmp_path / "solution.py").read_text()


def test_symlink_rejected(tmp_path):
    ws = setup_ws(tmp_path)
    outside = tmp_path.parent / "outside.py"
    outside.write_text("safe = True\n")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(WorkspacePolicyError):
        ws.resolve_file("linked.py")


def test_tests_need_explicit_approval(tmp_path):
    ws = setup_ws(tmp_path)
    with pytest.raises(WorkspacePolicyError, match="approval"):
        ws.run_tests(5, approved=False)
