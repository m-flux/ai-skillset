"""SQLite trace storage and line-oriented JSON event export/import."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from forgebench.schemas import RunEvent, RunRecord

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_LINE_BYTES = 25 * 1024


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if re.search(r"(?i)(api.?key|token|password|secret|private.?key)", str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        result = value
        for pattern in SECRET_PATTERNS:
            result = pattern.sub(lambda match: match.group(0).split("=")[0] + "=[REDACTED]" if "=" in match.group(0) else "[REDACTED]", result)
        return result[:20000]
    return value


class TraceStore:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                status TEXT NOT NULL, verified INTEGER NOT NULL, created_at TEXT NOT NULL, data_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
                step INTEGER NOT NULL, correlation_id TEXT NOT NULL, metadata_json TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, step, timestamp)")

    def save_run(self, run: RunRecord) -> None:
        data = run.model_dump(mode="json")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs(id,task_id,provider,model,status,verified,created_at,data_json) VALUES(?,?,?,?,?,?,?,?)",
                       (run.id, run.task_id, run.provider, run.model, run.status, int(run.verified), run.created_at,
                        json.dumps(data, ensure_ascii=False)))

    def add_event(self, event: RunEvent) -> None:
        data = redact(event.metadata)
        encoded = json.dumps(data, ensure_ascii=False, default=str)
        if len(encoded.encode("utf-8")) > 20_000:
            encoded = json.dumps({"truncated": True, "note": "metadata exceeded persistence size cap"})
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO events(event_id,run_id,timestamp,event_type,step,correlation_id,metadata_json) VALUES(?,?,?,?,?,?,?)",
                       (event.event_id, event.run_id, event.timestamp, event.event_type, event.step, event.correlation_id, encoded))

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT data_json FROM runs WHERE id=?", (run_id,)).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        with self.connect() as db:
            rows = db.execute("SELECT data_json FROM runs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [RunRecord.model_validate_json(row[0]) for row in rows]

    def events(self, run_id: str) -> list[RunEvent]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY step,timestamp,event_id", (run_id,)).fetchall()
        return [RunEvent(event_id=row["event_id"], run_id=row["run_id"], timestamp=row["timestamp"],
                         event_type=row["event_type"], step=row["step"], correlation_id=row["correlation_id"],
                         metadata=json.loads(row["metadata_json"])) for row in rows]

    def export_jsonl(self, run_id: str, destination: str | Path) -> Path:
        events = self.events(run_id)
        if not events:
            raise ValueError(f"No events found for run {run_id!r}")
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(event.model_dump_json() + "\n" for event in events), encoding="utf-8")
        return output

    def import_jsonl(self, source: str | Path) -> dict[str, int | list[str]]:
        path = Path(source)
        size = path.stat().st_size
        if size > MAX_IMPORT_BYTES:
            raise ValueError(f"Trace import exceeds {MAX_IMPORT_BYTES} byte limit")
        imported = 0
        rejected: list[str] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                rejected.append(f"line {line_number}: exceeds size limit")
                continue
            try:
                event = RunEvent.model_validate_json(line)
                # Keep imported trace events independent of benchmark run metadata. This prevents
                # a trace fixture from being counted as a model evaluation in history/comparisons.
                self.add_event(event)
                imported += 1
            except Exception as exc:
                rejected.append(f"line {line_number}: {type(exc).__name__}: {exc}")
        return {"imported": imported, "rejected": rejected}

    def delete_run(self, run_id: str) -> bool:
        with self.connect() as db:
            db.execute("PRAGMA foreign_keys=ON")
            event_cursor = db.execute("DELETE FROM events WHERE run_id=?", (run_id,))
            run_cursor = db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            return event_cursor.rowcount > 0 or run_cursor.rowcount > 0


def replay_recorded_tools(events: list[RunEvent]) -> list[dict[str, Any]]:
    """Return persisted tool results in order; no LLM or command is executed."""
    replay = []
    for event in sorted(events, key=lambda item: (item.step, item.timestamp, item.event_id)):
        if event.event_type == "tool.result":
            replay.append({"step": event.step, "correlation_id": event.correlation_id,
                           "tool": event.metadata.get("tool"), "input": event.metadata.get("input"),
                           "output": event.metadata.get("output"), "recorded_replay": True})
    return replay
