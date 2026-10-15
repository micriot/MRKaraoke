# Karaoke Collector

Pre-show checks and diagnostics to fine-tune your SingWS hosting experience.
Karaoke Collector includes optional measured, operator-confirmed stress-test
scenarios. It never submits a request until the person at the Mac reviews
preflight and confirms **OK, Start Test Run**.

## Before any larger live test

Run the automated checks, then perform a **two-singer live smoke** only after
the Mic Riot tenant, SingWS host connection, audio route, and display evidence
are visibly confirmed. Do not run a 10+ song test until that smoke gate passes.

## Local development

```zsh
.venv/bin/python -m pytest -v
.venv/bin/python scripts/verify_release.py
```
