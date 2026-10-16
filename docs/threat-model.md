# Threat model and safety boundary

## Assets to protect

- Files outside the designated disposable workspace.
- Credentials, local environment settings, private keys, and user source repositories.
- Test integrity and benchmark records.
- Trace metadata that may accidentally include secrets.

## Untrusted input

Task descriptions, skill instructions, source files, model responses, imported JSONL traces, and test code are treated as untrusted. A prompt in a repository cannot grant the model additional tools.

## Implemented controls

- Model output must satisfy a strict Pydantic schema before patch handling.
- Paths are relative and traversal, drive-qualified paths, symlink targets, protected files, and test edits are rejected.
- Patches use one exact existing anchor and source is Python syntax-checked before writing.
- No model-provided shell command is accepted. Test invocation is a fixed argv with `shell=False`, timeout, and output caps.
- Test execution requires explicit user approval and only targets bundled sample fixtures in the CLI benchmark path.
- Trace events are size-limited and common token/password patterns are redacted before persistence.
- JSONL trace imports have total-size and per-line limits and validate every event.

## Residual risks

These are application-level controls, **not a complete operating-system sandbox**. A Python test file can still execute code with the current user's privileges. Do not run untrusted external repositories or arbitrary user-provided fixtures without stronger isolation, such as a properly configured container or VM. `--approve-tests` is explicit consent, not a proof that test code is safe. A compromised local model server or malicious dependencies are outside the current boundary.

## Future hardening

- Container-backed execution with read-only source mounts and constrained network access.
- Cross-platform process resource limits.
- Broader and tested secret-redaction rules.
- Cancellation and explicit trace retention policy.
- Signed, versioned benchmark fixture manifests.
