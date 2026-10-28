# Upstream attribution

This project includes source and prompt material from **coleam00/Archon**, pinned to commit `72817c50dc51bb91773f71e5448bb7d387bfc8dd`.

- Repository: https://github.com/coleam00/Archon
- Original files: `vendor/archon/.archon/workflows/sdlc/`
- Original license: `vendor/archon/LICENSE` (MIT; original copyright notice retained)
- Prompt copies and generated schemas in this repository are derived from those files.
- `SOURCE.json` records the upstream paths and SHA-256 hashes.

The port reuses the original round-decision, outcome and reporting scripts. Its bulk parity test replaces only the reducer's io import in memory; it does not modify the vendored source.

DAGU, Bun and go-task/Task are external tools downloaded from their official releases. Their binaries are not redistributed or committed here; their own licenses apply. This repository is not affiliated with or endorsed by those projects.

The complete pinned SDLC source pack is retained to preserve relative imports and provenance. Unported upstream workflows remain reference material. Port entrypoints under `workflows/` cover only simple and detailed live delivery; `archon-round.yaml` is the required internal child of detailed delivery. Other upstream workflows in the source pack are reference material, not supported DAGU entrypoints.
