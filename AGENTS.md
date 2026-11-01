# ONI_Autonomous_AI — offline Phase 3 workspace rules

- Work only in this independent repository. Do not change ONI, its MOD directories,
  existing saves, Steam settings, or other projects.
- Keep runtime and tests offline. No live game connections or live game action execution,
  unattended real-game play, server startup, .NET/Rust installation, or unapproved publishing.
- Preserve UNKNOWN, source revision, verification status, game version and DLC scope.
  Documentation examples are not verified game statistics.
- Synthetic-only actions and evaluation are authorized. Do not implement a fixed
  strategy or silently treat synthetic parameters as actual ONI statistics.
- Autonomous synthetic episodes with a replaceable test Policy are authorized. Do not
  send fixture labels to the Policy or call external LLM APIs/paid services.
- Paired Policy comparisons, exact structured claims and spawned worker time limits are
  authorized. Freeze source/settings before heldout evaluation; do not tune on its results.
- Model adapters are design/mock only. No model service startup, installation or API calls.
- Keep actual game adapters and action executors unimplemented until scope is explicitly
  authorized and applicable Steam/Klei conditions are resolved.
- Use Python 3.12, pinned dependencies and uv.lock. Do not commit secrets, tool
  downloads, virtual environments, game data, or generated databases.
- Checks: `.venv/Scripts/python.exe -m pytest`, `.venv/Scripts/ruff.exe check .`,
  `.venv/Scripts/ruff.exe format --check .`.
- Update Japanese design/research documentation when contracts or evidence change.
