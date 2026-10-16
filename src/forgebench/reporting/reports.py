"""Reports derive all metrics from persisted, actual run records."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from forgebench.schemas import RunRecord
from forgebench.tracing.store import TraceStore


def compare_runs(runs: list[RunRecord]) -> list[dict]:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for run in runs:
        groups[(run.provider, run.model)].append(run)
    result = []
    for (provider, model), group in sorted(groups.items()):
        duration_values = [r.duration_ms for r in group]
        latencies = [r.latency_ms for r in group if r.latency_ms is not None]
        eligible = [r for r in group if r.test_exit_code is not None]
        selected = [r for r in group if r.selected_skill is not None]
        structured = [r for r in group if r.structured_output_valid is not None]
        result.append({
            "provider": provider, "model": model, "runs": len(group),
            "verified_success_rate": round(sum(r.verified for r in group) / len(group), 4) if group else None,
            "test_pass_rate": round(sum(r.test_exit_code == 0 for r in eligible) / len(eligible), 4) if eligible else None,
            "skill_selection_rate": round(sum(r.selected_skill == r.required_skill for r in selected) / len(selected), 4) if selected else None,
            "structured_output_valid_rate": round(sum(bool(r.structured_output_valid) for r in structured) / len(structured), 4) if structured else None,
            "tool_policy_violation_rate": round(sum(r.policy_rejections > 0 for r in group) / len(group), 4) if group else None,
            "median_latency_ms": round(median(latencies)) if latencies else None,
            "median_duration_ms": round(median(duration_values)) if duration_values else None,
            "prompt_tokens_observed": sum(r.prompt_tokens for r in group if r.prompt_tokens is not None) if any(r.prompt_tokens is not None for r in group) else None,
            "completion_tokens_observed": sum(r.completion_tokens for r in group if r.completion_tokens is not None) if any(r.completion_tokens is not None for r in group) else None,
            "policy_rejections": sum(r.policy_rejections for r in group),
            "failures": dict(_count(r.failure_category or "none" for r in group)),
            "repeat_run_agreement": _agreement(group),
        })
    return result


def _count(values):
    from collections import Counter
    return Counter(values)


def _agreement(group: list[RunRecord]) -> float | None:
    if len(group) < 2:
        return None
    statuses = [r.verified for r in group]
    return round(max(statuses.count(True), statuses.count(False)) / len(statuses), 4)


def make_report(runs: list[RunRecord]) -> dict:
    return {
        "suite": "forgebench", "suite_version": "1.0", "run_count": len(runs),
        "verified_successes": sum(r.verified for r in runs),
        "verified_success_rate": round(sum(r.verified for r in runs) / len(runs), 4) if runs else None,
        "failed_verified_runs": sum(r.status == "failed" for r in runs),
        "unverified_runs": sum(r.status == "unverified" for r in runs),
        "model_comparison": compare_runs(runs),
        "runs": [r.model_dump(mode="json") for r in runs],
        "metric_notes": {
            "latency": "Provider response time where the adapter reported it; end-to-end duration includes runtime and tests.",
            "tokens": "Unavailable unless the provider returns token counts; null is not zero.",
            "success": "A run is verified only when the fixed tests pass and the required skill was selected.",
            "significance": "No statistical-significance claim is made.",
            "mock": "Mock provider results validate the harness only and are not evidence of model capability."
        }
    }


def write_reports(runs: list[RunRecord], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = make_report(runs)
    json_path = output_dir / "benchmark-report.json"
    md_path = output_dir / "benchmark-report.md"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = [
        "# ForgeBench benchmark report", "", f"- Runs: {len(runs)}",
        f"- Verified successes: {data['verified_successes']}",
        f"- Failed verified runs: {data['failed_verified_runs']}",
        f"- Unverified runs: {data['unverified_runs']}", "", "## Model comparison", "",
        "| Provider | Model | Runs | Verified success rate | Test pass rate | Median latency (ms) | Policy rejections |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in data["model_comparison"]:
        success = "n/a" if item["verified_success_rate"] is None else f"{item['verified_success_rate'] * 100:.1f}%"
        test = "n/a" if item["test_pass_rate"] is None else f"{item['test_pass_rate'] * 100:.1f}%"
        latency = "n/a" if item["median_latency_ms"] is None else str(item["median_latency_ms"])
        rows.append(f"| {item['provider']} | {item['model']} | {item['runs']} | {success} | {test} | {latency} | {item['policy_rejections']} |")
    rows += ["", "## Runs", "", "| Run ID | Task | Provider/model | Status | Verified | Test exit | Duration (ms) |", "|---|---|---|---|---:|---:|---:|"]
    for run in runs:
        rows.append(f"| `{run.id}` | {run.task_id} | {run.provider}/{run.model} | {run.status} | {'yes' if run.verified else 'no'} | {run.test_exit_code if run.test_exit_code is not None else 'n/a'} | {run.duration_ms} |")
    rows += ["", "> Mock-provider rows demonstrate harness behavior, not real model quality. Success is decided by actual test execution and the required-skill criterion.", ""]
    md_path.write_text("\n".join(rows), encoding="utf-8")
    return json_path, md_path


def runs_from_store(store: TraceStore) -> list[RunRecord]:
    return store.list_runs(limit=1000)
