# ONI_Autonomous_AI — Phase 4B1 offline inference workspace rules

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
- Phase 4B1 authorizes offline inference IPC, mock transports, budget/schema validation
  and comparison plan/report v2. Preserve the Phase 1–3 APIs and log formats.
- Read-only hardware/runtime inventory and public documentation review are authorized.
  Do not download model/tokenizer artifacts,
  install software, change PC settings/drivers, or create/store API keys.
- Publish only selected hardware specifications. Never commit serials, device UUIDs,
  computer/account names, user-specific paths, private keys, or raw system dumps.
- Estimates are not spending approval. Phase 4B2 model acquisition, runtime setup and
  model execution require their own explicit scope; B2 heldout seeds are plans only.
- Keep Policy worker socket blocking. Only allowlisted count/generate IPC is authorized;
  do not add arbitrary URL/command execution. Unknown exact token counts stop generation.
- Reserve input plus maximum output before each attempt; retain unknown-usage reservations.
  Offline byte-token fixtures and artificial prices are not real LLM measurements or fees.
- Commit local changes after checks; GitHub push requires separate approval.
- Keep actual game adapters and action executors unimplemented until scope is explicitly
  authorized and applicable Steam/Klei conditions are resolved.
- Use Python 3.12, pinned dependencies and uv.lock. Do not commit secrets, tool
  downloads, virtual environments, game data, or generated databases.
- Checks: `.venv/Scripts/python.exe -m pytest`, `.venv/Scripts/ruff.exe check .`,
  `.venv/Scripts/ruff.exe format --check .`.
- Update Japanese design/research documentation when contracts or evidence change.
