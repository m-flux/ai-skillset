"""Agent Skills SKILL.md parser and conformance diagnostics."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field

ALLOWED_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def _valid_skill_name(name: str) -> bool:
    # The current specification describes Unicode lowercase alphanumeric names.
    # Keep hyphens as single separators and reject leading/trailing/repeated hyphens.
    if not name or len(name) > 64 or name.startswith("-") or name.endswith("-") or "--" in name:
        return False
    return all(ch == "-" or (ch.isalpha() and ch.islower()) or ch.isdigit() for ch in name)


class DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: object, line: int):
        self.key, self.line = key, line
        super().__init__(f"duplicate YAML key {key!r} at line {line}")


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    result: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise DuplicateKeyError(key, key_node.start_mark.line + 1)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


class Diagnostic(BaseModel):
    severity: str
    message: str
    path: str | None = None
    line: int | None = None


class SkillValidationReport(BaseModel):
    path: str
    valid: bool
    name: str | None = None
    description: str | None = None
    optional_fields: list[str] = Field(default_factory=list)
    errors: list[Diagnostic] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)
    instructions: str = ""
    files: list[str] = Field(default_factory=list)


class SkillValidator:
    def validate(self, skill_dir: str | Path) -> SkillValidationReport:
        folder = Path(skill_dir).expanduser().resolve()
        errors: list[Diagnostic] = []
        warnings: list[Diagnostic] = []
        skill_file = folder / "SKILL.md"
        result = SkillValidationReport(path=str(folder), valid=False)
        if not folder.is_dir():
            result.errors.append(Diagnostic(severity="error", message="Skill directory does not exist", path=str(folder)))
            return result
        if not skill_file.is_file():
            result.errors.append(Diagnostic(severity="error", message="Required SKILL.md file is missing", path=str(skill_file)))
            return result
        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            result.errors.append(Diagnostic(severity="error", message=f"Cannot read skill file: {exc}", path=str(skill_file)))
            return result
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            result.errors.append(Diagnostic(severity="error", message="SKILL.md must begin with YAML frontmatter delimiter ---", path=str(skill_file), line=1))
            result.errors.extend(errors)
            return result
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if closing is None:
            result.errors.append(Diagnostic(severity="error", message="YAML frontmatter is not closed by ---", path=str(skill_file), line=len(lines) or 1))
            return result
        raw_frontmatter = "\n".join(lines[1:closing])
        try:
            data: Any = yaml.load(raw_frontmatter, Loader=UniqueKeyLoader)
        except DuplicateKeyError as exc:
            result.errors.append(Diagnostic(severity="error", message=str(exc), path=str(skill_file), line=exc.line))
            return result
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            result.errors.append(Diagnostic(severity="error", message=f"Invalid YAML frontmatter: {exc}", path=str(skill_file), line=(mark.line + 2 if mark else None)))
            return result
        if not isinstance(data, dict):
            result.errors.append(Diagnostic(severity="error", message="YAML frontmatter must be a mapping/object", path=str(skill_file), line=2))
            return result
        unknown = sorted(str(key) for key in data if key not in ALLOWED_FIELDS)
        for key in unknown:
            warnings.append(Diagnostic(severity="warning", message=f"Unknown frontmatter field {key!r}; it is not defined by the current specification", path=str(skill_file)))
        # Preserve strict metadata checks but treat unrecognized future fields as warnings for forward compatibility.
        name = data.get("name")
        description = data.get("description")
        if not isinstance(name, str) or not name.strip():
            errors.append(Diagnostic(severity="error", message="Required field 'name' must be a non-empty string", path=str(skill_file)))
        else:
            name = name.strip()
            if len(name) > 64:
                errors.append(Diagnostic(severity="error", message="'name' must be at most 64 characters", path=str(skill_file)))
            if not _valid_skill_name(name):
                errors.append(Diagnostic(severity="error", message="'name' must contain lowercase letters/digits and single hyphens only; it cannot start/end with a hyphen or contain --", path=str(skill_file)))
            if name != folder.name:
                errors.append(Diagnostic(severity="error", message=f"'name' ({name!r}) must match parent directory name ({folder.name!r})", path=str(skill_file)))
        if not isinstance(description, str) or not description.strip():
            errors.append(Diagnostic(severity="error", message="Required field 'description' must be a non-empty string", path=str(skill_file)))
        elif len(description.strip()) > 1024:
            errors.append(Diagnostic(severity="error", message="'description' must be at most 1024 characters", path=str(skill_file)))
        for key in ("license", "allowed-tools"):
            if key in data and not isinstance(data[key], str):
                errors.append(Diagnostic(severity="error", message=f"Optional field {key!r} must be a string", path=str(skill_file)))
        if "compatibility" in data:
            value = data["compatibility"]
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
                errors.append(Diagnostic(severity="error", message="'compatibility' must be a non-empty string of at most 500 characters", path=str(skill_file)))
        if "metadata" in data:
            value = data["metadata"]
            if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
                errors.append(Diagnostic(severity="error", message="'metadata' must be a mapping of string keys to string values", path=str(skill_file)))
        files: list[str] = []
        for item in folder.rglob("*"):
            if item.is_symlink():
                warnings.append(Diagnostic(severity="warning", message="Symlinked skill resources are not followed by ForgeBench", path=str(item)))
            elif item.is_file():
                files.append(item.relative_to(folder).as_posix())
        if len(lines) > 500:
            warnings.append(Diagnostic(severity="warning", message="SKILL.md exceeds the recommended 500-line limit", path=str(skill_file)))
        instructions = "\n".join(lines[closing + 1:]).strip()
        if not instructions:
            warnings.append(Diagnostic(severity="warning", message="Skill has no instruction body after frontmatter", path=str(skill_file)))
        optional = sorted(key for key in data if key in ALLOWED_FIELDS and key not in {"name", "description"})
        return SkillValidationReport(path=str(folder), valid=not errors, name=name if isinstance(name, str) else None,
                                     description=description.strip() if isinstance(description, str) else None,
                                     optional_fields=optional, errors=errors, warnings=warnings,
                                     instructions=instructions, files=sorted(files))

    def discover(self, skills_root: str | Path) -> list[SkillValidationReport]:
        root = Path(skills_root).expanduser().resolve()
        if not root.is_dir():
            return [SkillValidationReport(path=str(root), valid=False, errors=[Diagnostic(severity="error", message="Skills root does not exist", path=str(root))])]
        dirs = sorted(p.parent for p in root.rglob("SKILL.md") if p.is_file() and not p.is_symlink())
        return [self.validate(folder) for folder in dirs]
