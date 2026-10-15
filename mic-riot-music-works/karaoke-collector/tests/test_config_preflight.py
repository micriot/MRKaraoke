from __future__ import annotations

import pytest

from singws_live_test_runner.config import Redactor, RunConfiguration
from singws_live_test_runner.domain import RunMode, RunRecord, RunState
from singws_live_test_runner.preflight import PreflightService


def valid_configuration() -> RunConfiguration:
    return RunConfiguration(
        tenant_id="mrk",
        api_base_url="https://micriot.net",
        credential_reference="micriot-test-token",
        target_song_count=10,
        request_pace_seconds=3,
        baseline_song="SC – Neon Moon – Brooks & Dunn",
        required_host_name="SingWS",
    )


def test_preflight_lists_invalid_configuration_before_ready() -> None:
    invalid = valid_configuration().replace(target_song_count=0, request_pace_seconds=0)

    result = PreflightService().evaluate(invalid)

    assert result.is_ready is False
    assert "target_song_count must be between 1 and 100" in result.blocking_messages
    assert "request_pace_seconds must be at least 1" in result.blocking_messages


def test_redactor_keeps_credential_out_of_messages_and_serialized_output() -> None:
    secret = "actual-secret-value"
    redactor = Redactor((secret,))

    assert redactor.redact(f"Authorization: Bearer {secret}") == "Authorization: Bearer [REDACTED]"
    assert secret not in redactor.redact_exception(RuntimeError(secret))


def test_preflight_requires_exact_operator_confirmation_before_running() -> None:
    run = RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=10)
    service = PreflightService()
    result = service.evaluate(valid_configuration())

    assert result.is_ready is True
    with pytest.raises(PermissionError, match="explicit operator confirmation"):
        service.confirm_ready(run, result, "start")

    ready_run = service.confirm_ready(run, result, "OK, Start Test Run")

    assert ready_run.state is RunState.READY
