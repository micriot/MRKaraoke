# Scanning and import performance — 2026-10-04

Workers now immediately claim another pending file when any worker finishes. Previously every batch waited for its slowest member. Concurrency remains bounded at two workers by default. Durable file claims and completed-stage checkpoints remain enabled with SQLite FULL synchronization.

Discovery reuses metadata obtained from directory entries rather than issuing another stat for each queued file. Discovery still commits every 64 entries or one second, whichever comes first. No validation stages were removed and analysis cache versions remain unchanged because the checks themselves did not change.

Synthetic before/after benchmark on this Mac: importing 2,000 tiny files fell from 0.09763 to 0.08119 seconds (about 17% faster). A 16-task mixed-duration scheduler workload with two workers fell from 0.74192 to 0.42815 seconds (about 42% faster). These are single-run synthetic measurements, subject to filesystem caching and scheduling variability.

The same 13 actual files audited in 2.464 seconds versus the previous recorded 3.216 seconds. This comparison spans separate runs and does not isolate scheduler improvements from warm filesystem caches. Unchanged resume was 0.00906 seconds. All original hashes matched before and after; outcomes remained 11 Needs Review and two Failed. A temporary project held the benchmark state and no new full-library scan was performed.

31 automated tests passed, including a new concurrency regression that requires the next queued file to start before a slow file completes. Existing crash recovery, cancellation, source changes, companion cache, incremental scans, and HTTP checks passed. Large-library throughput remains unmeasured.
