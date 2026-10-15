from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_release_verifier_requires_no_embedded_credentials_and_documents_smoke_gate() -> None:
    source = Path("scripts/verify_release.py").read_text()
    readme = Path("README.md").read_text()

    assert "api_key" not in source.lower()
    assert "two-singer live smoke" in readme.lower()
    assert "# karaoke collector" in readme.lower()
    assert "pre-show checks and diagnostics" in readme.lower()


def test_release_verifier_runs_from_the_project_root() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_release.py"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
