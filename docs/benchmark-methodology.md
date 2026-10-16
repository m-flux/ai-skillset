# Benchmark methodology

## Reproducibility

Each task has a stable ID, fixture path, required skill, target source file, timeout, suite version, and tags. Every trial uses a fresh copy of the same fixture. Tests are fixed in the bundled fixture and are never edited by a model patch.

## Metrics

- **Verified success:** the configured tests returned exit code zero and the model's `selected_skill` matches the task's required skill.
- **Test pass rate:** proportion of runs where test exit code is zero, among runs where tests were approved and actually executed.
- **Skill-selection rate:** matching skill selections among responses that included a selection.
- **Latency:** elapsed time reported around the provider call; end-to-end duration also includes copying, tool calls, and tests.
- **Token counts:** sums only for provider-reported counts. `null` means unavailable, not zero.
- **Policy rejections:** attempts rejected by the workspace boundary.
- **Repeat-run agreement:** the larger of verified-pass and verified-fail counts divided by the number of runs for one provider/model group. This is descriptive and not a statistical-significance measure.

## Interpretation cautions

Mock runs only exercise the harness; they are not evidence of real-model quality. Comparisons are meaningful only when models receive equivalent task, fixture, skill, and tool policies. A small number of trials is not enough to claim statistical significance. The MVP does not currently measure memory consumption, GPU utilization, or full patch semantic similarity.
