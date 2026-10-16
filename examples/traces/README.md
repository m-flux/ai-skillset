# Trace fixtures

`failed-policy-rejection.jsonl` is an explicitly labelled **illustrative failure fixture**, not a benchmark result. It records a rejected path-traversal patch and an output event for offline inspection/replay. It executes neither a model nor any command.

Try:

```powershell
python -m forgebench.cli replay --input examples/traces/failed-policy-rejection.jsonl
```

The replay should return the recorded `apply_patch` rejection as `recorded_replay: true`.
