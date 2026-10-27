# Development

Install uv and Node.js 24, then run `uv sync --frozen`. `make help` and `task --list` expose the same major targets.

Before opening a PR:

```bash
make lint source-check generated-check test parity
make scenarios
make tools
make ci-native
```

The native suite needs ordinary Unix-socket support. If your sandbox forbids it, retain that limitation and let the GitHub native-engine job run; do not relabel local execution as native execution. CI requires native tests to pass.

Run `make generate` after changing workflow generation. Workflows/config/prompts are deterministic and checked in for review. Keep machine paths, virtualenvs, credentials and generated run results out of commits. Do not edit `vendor/archon/`; a deliberate upstream revision change needs a separately reviewed provenance update.

Tests should exercise decisions, missing evidence, publication identity and failure behavior. CI has no model or forge credentials. Keep live integration changes marked experimental until they have real disposable-repository evidence. Pin tool versions and GitHub Actions commits; update `uv.lock` with dependency changes.

For problems, include the selected variant, fixture, tool versions and relevant log. Do not include credentials or private issue/source data. Report sensitive vulnerabilities through GitHub's private reporting options when available.
