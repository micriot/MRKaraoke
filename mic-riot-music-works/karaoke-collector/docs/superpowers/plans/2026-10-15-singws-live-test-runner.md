# SingWS Live Test Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone macOS companion that verifies a SingWS show setup and runs explicitly approved, measured Mic Riot test scenarios.

**Architecture:** A PyQt6 desktop application owns persisted run state and a strict preflight gate. Adapters isolate the real Mic Riot request API, local SingWS observation/control, audio/display inspection, and local evidence capture; the coordinator can advance only after explicit operator confirmation.

**Tech Stack:** Python 3.14, PyQt6, pytest, SQLite, platform-native macOS audio/display inspection, HTTP client, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-14-singws-live-test-runner-design.md`

## Global Constraints

- Ship as a separate macOS app; opening SingWS alone must not change its behavior.
- Never submit requests or control SingWS until the operator confirms the completed **Test Run Ready** preflight.
- Use only the explicitly configured Mic Riot tenant; credentials stay in memory and are redacted from all persisted output.
- Generate only unique `FirstName Test` requests and never duplicate a song within a run.
- Live Test requests are paced no faster than one per second and use an initial batch of 10, replenishing by 10 once eight from a batch complete and two remain.
- Pre-Show Check performs local-library → KaraFun → local-library fast-forward checkpoints in about five minutes.
- Test-app audio uses Mac built-in speakers only; never silently change SingWS or system output routing.
- Preserve and report individual failures; stop only for safety/tenant/authentication violations, explicit Stop, or an unrecoverable missing prerequisite.

## Review Focus

- Credentials accidentally appearing in a report, screenshot filename, exception, or debug log must be redacted; cover in Task 3.
- A valid response from a wrong Mic Riot tenant must block before submission; cover in Task 4.
- A song or queue item that merely resembles a test request must never be controlled as if it belonged to this run; cover in Task 5.
- A missing physical display must still render the external-screen mock; cover in Task 6.
- An external headphone route must be reported and block Pre-Show playback without rerouting SingWS; cover in Task 6.

---

## File Structure

```text
singws_live_test_runner/
  app.py                         # PyQt bootstrap and dependency wiring
  domain.py                      # Typed run state, records, results, failures
  storage.py                     # SQLite persistence and report snapshots
  config.py                      # Keychain-backed config references and validation
  preflight.py                   # Deterministic readiness checks and confirmation model
  api.py                         # Mic Riot request/status adapter
  scenario.py                    # Seeded names, unique-song selection, batch scheduler
  singws_bridge.py               # Scoped local SingWS observer/controller interface
  diagnostics.py                 # Audio route, drive, display mock, media evidence
  coordinator.py                 # State machine and resilient run orchestration
  scoring.py                     # Baseline comparison and explainable 1–10 scores
  ui/
    main_window.py               # Run setup, ready prompt, live console, report tabs
    external_mock.py             # Rotation/show external-display mock
  reports.py                     # JSON and HTML exports
tests/
  test_domain.py
  test_config_preflight.py
  test_api.py
  test_scenario.py
  test_diagnostics.py
  test_coordinator.py
  test_scoring_reports.py
```

### Task 1: App Foundation and Persisted Run Model

**Files:**
- Create: `pyproject.toml`, `singws_live_test_runner/__init__.py`, `singws_live_test_runner/domain.py`, `singws_live_test_runner/storage.py`, `singws_live_test_runner/app.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Produces: `RunMode`, `RunState`, `TestRequest`, `ObservedEvent`, `SongResult`, `RunRecord`, and `RunStore` for all later tasks.

- [ ] **Step 1: Write failing domain tests**

Test legal state transitions, immutable event append behavior, and persistence/reload of a partial run.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_domain.py -v`
Expected: FAIL because the package and domain interfaces do not exist.

- [ ] **Step 3: Implement the typed domain model and SQLite store**

Define `RunState` as `DRAFT`, `PREFLIGHT`, `READY`, `RUNNING`, `STOPPING`, `COMPLETED`, `FAILED`; expose `RunStore.create_run`, `append_event`, `save_result`, and `load_run`.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_domain.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml singws_live_test_runner tests/test_domain.py
git commit -m "feat: add test-runner domain model"
```

### Task 2: Configuration, Redaction, and Explicit Preflight Gate

**Files:**
- Create: `singws_live_test_runner/config.py`, `singws_live_test_runner/preflight.py`
- Test: `tests/test_config_preflight.py`

**Interfaces:**
- Consumes: `RunRecord`, `RunState`, `RunStore`.
- Produces: `RunConfiguration`, `PreflightCheck`, `PreflightResult`, `Redactor`, and `PreflightService.evaluate(config) -> PreflightResult`.

- [ ] **Step 1: Write failing preflight and redaction tests**

Test that a tenant, credential, count, pace, baseline song, and required host name are validated; assert a secret cannot appear in serialized events or exception text; assert no preflight result can start a run without a separate confirmation call.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_config_preflight.py -v`
Expected: FAIL because configuration and preflight services do not exist.

- [ ] **Step 3: Implement configuration and the confirmation boundary**

Store credential references in macOS Keychain, not SQLite. Implement `PreflightService.confirm_ready(result, confirmation_text)` so only exact `OK, Start Test Run` changes a ready run to runnable.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_config_preflight.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add singws_live_test_runner/config.py singws_live_test_runner/preflight.py tests/test_config_preflight.py
git commit -m "feat: add protected test preflight"
```

### Task 3: Read-Only Mic Riot Contract Discovery and API Adapter

**Files:**
- Create: `singws_live_test_runner/api.py`, `tests/fixtures/micriot/`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `RunConfiguration`, `Redactor`.
- Produces: `MicRiotClient.verify_tenant()`, `songbook()`, `create_request(request)`, and `request_status(request_id)`.

- [ ] **Step 1: Capture a redacted, read-only contract fixture**

Inspect the configured Mic Riot service using only safe tenant/songbook/status reads and save sanitized examples under `tests/fixtures/micriot/`; do not create a request in this step.

- [ ] **Step 2: Write failing adapter tests from the fixture**

Assert endpoint/schema validation, wrong-tenant rejection, request correlation-ID handling, rate limiting, and redaction of HTTP errors.

- [ ] **Step 3: Run the focused test to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL because `MicRiotClient` does not exist.

- [ ] **Step 4: Implement the adapter with a confirmed endpoint allowlist**

Only enable `create_request` after `verify_tenant` matches the configured tenant and the preflight confirmation has been recorded. Enforce a one-second minimum between submissions.

- [ ] **Step 5: Run the focused test to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add singws_live_test_runner/api.py tests/test_api.py tests/fixtures/micriot
git commit -m "feat: add verified Mic Riot adapter"
```

### Task 4: Scenario Generator and Rolling Batch Scheduler

**Files:**
- Create: `singws_live_test_runner/scenario.py`
- Test: `tests/test_scenario.py`

**Interfaces:**
- Consumes: songbook data and `RunConfiguration`.
- Produces: `ScenarioGenerator.build(seed, count, songs) -> list[TestRequest]` and `BatchScheduler.next_batch(run) -> list[TestRequest]`.

- [ ] **Step 1: Write failing scenario tests**

Assert 1–100 unique `FirstName Test` names, no duplicate song IDs, unambiguous `SC – Neon Moon – Brooks & Dunn` lookup, initial batches of 10, and replenishment only after eight completions with two pending.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_scenario.py -v`
Expected: FAIL because the generator and scheduler do not exist.

- [ ] **Step 3: Implement deterministic manifest generation and rolling batches**

Persist the random seed and manifest before any submission. Make completion counting depend only on this run’s correlated request IDs.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_scenario.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add singws_live_test_runner/scenario.py tests/test_scenario.py
git commit -m "feat: add unique scenarios and rolling batches"
```

### Task 5: SingWS Observation, Audio/Display Diagnostics, and Pre-Show Sequence

**Files:**
- Create: `singws_live_test_runner/singws_bridge.py`, `singws_live_test_runner/diagnostics.py`, `singws_live_test_runner/ui/external_mock.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `TestRequest`, `ObservedEvent`, and `PreflightResult`.
- Produces: `SingWSBridge.observe()`, `drive_checkpoint()`, `AudioRouteInspector.inspect()`, `DisplayMock.render(state)`, and `PreShowScenario.checkpoints()`.

- [ ] **Step 1: Write failing diagnostic and pre-show tests**

Test built-in-speaker success, external-headphone blocking without device mutation, absent physical display with functional mock, missing media-drive warning, and exact local → KaraFun → local fast-forward checkpoint order.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_diagnostics.py -v`
Expected: FAIL because bridge and diagnostics interfaces do not exist.

- [ ] **Step 3: Implement scoped local observation/control adapters**

First prefer documented local SingWS signals; use accessibility only for explicitly named host actions. Add device/display inspection without changing routes and a local mock that renders rotation and show states.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_diagnostics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add singws_live_test_runner/singws_bridge.py singws_live_test_runner/diagnostics.py singws_live_test_runner/ui/external_mock.py tests/test_diagnostics.py
git commit -m "feat: add SingWS diagnostics and pre-show checks"
```

### Task 6: Coordinator, Evidence Collection, and Resilient Continuation

**Files:**
- Create: `singws_live_test_runner/coordinator.py`, `singws_live_test_runner/scoring.py`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `MicRiotClient`, `BatchScheduler`, `SingWSBridge`, `RunStore`.
- Produces: `RunCoordinator.start`, `stop`, `record_observation`, and `advance` plus `ScoringEngine.score(result, baseline)`.

- [ ] **Step 1: Write failing coordinator tests**

Test no submit before confirmation, request-to-queue matching, individual failure continuation, stop behavior, safety-stop behavior, silence bands, black-frame and stalled-frame annotations, and queued batch replenishment.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_coordinator.py -v`
Expected: FAIL because the coordinator does not exist.

- [ ] **Step 3: Implement the state machine and evidence collector**

Use a monotonic clock. Collect local audio-energy/frame-state evidence, classify silence under 250 ms as informational, 250–999 ms as warning, and at least 1 second as failure. Keep running after song failures whenever later tests remain viable.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_coordinator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add singws_live_test_runner/coordinator.py singws_live_test_runner/scoring.py tests/test_coordinator.py
git commit -m "feat: orchestrate resilient measured test runs"
```

### Task 7: Mic Riot-Style Desktop UI and Reports

**Files:**
- Create: `singws_live_test_runner/ui/main_window.py`, `singws_live_test_runner/reports.py`
- Modify: `singws_live_test_runner/app.py`
- Test: `tests/test_scoring_reports.py`

**Interfaces:**
- Consumes: `PreflightResult`, `RunCoordinator`, `SongResult`, `RunStore`.
- Produces: `MainWindow`, `ReportExporter.export_json`, and `ReportExporter.export_html`.

- [ ] **Step 1: Write failing UI-model and report tests**

Assert the preflight prompt lists tenant, request count, route, drive, display, and warnings; verify only the explicit confirmation enables Start; assert reports include automatic/manual 1–10 scores, timings, anomalies, and redacted evidence.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_scoring_reports.py -v`
Expected: FAIL because the UI and exporter do not exist.

- [ ] **Step 3: Implement the separate companion UI and export views**

Use a dark Mic Riot-style console with a prominent `TEST RUNNER` label. Provide mode selection, editable count, ready prompt, rolling-batch status, evidence timeline, Stop, external-screen mock, and export actions.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_scoring_reports.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add singws_live_test_runner/ui singws_live_test_runner/app.py singws_live_test_runner/reports.py tests/test_scoring_reports.py
git commit -m "feat: add test runner console and reports"
```

### Task 8: End-to-End Gates and macOS Packaging

**Files:**
- Create: `scripts/package_macos.sh`, `scripts/verify_release.py`, `README.md`
- Modify: `pyproject.toml`
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: completed app, configuration template, and packaged bundle.
- Produces: a signed-or-clearly-unsigned standalone `.app` and release verification report.

- [ ] **Step 1: Write failing end-to-end tests**

Test the two-singer authorized smoke path using a fixture API/bridge, the five-minute pre-show sequence, no automatic run when SingWS opens alone, and a Test Runner-first Ready prompt after a host session becomes available.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_end_to_end.py -v`
Expected: FAIL because package verification does not exist.

- [ ] **Step 3: Implement packaging and release checks**

Package without embedded credentials. Verify the bundle launches, imports its adapters, creates a fresh local database, and describes the mandatory two-singer live smoke gate before permitting a larger production test.

- [ ] **Step 4: Run all automated tests and release checks**

Run: `pytest -v && python scripts/verify_release.py`
Expected: PASS with all test modules green and a verified local app bundle.

- [ ] **Step 5: Perform the authorized two-singer live smoke gate**

Confirm the current tenant/schema, correlation, SingWS observation, BGM/karaoke transition capture, and report export before enabling a 10+ song live run.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml scripts README.md tests/test_end_to_end.py
git commit -m "build: package and verify SingWS test runner"
```

## Plan Self-Review

- **Coverage:** Tasks 1–8 cover state/persistence, safe preflight, API contract, batching, host/audio/display behavior, measurement/scoring, UI/reports, and distribution gates.
- **Type consistency:** `TestRequest`, `ObservedEvent`, `SongResult`, `RunConfiguration`, `PreflightResult`, and `RunCoordinator` are defined before their consumers.
- **Review focus mapping:** redaction → Task 2; tenant mismatch → Task 3; request ownership → Task 4/6; display mock → Task 5; audio-route safety → Task 5.
- **Scope:** API shape and SingWS local controls remain discovery-gated in Tasks 3 and 5; implementation may not guess either contract.
