"""Constrained workspace helpers. These are app-level protections, not an OS sandbox."""
from __future__ import annotations
import difflib
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from pydantic import BaseModel


class WorkspacePolicyError(ValueError):
    pass


class VerificationResult(BaseModel):
    command: list[str]
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    timed_out: bool = False


class SafeWorkspace:
    def __init__(self, root: str | Path, output_limit: int = 12000):
        self.root = Path(root).resolve()
        self.output_limit = output_limit
        if not self.root.is_dir():
            raise WorkspacePolicyError(f"Workspace does not exist: {self.root}")

    def resolve_file(self, relative_path: str, *, for_write: bool = False) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspacePolicyError("A non-empty relative path is required")
        normalized = relative_path.replace("\\", "/")
        candidate_posix = PurePosixPath(normalized)
        if candidate_posix.is_absolute() or any(part in ("..", "") for part in candidate_posix.parts):
            raise WorkspacePolicyError("Absolute paths and parent traversal are not allowed")
        if candidate_posix.parts and ":" in candidate_posix.parts[0]:
            raise WorkspacePolicyError("Drive-qualified paths are not allowed")
        candidate = self.root.joinpath(*candidate_posix.parts)
        current = self.root
        for part in candidate_posix.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspacePolicyError("Symlink paths are not allowed")
        resolved = candidate.resolve(strict=False)
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspacePolicyError("Path escapes the assigned workspace")
        if for_write:
            rel = candidate_posix.as_posix().lower()
            if candidate.suffix.lower() != ".py":
                raise WorkspacePolicyError("Only existing Python source files can be modified")
            if any(part.lower().startswith("test") or part.lower() == "tests" for part in candidate_posix.parts):
                raise WorkspacePolicyError("Test files are protected from model edits")
            if any(token in rel for token in (".env", "secret", "credential", "private", "id_rsa", "config", "setting")):
                raise WorkspacePolicyError("Sensitive/configuration paths are protected")
        if not candidate.is_file():
            raise WorkspacePolicyError("Target must be an existing regular file inside the workspace")
        return candidate

    def list_files(self, limit: int = 200) -> list[str]:
        found = []
        for path in sorted(self.root.rglob("*")):
            if path.is_symlink():
                continue
            if path.is_file() and not any(p in {".git", ".venv", "__pycache__"} for p in path.parts):
                found.append(path.relative_to(self.root).as_posix())
                if len(found) >= limit:
                    break
        return found

    def read_file(self, relative_path: str) -> str:
        path = self.resolve_file(relative_path)
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:self.output_limit]

    def search(self, needle: str, limit: int = 50) -> list[dict[str, object]]:
        if not needle:
            return []
        result = []
        for name in self.list_files():
            if not name.endswith((".py", ".md", ".toml", ".json", ".txt")):
                continue
            try:
                lines = self.read_file(name).splitlines()
            except (OSError, WorkspacePolicyError):
                continue
            for number, line in enumerate(lines, 1):
                if needle.casefold() in line.casefold():
                    result.append({"path": name, "line": number, "text": line[:300]})
                    if len(result) >= limit:
                        return result
        return result

    def diff(self, relative_path: str, old: str, new: str) -> str:
        return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                             fromfile=f"a/{relative_path}", tofile=f"b/{relative_path}"))

    def apply_patch(self, relative_path: str, old_text: str, new_text: str) -> str:
        path = self.resolve_file(relative_path, for_write=True)
        if not old_text:
            raise WorkspacePolicyError("Empty replacement anchors are forbidden")
        source = path.read_text(encoding="utf-8")
        count = source.count(old_text)
        if count != 1:
            raise WorkspacePolicyError(f"Patch anchor must match exactly once; found {count} matches")
        updated = source.replace(old_text, new_text, 1)
        # Syntax-check before writing so a broken parse does not reach disk.
        import ast
        try:
            ast.parse(updated, filename=relative_path)
        except SyntaxError as exc:
            raise WorkspacePolicyError(f"Proposed patch has a Python syntax error: {exc}") from exc
        path.write_text(updated, encoding="utf-8")
        return self.diff(relative_path, source, updated)

    def run_tests(self, timeout_seconds: int, approved: bool) -> VerificationResult:
        if not approved:
            raise WorkspacePolicyError("Test execution requires explicit approval via --approve-tests")
        # Fixed argument vector, no shell, and no user/model-supplied command string.
        command = [sys.executable, "-m", "pytest", "-q"]
        import time
        started = time.perf_counter()
        try:
            proc = subprocess.run(command, cwd=self.root, shell=False, capture_output=True,
                                  text=True, timeout=timeout_seconds, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            duration = round((time.perf_counter() - started) * 1000)
            return VerificationResult(command=command, exit_code=proc.returncode, duration_ms=duration,
                                      stdout=proc.stdout[-self.output_limit:], stderr=proc.stderr[-self.output_limit:])
        except subprocess.TimeoutExpired as exc:
            duration = round((time.perf_counter() - started) * 1000)
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return VerificationResult(command=command, exit_code=124, duration_ms=duration,
                                      stdout=stdout[-self.output_limit:], stderr=(stderr + "\nTest command timed out")[-self.output_limit:], timed_out=True)
