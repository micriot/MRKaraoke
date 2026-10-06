# Safe Library Auditor v0.1 implementation plan

Goal: a runnable local-only auditor, with crash-safe scan discovery and real media checks, preserving every original.

Spec: ../../Phase-0-Discovery-and-Design.md and the user's master build prompt. Latest steering removes all Spotify/Apple/provider integration; later playlist recommendations use only local music. Execute directly in this isolated new repository; no edits to Sing WS or user media.

Architecture: Python standard library processing engine, SQLite per project, bounded two-worker pool and a lightweight code-native local browser UI. No frontend package install or cloud service. Runtime bind only to 127.0.0.1; protect mutations by token and same-origin checks. Generated concept is a visual reference only, never a product screenshot or fake scan result.

Global constraints: AUDIT ONLY; no repairs; no automatic full master scan; never declare READY; hashes and stage results persist; source paths cannot overlap application/project storage; preserve customer isolation; canonical separator is ASCII ` - `; disk IDs and identity are never invented.

Review focus: interrupted directory enumeration; hidden/unsafe archive members; inaccessible/disconnected sources; stale companion evidence; hostile filename/CSV text. Add direct tests for each.

Task 1 — Durable project/database and job queues.
Files: auditor/store.py, auditor/jobs.py, tests/test_jobs.py.
Interfaces: create_project(root, name), Project(path), new_job(sources), snapshot(), discover_step(cancel), audit_file(file_id, cancel), run(cancel, workers=2).
Write/run failing tests for project isolation, source overlap, stop/resume, completed-directory preservation and stale-worker recovery. Implement SQLite WAL, explicit transactions, per-directory queue, per-file stage JSON, bounded batched discovery. Verify unchanged resumes do no repeated analysis; test crash recovery in real subprocesses.

Task 2 — Read-only media audit.
Files: auditor/media.py, auditor/singws.py, tests/test_media.py.
Interfaces: hash_file(path, cancel), signature(path), filename(path, kind, naming), archive(path, cancel), audio(path, cancel), cdg(path, cancel), compatibility(path, project_settings).
Write/run failing tests for valid/corrupt media, UTF-8/legacy names, unknown fields, mismatched/missing components, zero bytes, unsupported/unsafe ZIPs and sample CDG instructions. Implement bounded streaming reads and cancellable full FFmpeg audio decode; source-derived Sing WS AST oracle with digest/version evidence. Persist completed stages immediately; cache audio/CDG by hash plus tool version. Test changed companion invalidation.

Task 3 — Local server and UI.
Files: auditor/server.py, auditor/ui.html, launch.py, Start Auditor.command, tests/test_server.py.
Write/run failing API tests for isolated projects, live snapshot, report export and denied cross-origin/token mutations. Implement New/Open/Recent libraries, native source chooser plus path entry, saved scans, details, pagination/filtering, Pause/Resume/Stop Safely and reports. API queries stay bounded; show discovery progress honestly. No fake or future-phase buttons.

Task 4 — Real samples and handoff.
Files: tests/real_batch.py, README.md, Phase-1-Test-Report.md, reports/.
Select up to 25 actual library songs without enumerating entire master again. Hash originals before/after; audit real ZIP/pairs/MP4 and break MP3/FLAC/M4A. Measure cold audit, unchanged cache reuse and UI snapshot speed. Run entire unittest suite, subprocess crash tests and browser interactions. Report exact PASS/WARNING/FAIL/UNKNOWN checks and known limitations. Fix meaningful failures and retest. Do not proceed to Phase 2.

Execution ledger: docs/Progress.md. Each task records verification commands/results. Phase completion is an exit-test claim, not a button or elapsed-time claim.
