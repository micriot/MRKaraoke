# Karaoke Collector — Design

## Purpose

Build a dedicated macOS test application that creates an authorized live
stress-and-quality run against the Mic Riot request API and measures the real
SingWS host experience from request intake through karaoke playback and the
return to background music.

The runner is for the host's own environment during an operator-approved
live-test window (America/Los_Angeles). It is not a public kiosk, an API
load-testing tool for arbitrary tenants, or a replacement for SingWS.

## Launch and consent behavior

SingWS always remains a normal standalone hosting application. Opening it by
itself must not open, configure, or start the Test Runner, and no test-run
state may change normal SingWS behavior outside an explicitly running test.

The Test Runner is a separate application. When opened first, it waits for
SingWS to be launched and detects a usable local host session. It then shows a
**Test Run Ready** prompt, never an automatic run. The prompt presents the
preflight result: resolved Mic Riot tenant, request-open status, connected
SingWS session, expected reference song, selected request count and pace,
available unique songs, capture/display availability, and any blocking
warnings. The operator must press **OK, Start Test Run** after reviewing that
screen before the runner submits even one API request or drives a SingWS
control. Closing or declining the prompt leaves both applications unchanged.

## Test modes

### Pre-Show Check

Pre-Show Check is the short readiness gate for a host who has not used the
current build and needs confidence before doors open. It targets a five-minute
run, rather than the 15+ minutes required by three full songs.

It checks the Mic Riot network, SingWS connection, local karaoke library and
external media drive, actual audio route, background music, rotation/show
controls, selected DJ/soundboard action, and an internal mock of the external
display. A missing physical external display is a warning, not a blocker: the
mock must still render the expected rotation and karaoke/show states.

After preflight and explicit confirmation, it runs this controlled three-song
sequence: one local-library song, one KaraFun song, then one different
local-library song. It fast-forwards each test song to its defined start,
active-playback, and finish/handoff checkpoints. The purpose is to prove
local → KaraFun → local handoffs and BGM transitions, not to play each full
track. It records the same route, silence, black-frame, UI, and transition
evidence as a full run, labeled `pre-show` in the report.

### Live Test Run

Live Test Run is the configurable 1–100-song scenario. The setup screen has
an editable song-count field so the operator can choose, for example, 10, 20,
50, or 100 requests. It uses the live Mic Riot API under the safety boundaries
below and applies full playback observation, scoring, and reporting. It sends
an initial batch of 10 requests, then replenishes by 10 when eight requests
from the current batch have completed and two remain. It never posts the full
target count at once.

## User-stated requirements

- Submit an operator-selected number of distinct singer requests (1–100) to
  the real Mic Riot server; 50–100 is supported for a full stress run.
- Use synthetic, human-readable names in the form `FirstName Test`; no request
  may claim to be an actual person.
- Do not select the same karaoke song twice in a test run.
- Submit Live Test requests in rolling batches of 10, never the full planned
  count at once. When eight songs from a submitted batch are completed and two
  remain, submit the next eligible batch of 10 until the configured total is
  reached.
- Continue through individual song, media, or host-control failures; record
  them as failed results and continue testing later queued songs.
- Exercise the public-request path through the API because the kiosk/network
  was previously stressed.
- Exercise SingWS itself: singer rotation, rotation screen, karaoke/show
  screen, background music, DJ/soundboard buttons, and song playback.
- Measure timing from the background-music transition to usable karaoke start.
- Note all silences and small anomalies.
- Score the karaoke video and music track from 1 to 10 for every performed
  test. `SC – Neon Moon – Brooks & Dunn` is the known-good reference song.
- Provide a roughly five-minute pre-show check that exercises three songs in
  local-library → KaraFun → local-library order and fast-forwards through the
  planned checkpoints instead of waiting for full songs.
- During any test, use the Mac's built-in speakers only; do not reroute audio
  to an external headphone jack. Report the detected SingWS/audio route and
  warn about unexpected routes without silently changing them.

## Non-negotiable safety boundaries

- The target tenant, API base URL, and required credentials are read from an
  explicit run configuration; no credential is written to logs, reports, or
  screenshots.
- Before any submission, show the resolved tenant and a plain-language count
  of the requests that will be created. A human must explicitly confirm the
  completed preflight with **OK, Start Test Run**.
- Never submit to an endpoint other than the configured Mic Riot tenant.
- Generate only names ending in `Test`, tag all run data with a UUID, and
  preserve the request IDs returned by the server.
- Never remove, reorder, complete, skip, or edit requests that were not
  created by the current run.
- An always-visible Stop button prevents further submissions and safely
  finalizes evidence already collected. It cannot undo requests already sent.
- Default pacing is conservative (one request every 3 seconds); configurable
  pacing has a minimum of 1 second and no burst mode.
- Treat a song-level failure as a recorded outcome, not a reason to stop the
  run. Continue with later test songs and include all failures in the final
  report.
- Do not change the system audio device or the SingWS output device without a
  separate, explicit operator action. The app's own Pre-Show audio must use
  the Mac built-in speakers and must never select an external headphone jack.

## Product shape

The first release is a local macOS desktop app with three surfaces:

1. **Run setup** — target validation, mode selection, a Live Test song-count
   field (1–100), pace, failure-stop
   threshold, expected host/display names, and a preview of the generated
   singers and unique song list. When SingWS becomes available, it presents
   the Test Run Ready preflight prompt and waits for explicit confirmation.
2. **Live run console** — submission progress, host observations, current
   singer/song, timers, markers, audio/video quality scores, anomaly stream,
   and Stop/Finish controls.
3. **Report viewer** — a chronological event timeline, per-request evidence,
   per-song grades, aggregate transition/silence metrics, and exportable JSON
   plus a human-readable HTML report.

## Architecture

### Run coordinator

Owns the finite-state run: `draft → preflight → baseline → submitting →
observing → stopping → completed | failed`. It is the only component allowed
to start API submissions. State is persisted locally so an interrupted run is
truthful about its last confirmed event rather than silently resuming.

### Mic Riot API adapter

Discovers and calls only the request creation and request-status operations
needed for the selected tenant. It uses the configured credential in memory,
redacts it from all diagnostics, applies the 1-second minimum rate limit, and
records raw status codes and redacted response summaries. Exact endpoints and
request/response schemas are verified against the configured live tenant in
preflight; implementation must not infer them from the installed application.

### Scenario generator

Builds a deterministic manifest from a saved random seed: 1–100 unique first
names plus `Test`, unique songs from the tenant songbook, one baseline entry
for `SC – Neon Moon – Brooks & Dunn`, and a bounded sequence of approved host
actions. It fails preflight if the songbook cannot provide enough unique songs
or the reference title cannot be unambiguously resolved.

### SingWS host observer/controller

Connects only to the local SingWS session via documented local signals,
window accessibility state, or a narrowly scoped local bridge established at
implementation time. It observes queue arrival, active singer/song, playback
state, BGM state, rotation display, karaoke/show display, and UI-visible
errors. It drives only the agreed host controls: open rotation screen, open
karaoke/show screen, selected DJ buttons, play/pause/finish when necessary for
the scripted test. Each control action is recorded with before/after state.

### Media observer

Creates timestamped local evidence during every playback transition:

- audio-energy samples detect silence below a calibrated threshold;
- video frame sampling detects black/no-frame intervals and stalled frames;
- host state supplies requested/queued/started/finished milestones.

It does not record or transmit ambient microphone audio. Evidence is local and
bounded to the window/display and app output required to explain test results.

### Audio-route inspector

Reads and displays the current audio device used by SingWS and the output used
by the Test Runner. It identifies built-in speakers, headphone jack, HDMI,
USB/external speakers, AirPlay, and unknown devices. It does not silently
reroute SingWS. Before and during Pre-Show Check, it verifies that the Test
Runner's playback route is the Mac's built-in speakers and marks any external
headphone-jack route as a blocking test-route failure.

### External-screen mock

Renders a local, resizable preview of the rotation and karaoke/show output
using the same state that would drive a physical second display. It lets the
operator verify the room-facing layout even when no external screen is
connected. If a screen is connected, the app records its presence and the
expected output route; it never requires one merely to complete Pre-Show
Check.

### Scoring engine

Runs the baseline first. Its measured transition and display behavior become a
reference, not a guarantee of song quality. Each test song receives:

- **Video score (1–10):** lyric/video visibility, stable non-black output,
  aspect/crop consistency, and sync behavior relative to the baseline.
- **Track score (1–10):** audible output, continuity, level consistency,
  clean BGM handoff, and alignment with the selected song title.

Automatic metrics propose a score and explain it. The operator may adjust the
score, but the original automatic score and reason remain in the report.

## Run data flow

1. Validate API reachability, tenant identity, SingWS connection, accepting
   requests, library/songbook availability, reference-song resolution, audio
   route, media-drive presence, and mock external-screen rendering.
2. For a Pre-Show Check, run local-library → KaraFun → local-library through
   fast-forward checkpoints and report readiness. For a Live Test Run, play
   and observe the Neon Moon baseline, including BGM → karaoke → BGM.
3. For a Live Test Run, submit an initial batch of 10 manifest requests at the
   configured pace. After eight from that batch complete and two remain,
   submit the next eligible 10; repeat only until the configured total is met.
4. Match API acknowledgements to host-queue arrivals by run ID, request ID,
   singer, and song; never treat an unverified match as success.
5. For each queued song, observe or initiate the planned host/display actions,
   mark transition boundaries, collect media evidence, and record anomalies.
6. Once the song completes and BGM resumes, calculate scores and append the
   immutable per-song result.
7. Stop on user request, scheduled completion, or failure threshold; finalize
   an honest report even if the run is incomplete.

## Measurements and failure rules

All timing uses a monotonic local clock and includes both host event time and
capture time when available.

| Measurement | Start | End | Failure / annotation |
| --- | --- | --- | --- |
| API-to-queue latency | API submit acknowledgement | matching host queue item | missing or ambiguous arrival |
| BGM-to-karaoke start | BGM fade/stop detected | audible karaoke and non-black karaoke frame | any silence, black frame, or stalled state |
| Karaoke active duration | first usable karaoke frame/audio | finish/stop event | early end, frozen frame, or audio loss |
| Karaoke-to-BGM return | karaoke finish | audible BGM and non-black idle/show frame | silence, missing BGM, or wrong display |
| UI action response | each action dispatch | expected visible host state | timeout, error, or unexpected state |

Every silence, even brief, is stored with start, end, duration, surrounding
event IDs, and a severity. Default severity: informational below 250 ms,
warning at 250–999 ms, failure at 1 second or more. Thresholds are configurable
and visible in the report.

The run stops immediately only for an API authentication/tenant mismatch, API
request creation against an unconfirmed endpoint, evidence that a non-run
request has been manipulated, or an explicit operator Stop. It records and
continues through individual API, queue-matching, playback, media-capture, and
host-control failures whenever subsequent test songs can still run. A lost
connection or host-control confidence issue pauses new batch submission and
asks the operator whether to retry or finish the report; it does not discard
already collected evidence.

## Verification strategy

- Unit tests cover manifest uniqueness, `Test` naming, rate limits, redaction,
  state transitions, matching logic, silence classification, scoring bands,
  and report integrity.
- Contract tests use recorded/redacted API fixtures before any live request.
- A two-singer live smoke run validates the exact current endpoint/schema and
  host observer before a larger live run is enabled.
- A Pre-Show Check verifies that the three-song fast-forward scenario completes
  within five minutes, preserves the Mac built-in-speaker test route, detects
  an external-headphone route, and renders the external-screen mock with no
  physical display attached.
- A full run verifies unique songs, request-to-queue matching, UI action logs,
  baseline comparison, complete evidence records, report export, rolling
  batch replenishment, and continuation after an individual test-song failure.
- No success claim is made merely because requests were accepted: a run must
  have host-side and media observations for every completed result.

## Explicit limits

- The real Mic Riot API schema and local SingWS integration points have not
  yet been verified. Preflight and the two-singer smoke run are hard gates.
- A score assesses the observed playback in this specific environment; it
  cannot certify an underlying media file for all equipment or venues.
- The app cannot make a person sing. “Performed” means SingWS completed its
  playback lifecycle while the runner observed the karaoke media.
