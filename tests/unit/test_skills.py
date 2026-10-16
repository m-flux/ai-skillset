from pathlib import Path
from forgebench.skills.validator import SkillValidator


def _make_skill(root: Path, name="example-skill", frontmatter=None, body="# Instructions\n"):
    folder = root / name
    folder.mkdir()
    frontmatter = frontmatter or f"name: {name}\ndescription: Do the task and use this skill when it applies."
    (folder / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return folder


def test_valid_skill_and_optional_fields(tmp_path):
    folder = _make_skill(tmp_path, frontmatter='name: example-skill\ndescription: Do the task when applicable.\nmetadata:\n  version: "1"\nlicense: MIT')
    report = SkillValidator().validate(folder)
    assert report.valid
    assert report.optional_fields == ["license", "metadata"]


def test_name_must_match_folder(tmp_path):
    folder = _make_skill(tmp_path, frontmatter='name: other-skill\ndescription: Do the task when applicable.')
    report = SkillValidator().validate(folder)
    assert not report.valid
    assert any("match parent directory" in error.message for error in report.errors)


def test_duplicate_yaml_key_rejected(tmp_path):
    folder = _make_skill(tmp_path, frontmatter='name: example-skill\nname: example-skill\ndescription: Use this skill when asked.')
    report = SkillValidator().validate(folder)
    assert not report.valid
    assert any("duplicate YAML key" in error.message for error in report.errors)


def test_bad_types_and_unknown_field_warned(tmp_path):
    folder = _make_skill(tmp_path, frontmatter='name: example-skill\ndescription: Use this skill when asked.\nmetadata: []\nunknown-field: yes')
    report = SkillValidator().validate(folder)
    assert not report.valid
    assert report.warnings


def test_missing_skill_file(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    report = SkillValidator().validate(folder)
    assert not report.valid and "missing" in report.errors[0].message


def test_bundled_skills_valid(project_root):
    reports = SkillValidator().discover(project_root / "examples" / "skills")
    assert reports and all(r.valid for r in reports)
