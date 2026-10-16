"""Optional Streamlit dashboard; data comes from ForgeBench's local SQLite store."""
from __future__ import annotations
from pathlib import Path
import json


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise SystemExit("Dashboard dependency missing. Install with: python -m pip install -e '.[dashboard]'") from exc
    from forgebench.config import load_settings
    from forgebench.tracing.store import TraceStore, replay_recorded_tools
    from forgebench.skills.validator import SkillValidator
    from forgebench.benchmarks.runner import BenchmarkRunner
    from forgebench.reporting.reports import compare_runs, write_reports

    root = Path(__file__).resolve().parent
    settings = load_settings(root)
    store = TraceStore(settings.database_path)
    runner = BenchmarkRunner(root, store, settings.runs_dir, settings.timeout_seconds)
    st.set_page_config(page_title="ForgeBench", page_icon="🧪", layout="wide")
    st.title("ForgeBench")
    st.caption("Local-first reliability lab for open-weight coding agents")
    pages = ["Overview", "Skills", "Benchmark runner", "Trace inspector", "Model comparison", "Configuration"]
    page = st.sidebar.radio("Workspace", pages)
    runs = store.list_runs(1000)

    if page == "Overview":
        a, b, c, d = st.columns(4)
        a.metric("Stored runs", len(runs))
        b.metric("Verified successes", sum(r.verified for r in runs))
        c.metric("Failed runs", sum(r.status in ("failed", "error") for r in runs))
        c2 = sum(r.status == "unverified" for r in runs)
        d.metric("Unverified", c2)
        st.subheader("System readiness")
        st.write(f"Project version: `0.1.0`")
        st.write(f"Database: `{settings.database_path}`")
        try:
            health = runner.make_provider("ollama", settings.ollama_model, settings.ollama_url).health()
            st.success(f"Ollama reachable · {len(health['models'])} model(s) listed")
            if settings.ollama_model not in health["models"]:
                st.warning(f"Configured model `{settings.ollama_model}` is not installed. Pull it in Ollama or change configuration.")
        except Exception as exc:
            st.warning(f"Ollama unavailable: {exc}. Use the mock provider for harness smoke tests, or start Ollama and install a model.")
        if not runs:
            st.info("No results yet. Run a benchmark to populate history and comparisons. Mock results are labelled and do not measure model quality.")
        else:
            st.dataframe([r.model_dump(mode="json", include={"id", "task_id", "provider", "model", "status", "verified", "duration_ms", "failure_category"}) for r in runs], use_container_width=True)
    elif page == "Skills":
        root_in = st.text_input("Skills directory", str(root / "examples" / "skills"))
        if st.button("Validate discovered skills"):
            reports = SkillValidator().discover(root_in)
            st.json([r.model_dump(mode="json", exclude={"instructions"}) for r in reports])
        one = st.text_input("Or validate one skill directory", "")
        if st.button("Validate one skill") and one.strip():
            st.json(SkillValidator().validate(one).model_dump(mode="json", exclude={"instructions"}))
    elif page == "Benchmark runner":
        task_ids = [t.id for t in runner.tasks]
        selected = st.multiselect("Tasks", task_ids, default=task_ids)
        provider = st.selectbox("Provider", ["mock", "ollama"])
        model = st.text_input("Ollama model tag", settings.ollama_model, disabled=(provider == "mock"))
        repetitions = st.number_input("Repetitions per task/model", min_value=1, max_value=10, value=1)
        approved = st.checkbox("Approve fixed pytest verification in disposable bundled fixtures")
        if st.button("Run benchmark", disabled=not selected or (provider == "ollama" and not model.strip())):
            with st.spinner("Running verified tasks..."):
                results = runner.benchmark(selected, provider, [model] if provider == "ollama" else None, int(repetitions), approved, settings.ollama_url)
                paths = write_reports(results, settings.reports_dir)
            st.success(f"Finished {len(results)} run(s). Reports saved to {paths[0]} and {paths[1]}.")
            st.dataframe([r.model_dump(mode="json") for r in results], use_container_width=True)
    elif page == "Trace inspector":
        if not runs:
            st.info("No stored runs yet.")
        else:
            run_id = st.selectbox("Run", [r.id for r in runs])
            chosen = store.get_run(run_id)
            st.json(chosen.model_dump(mode="json") if chosen else {})
            events = store.events(run_id)
            st.dataframe([e.model_dump(mode="json") for e in events], use_container_width=True)
            st.subheader("Recorded tool-output replay")
            st.caption("Reads saved tool.result outputs only; it does not call the model or run commands.")
            st.json(replay_recorded_tools(events))
            if st.button("Export selected trace"):
                output = settings.reports_dir / f"{run_id}.jsonl"
                store.export_jsonl(run_id, output)
                st.success(f"Trace exported to {output}")
    elif page == "Model comparison":
        if not runs:
            st.info("No benchmark data yet. Comparisons will appear after runs are stored.")
        else:
            st.dataframe(compare_runs(runs), use_container_width=True)
            st.caption("Rates come from actual stored runs. Token metrics are unavailable where the provider reports none. No significance claim is made.")
    elif page == "Configuration":
        st.json({"provider_default": settings.provider, "ollama_url": settings.ollama_url,
                 "ollama_model": settings.ollama_model, "database_path": str(settings.database_path),
                 "runs_dir": str(settings.runs_dir), "reports_dir": str(settings.reports_dir),
                 "timeout_seconds": settings.timeout_seconds})
        st.warning("Workspace path rules and command allowlists are application-level controls, not a complete OS sandbox. Review untrusted fixture tests before execution.")


if __name__ == "__main__":
    main()
