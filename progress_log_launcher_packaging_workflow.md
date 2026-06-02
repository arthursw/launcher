# Launcher Packaging Workflow Progress

## Initial plan

- Make `packaging/launcher/application.yml` the app-repo default config.
- Add unified `launcher` subcommands: `run`, `init`, `build`, and `release`.
- Expose release operations only as `launcher release ...`.
- Keep launcher executable build artifacts separate from app release artifacts.

## Iteration 1

- Planned: add tests for new config defaults, unified release command dispatch, init generation, and build spec planning.
- Implemented:
  - Added `packaging/launcher/application.yml` runtime and release defaults.
  - Added unified `launcher run`, `launcher init`, `launcher build`, and `launcher release ...` dispatch.
  - Removed the separate release entry point; release operations live under `launcher release ...`.
  - Added `launcher build --spec-only` with generated files under `dist/launcher/`.
  - Updated app-repo workflow docs and examples.
- Learned:
  - `launcher.gui.__init__` imported optional GUI backends eagerly, which broke base `pytest` collection without Textual installed.
  - Generated build artifacts belong under `dist/launcher/`, not under app-owned `packaging/launcher/`.
- Plan changes:
  - Fixed GUI package exports to import optional backends lazily.
  - Generated init trust URLs now infer GitHub owner/repo from the supplied repository when possible.
- Next: review final diffs and handle any review-agent findings.
