from pathlib import Path
import pytest
from forgebench.tracing.store import TraceStore
from forgebench.benchmarks.runner import BenchmarkRunner

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def project_root():
    return ROOT

@pytest.fixture
def store(tmp_path):
    return TraceStore(tmp_path / "test.sqlite3")

@pytest.fixture
def runner(tmp_path, project_root, store):
    return BenchmarkRunner(project_root, store, tmp_path / "runs", timeout_seconds=15)
