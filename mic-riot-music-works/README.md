# Mic Riot Music Works v0.2

Independent local music-library scanning and safe copy repairs. Sing WS is not required, accessed, or contacted. Its integration has been removed. Existing scan progress is retained.

## Start

Open `../Mic-Riot-Music-Works-0.2-Apple-Silicon.dmg`, drag Mic Riot Music Works to Applications, then double-click the app. It includes Python, FFmpeg, and FFprobe and opens its interface in your browser at http://127.0.0.1:8765. This is a standalone runtime bundle with a browser interface, not a native window. It was built and checked on this Mac only. It has an ad-hoc signature and is not notarized for public distribution.

Source users can still run `python3 launch.py` or Start Auditor.command with Python and FFmpeg installed.

The bundled app stores projects in `~/Library/Application Support/Mic Riot Music Works/Libraries`. Your existing projects were copied there, including unfinished progress. The source application's older Libraries directory remains intact; use the bundled app going forward to avoid maintaining two separate project histories.

## Scan and repair

1. Select a library, add local sources, and Scan. An unfinished job offers Resume Scan.
2. Click a file for its specific checks and repair explanation.
3. Pause or finish the scan before choosing **Fix What Can Be Fixed**. Only completed files with established safe actions are eligible. Pending scan files are not repaired.
4. The app creates separate working copies, verifies them, and publishes successful outputs in FIXED. Use **Open Fixed Folder** to find them. Originals are never renamed, overwritten, moved, or deleted.
5. Stop Safely saves pending repair work. Resume Repairs continues the durable queue. Generate Reports includes actual repair evidence.

Current automatic actions: flatten a readable ZIP containing one matching MP3/CDG pair and remove extra entries; package a loose exact-name MP3/CDG pair into a clean ZIP. Every result gets CRC checks, full audio decoding, CDG structural checks, member-byte preservation checks, and original hashes checked again. Publication is atomic, never overwrites an existing output, and saves its intent for crash recovery.

Failures and uncertain files stay visible with explanations. Missing audio, unrecoverable corruption, mismatched identities, unsupported ZIP methods, and uncertain naming need replacement or review. The app does not claim that packaging can restore lost sound.

## Persistent and fast

Scanning saves folder discovery every 64 entries or one second and each completed analysis stage. Resume continues saved queues; Check for Changes checks recorded folders and enumerates changed folders. Workers refill immediately when any worker finishes. SQLite uses WAL and FULL synchronization. Keep project directories: they hold your state.

## Actual status

This is a working independent audit and packaging-repair app, not the entire master specification. Automatic repairs use deterministic local rules. A generative AI identity/recommendation service, full graphics rendering/sync tests, arbitrary corruption restoration, canonical naming with confirmed identities, duplicate consolidation, music playback, and playlist generation are not implemented. No cloud AI or streaming account is contacted.

See docs/V0.2-Verification.md for evidence and limits. Tests: `python3 -m unittest discover -s tests`.
