# Model Discovery & Refresh — Implementation Plan

## Goal
Always run on the **current generation** of models per provider. Boot-time and on-demand refresh discover new models, smoke-test them, and evict superseded ones. Default ministry members and prime minister auto-promote to successors.

## Decisions (locked in with user)
- Direct provider APIs preferred (OpenRouter as fallback aggregator).
- "Current gen" = within each `(provider, family)` group, keep all models matching the max major version; drop older majors.
- New models discovered must pass a silent smoke-test (`Say OK`, short timeout) before joining the registry.
- Ministry-member and prime-minister defaults auto-swap to successors when their current model is evicted.
- YAML stays human-config (personas, overrides). Discovered registry persists separately.

---

## Phase 1 — Backend discovery layer
- [ ] Create `backend/model_discovery.py`
  - `DiscoveredModel` dataclass: `provider, id, family, tier, version, created, pricing_completion, context_length, source`
  - Provider clients (each returns `list[DiscoveredModel]`):
    - [ ] `discover_openai()` → `GET https://api.openai.com/v1/models`
    - [ ] `discover_anthropic()` → `GET https://api.anthropic.com/v1/models` (header `anthropic-version: 2023-06-01`)
    - [ ] `discover_google()` → `GET https://generativelanguage.googleapis.com/v1beta/models?key=…`
    - [ ] `discover_xai()` → `GET https://api.x.ai/v1/models`
    - [ ] `discover_moonshot()` → `GET https://api.moonshot.ai/v1/models`
    - [ ] `discover_nvidia()` → `GET https://integrate.api.nvidia.com/v1/models`
    - [ ] `discover_openrouter()` → `GET https://openrouter.ai/api/v1/models` (used as fallback + enrichment for pricing/context_length)
  - Each client gracefully no-ops if its API key env var is missing.

## Phase 2 — Family/version parser
- [ ] `backend/model_taxonomy.py`
  - `parse_model(provider, model_id) → (family, tier, version_tuple)`
  - Family rules: `claude`, `gpt`, `gemini`, `grok`, `kimi`, `deepseek`, `llama`, `qwen`, etc.
  - Tier rules: `opus|sonnet|haiku`, `pro|flash|flash-lite`, `reasoning|non-reasoning|fast`, `mini|nano`, …
  - Version: numeric extract (e.g., `claude-opus-4.6` → `(4, 6)`; `gemini-3.1-pro` → `(3, 1)`; `gpt-5.2` → `(5, 2)`).
  - Unknown models: classified as `family=other`, kept across refreshes (never auto-evicted).

## Phase 3 — Generation policy
- [ ] `compute_current_generation(discovered: list[DiscoveredModel]) → KeptSet`
  - Group by `(provider, family)`.
  - Within each group: find `max_major_version`; keep every model whose major matches.
  - Preserves tier diversity (opus/sonnet/haiku all retained when major matches).
  - Returns `{kept: [...], evicted: [...]}` with reasons (`"superseded by {new_id}"`).

## Phase 4 — Smoke test
- [ ] `smoke_test_model(model_id) → bool`
  - Reuses `query_model()` from `openrouter.py` with `timeout=10s`, msg=`Say OK`.
  - Wraps reasoning models in 60s timeout (use existing REASONING_MODELS set).
- [ ] After discovery, run smoke tests in parallel for **new** models only (not already in registry).
- [ ] Models that fail smoke test: omitted from kept set + logged.

## Phase 5 — Registry persistence
- [ ] `data/model_registry.json` — managed by backend.
  - Schema: `{ generated_at, models: [{id, provider, family, tier, version, smoke_tested_at, source}], evicted: [...] }`.
- [ ] `backend/model_registry.py`
  - `load_registry() / save_registry(atomic write via tempfile + rename)`.
  - `merge_with_yaml(yaml_overrides)` — yaml `available_models` entries always retained (manual pins).
- [ ] On boot:
  - If `model_registry.json` missing → run synchronous discovery before serving.
  - Else → fire async background refresh (non-blocking).

## Phase 6 — Default-member succession
- [ ] On eviction of a model that appears in `DEFAULT_MINISTRY_MODELS` or `DEFAULT_PRIME_MINISTER`:
  - Find successor in same `(provider, family, tier)` from kept set; if none, fall back to same `(provider, family)` highest tier.
  - Carry over the persona binding from `DEFAULT_MODEL_PERSONAS` to the successor.
- [ ] Write succession map to registry so `/api/config` returns updated defaults.

## Phase 7 — API surface
- [ ] `POST /api/models/refresh` (auth required)
  - Runs full discovery + smoke + persistence cycle.
  - Returns `{ added: [...], removed: [...], kept: [...], succession: { old_id: new_id, ... }, smoke_failures: [...] }`.
- [ ] `GET /api/models/registry` — current registry contents (for diagnostic UI).
- [ ] Update `GET /api/config` to read from registry instead of static `AVAILABLE_MODELS`.
- [ ] Keep `/api/models/health` working against the live registry.

## Phase 8 — Configuration
- [ ] Extend `ministry_config.yaml`:
  ```yaml
  discovery:
    enabled: true
    boot_refresh: async   # sync | async | off
    providers:
      openai:    { enabled: true, api_key_env: OPENAI_API_KEY,    base_url: https://api.openai.com/v1 }
      anthropic: { enabled: true, api_key_env: ANTHROPIC_API_KEY, base_url: https://api.anthropic.com/v1 }
      google:    { enabled: true, api_key_env: GOOGLE_API_KEY,    base_url: https://generativelanguage.googleapis.com/v1beta }
      xai:       { enabled: true, api_key_env: XAI_API_KEY,       base_url: https://api.x.ai/v1 }
      moonshot:  { enabled: true, api_key_env: MOONSHOT_API_KEY,  base_url: https://api.moonshot.ai/v1 }
      nvidia:    { enabled: true, api_key_env: NVIDIA_API_KEY,    base_url: https://integrate.api.nvidia.com/v1 }
      openrouter:{ enabled: true, api_key_env: LLM_API_KEY,       base_url: https://openrouter.ai/api/v1, role: enrichment }
    smoke_test:
      timeout_seconds: 10
      reasoning_timeout_seconds: 60
  available_models_overrides: []   # never auto-evicted, always merged in
  ```

## Phase 9 — Frontend
- [ ] `ModelConfig.jsx`
  - Add **REFRESH** button next to "Check Health".
  - Calls `api.refreshModels()` (new method in `api.js`).
  - Shows spinner; on completion renders a diff panel:
    - ➕ Added (with smoke-test ✓)
    - ➖ Removed (superseded by …)
    - ↻ Defaults updated (old → new)
  - Reload `/api/config` after refresh.
- [ ] Add `api.refreshModels()` and `api.getModelRegistry()` to `frontend/src/api.js`.

## Phase 10 — Verification
- [ ] Manual: hit `POST /api/models/refresh` with at least 2 provider keys set; confirm new models appear, old majors get evicted.
- [ ] Manual: temporarily revoke one provider key; confirm refresh skips that provider gracefully.
- [ ] Manual: in UI, click REFRESH after planting a stale model in registry; confirm diff panel renders.
- [ ] Boot test: delete `model_registry.json`, restart backend, confirm sync discovery populates it before first request succeeds.
- [ ] Smoke-test failure path: temporarily inject a fake model ID; confirm it's logged + excluded from registry.

---

## Out of scope (call out before building)
- Cost-based ranking beyond what's needed for current-gen detection (we keep all current-gen, not "top-N by price").
- Auto-rebinding **user-customized** ministry configs in the UI; we only swap server-side defaults.
- Background scheduled refresh (cron). Refresh is boot + manual button only.

## Open items needing your sign-off before I start
1. **Boot refresh mode** — `async` (non-blocking, current registry served until done) is my default. ✅ confirmed
2. **`model_registry.json` location** — `data/model_registry.json` alongside the SQLite DB. ✅ confirmed
3. **Smoke test budget** — no cap. ✅ confirmed
4. **Family classifier** — regex/lookup table; unknowns exempt from eviction. ✅ confirmed

---

## Review (post-implementation)

### Files added
- `backend/model_taxonomy.py` — parse `provider/model` → `(family, tier, version_tuple)` with regex tables. `family='other'` is exempt from eviction.
- `backend/model_discovery.py` — async clients for OpenAI, Anthropic, Google, xAI, Moonshot, NVIDIA, OpenRouter (enrichment). Each no-ops when its `api_key_env` is unset.
- `backend/model_registry.py` — generation policy, succession, atomic JSON persistence to `data/model_registry.json`.
- `backend/model_refresh.py` — orchestrator: discover → dedupe → policy → smoke-test new only → save → diff.
- `tasks/todo.md` — this plan.

### Files modified
- `backend/config.py` — added `DISCOVERY_CONFIG` block.
- `backend/main.py` — startup hook (sync if no registry, async otherwise), `POST /api/models/refresh`, `GET /api/models/registry`. `/api/config` and `/api/models/health` now read the live registry.
- `ministry_config.yaml` — added `discovery:` section + `available_models_overrides: []`.
- `frontend/src/api.js` — `refreshModels()`, `getModelRegistry()`.
- `frontend/src/components/ModelConfig.jsx` — REFRESH button + diff panel.
- `frontend/src/components/ModelConfig.css` — styles for the new button + diff panel.

### Generation policy refinement made during build
Initially planned per-(provider, family) max-major. Changed to per-(provider, family, tier) max-version after test caught that `claude-opus-4` was being kept alongside `claude-opus-4.6`. Per-tier grouping correctly evicts the older opus while still preserving sonnet/haiku at independent versions.

### Verification
- Taxonomy parser hand-tested across all 24 model IDs in current YAML. All parse correctly.
- Generation policy + succession unit-tested with 16 mixed-generation models including current-gen + superseded.
- Registry JSON round-trip works (atomic write + reload).
- All modules import cleanly. FastAPI registers `/api/models/refresh` + `/api/models/registry`.

### Not done (deferred / out of scope)
- LiteLLM proxy reachability of newly-discovered models is **not** auto-synced — if `LLM_API_URL` points at LiteLLM, smoke tests will fail for models not in `litellm_config.yaml`. Those failures will appear in the diff and the model is excluded (graceful degradation; user can update LiteLLM config + re-refresh).
- No background scheduled refresh — boot + manual button only as agreed.
- No write-back to `ministry_config.yaml` (registry is JSON-side; YAML stays human-config).

---

## Restart-2 review (post-fix verification)

After applying the boot-crash fixes, restart succeeded. Registry populated cleanly:
- **16 current-gen models kept** across openai, anthropic, google, xai, moonshot, nvidia
- **131 evicted as superseded**
- **35 smoke failures** (mostly LiteLLM proxy not knowing newly-discovered IDs — expected)
- **2 succession events** triggered for default ministry members

### Known issues surfaced by real data — TODO next session

1. **Substring tier matching collides reasoning vs non-reasoning.**
   `xai/grok-4.20-0309-non-reasoning` and `xai/grok-4.20-0309-reasoning` both parse to `tier=reasoning` because the regex matches "reasoning" as substring inside "non-reasoning". They get grouped together and the wrong one wins succession.
   **Fix**: in `model_taxonomy.py::_TIER_PATTERNS`, add `non-reasoning` BEFORE `reasoning` so the more-specific pattern wins. Also consider adding `non-thinking`, `non-fast`, etc. as preventive measures.

2. **Succession picks wrong tier when no exact match exists.**
   `openai/gpt-5.2` (tier="") got promoted to `openai/gpt-5.4-nano` (tier="nano") because `find_successor()`'s fallback to "same provider+family at any tier" picked the only gpt-5 option available. But tier="" → tier="nano" is a meaningful downgrade.
   **Fix options**: (a) leave `find_successor` returning None when no same-tier match → keep the original ID; (b) only allow succession when the tier change is "upgrade-shaped" (e.g. "" → "" or "" → "pro").

3. **`google/gemini-3.1-pro-preview-customtools` kept as separate model.**
   Tier classification doesn't strip the `-customtools` suffix, so it ends up in a sole-member group `(google, gemini, pro)` alongside `gemini-3.1-pro-preview` (also tier=pro). Then both are kept as max-version of their group. They're distinct groups because one has variants in the ID. Wait — actually both have tier=pro, so they should collide. Need to double-check what's happening.
   **Fix**: probably treat `-customtools`, `-preview`, `-experimental`, etc. as variant suffixes that don't affect tier grouping.

4. **`gpt-3.5-turbo-instruct` kept as sole member of its tier group.**
   tier="instruct" → no other gpt-instruct exists → kept. But it's clearly legacy.
   **Fix options**: blacklist some legacy tiers; or apply a max-age rule (drop if `created` is more than N years old).

---

## Restart-3 review (post-polish fixes, 2026-05-06)

All 4 issues from Restart-2 fixed plus a date-suffix bug surfaced during live verification.

### Files modified
- `backend/model_taxonomy.py`
  - `_TIER_PATTERNS`: added `non-reasoning`, `non-thinking`, `non-fast` BEFORE their positive forms (Fix #1).
  - `_detect_version`: strips date suffixes (`-YYYY-MM-DD`, `-\d{6,}`) before pattern matching, so `gpt-audio-mini-2025-10-06` no longer parses as version (2025, …).
- `backend/model_registry.py`
  - `find_successor`: dropped same-(provider, family) fallback. Returns None when no exact tier match exists (Fix #2).
  - `_canonical_id` + `_dedupe_variants`: collapse `-customtools/-experimental/-with-thinking/-with-search` variants within survivor groups (Fix #3).
  - `_drop_legacy_majors`: per-family max-major filter, drops non-pinned models lagging by ≥ 2 majors (Fix #4).
- `tests/test_model_taxonomy.py`, `tests/test_model_registry.py` — 18 new unit tests, all passing.

### Live-data verification (against 147 models in `data/model_registry.json`)
- 16 → 30 kept (more current-gen surfaced once date-bug stopped hiding them).
- `xai/grok-4.20-0309-non-reasoning` and `…-reasoning` now in distinct tier groups.
- `google/gemini-3.1-pro-preview-customtools` evicted with reason "variant of `…-pro-preview`".
- `openai/gpt-3.5-turbo-instruct` evicted with reason "legacy: openai/gpt current major is 5".
- All gpt-5.x variants (mini, nano, pro, chat, …) correctly retained.

### Pre-existing issues unrelated to this PR
- `tests/test_config.py::TestLLMApiKeyValidation` has 2 pre-existing failures (verified by stashing my changes). Out of scope.
- `openai/gpt-5.4-mini` and `…-mini-2026-03-17` both kept — date-suffix dedupe within survivor groups not yet implemented (out of scope; would extend `_VARIANT_SUFFIXES` semantics).
- `moonshot/` vs `moonshotai/` (same model, two providers) both kept — cross-provider dedupe out of scope.
