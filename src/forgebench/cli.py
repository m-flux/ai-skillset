"""Command-line interface for validation, benchmark runs, traces, and reports."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from forgebench import __version__
from forgebench.benchmarks.runner import BenchmarkRunner
from forgebench.config import load_settings
from forgebench.providers.ollama import OllamaProvider
from forgebench.reporting.reports import write_reports, compare_runs
from forgebench.skills.validator import SkillValidator
from forgebench.tracing.store import TraceStore, replay_recorded_tools


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forgebench", description="Local-first AI agent reliability lab")
    parser.add_argument("--version", action="version", version=f"ForgeBench {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-tasks", help="list reproducible built-in benchmark tasks")
    skills = sub.add_parser("skills", help="validate and list skills under a directory")
    skills.add_argument("--skills-root", default="examples/skills")
    val = sub.add_parser("validate-skill", help="validate one Agent Skill directory")
    val.add_argument("skill_dir")
    run = sub.add_parser("run", help="run one task using mock or Ollama provider")
    run.add_argument("--task", required=True)
    run.add_argument("--provider", choices=["mock", "ollama"], default="mock")
    run.add_argument("--model")
    run.add_argument("--approve-tests", action="store_true", help="authorize fixed pytest command inside bundled disposable fixture")
    bench = sub.add_parser("benchmark", help="run repeatable tasks with fresh workspaces")
    bench.add_argument("--tasks", nargs="+", default=["all"])
    bench.add_argument("--provider", choices=["mock", "ollama"], default="mock")
    bench.add_argument("--models", nargs="+")
    bench.add_argument("--repetitions", type=int, default=1)
    bench.add_argument("--approve-tests", action="store_true")
    history = sub.add_parser("history", help="show stored runs")
    history.add_argument("--limit", type=int, default=30)
    events = sub.add_parser("events", help="show events for a run")
    events.add_argument("run_id")
    export = sub.add_parser("export-trace", help="export a run's trace as JSONL")
    export.add_argument("run_id")
    export.add_argument("--output", required=True)
    imp = sub.add_parser("import-trace", help="import and validate a JSONL trace")
    imp.add_argument("--input", required=True)
    replay = sub.add_parser("replay", help="replay recorded tool outputs without executing tools/models")
    replay.add_argument("--input", required=True)
    compare = sub.add_parser("compare", help="compare all stored model runs")
    delete = sub.add_parser("delete-run", help="delete local run metadata and events")
    delete.add_argument("run_id")
    delete.add_argument("--confirm", action="store_true")
    health = sub.add_parser("ollama-health", help="check local Ollama server and installed models")
    health.add_argument("--model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _root()
    settings = load_settings(root)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    store = TraceStore(settings.database_path)
    runner = BenchmarkRunner(root, store, settings.runs_dir, settings.timeout_seconds)
    if args.command == "list-tasks":
        for task in runner.tasks:
            print(f"{task.id}\t{task.required_skill}\t{task.description}")
        return 0
    if args.command == "skills":
        reports = SkillValidator().discover(Path(args.skills_root) if Path(args.skills_root).is_absolute() else root / args.skills_root)
        print(json.dumps([r.model_dump(mode="json", exclude={"instructions"}) for r in reports], indent=2))
        return 0 if all(r.valid for r in reports) else 1
    if args.command == "validate-skill":
        path = Path(args.skill_dir)
        report = SkillValidator().validate(path if path.is_absolute() else root / path)
        print(json.dumps(report.model_dump(mode="json", exclude={"instructions"}), indent=2))
        return 0 if report.valid else 1
    if args.command == "ollama-health":
        try:
            health = OllamaProvider(settings.ollama_url, args.model or settings.ollama_model).health()
            print(json.dumps(health, indent=2))
            if args.model and args.model not in health["models"]:
                print(f"Model {args.model!r} is not listed. Pull it locally before running.", file=sys.stderr)
                return 2
            return 0
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command in {"run", "benchmark"}:
        try:
            if args.command == "run":
                record = runner.run_one(args.task, args.provider, args.model, args.approve_tests, settings.ollama_url)
                runs = [record]
            else:
                task_ids = list(runner.by_id) if args.tasks == ["all"] else args.tasks
                unknown = sorted(set(task_ids) - set(runner.by_id))
                if unknown:
                    raise ValueError(f"Unknown task ids: {', '.join(unknown)}")
                runs = runner.benchmark(task_ids, args.provider, args.models, args.repetitions, args.approve_tests, settings.ollama_url)
            paths = write_reports(runs, settings.reports_dir)
            for record in runs:
                print(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            print(f"Reports: {paths[0]} and {paths[1]}")
            return 0 if all(r.verified for r in runs) else 1
        except Exception as exc:
            print(f"ForgeBench error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    if args.command == "history":
        print(json.dumps([r.model_dump(mode="json") for r in store.list_runs(args.limit)], indent=2))
        return 0
    if args.command == "events":
        print(json.dumps([e.model_dump(mode="json") for e in store.events(args.run_id)], indent=2))
        return 0
    if args.command == "export-trace":
        try:
            path = store.export_jsonl(args.run_id, args.output)
            print(path)
            return 0
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "import-trace":
        try:
            print(json.dumps(store.import_jsonl(args.input), indent=2))
            return 0
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "replay":
        try:
            report = store.import_jsonl(args.input)
            # Imported events are now in local storage; replay only stored tool.result records.
            event_list = []
            for run_id in {e.run_id for e in _read_events(args.input)}:
                event_list.extend(store.events(run_id))
            print(json.dumps({"import": report, "replay": replay_recorded_tools(event_list), "executes_model": False, "executes_commands": False}, indent=2))
            return 0 if not report["rejected"] else 1
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "compare":
        print(json.dumps(compare_runs(store.list_runs(1000)), indent=2))
        return 0
    if args.command == "delete-run":
        if not args.confirm:
            print("Refusing to delete without --confirm", file=sys.stderr)
            return 2
        return 0 if store.delete_run(args.run_id) else 1
    return 2


def _read_events(path: str | Path):
    from forgebench.schemas import RunEvent
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(RunEvent.model_validate_json(line))
            except Exception:
                continue
    return events


if __name__ == "__main__":
    raise SystemExit(main())
