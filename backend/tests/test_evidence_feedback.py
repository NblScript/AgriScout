"""证据反馈状态机与完整性检查的纯函数测试。"""

import pytest

from app.services.evidence_feedback import (
    ALLOWED_TRANSITIONS,
    CONFIRMED_NEGATIVE,
    CONFIRMED_POSITIVE,
    INTERVENED,
    PENDING,
    VALID_STATUSES,
    CompletenessReport,
    InvalidStatusError,
    InvalidTransitionError,
    apply_transition,
    assert_complete,
    check_completeness,
    is_complete,
    is_valid_transition,
    transition_status,
    validate_status,
    validate_transition,
)


def _record(**overrides):
    record = {
        "alert_id": "risk-001",
        "observation_region": "field-1/row-3/12m",
        "prediction_window": {"start": "2026-09-24T08:00:00+08:00", "end": "2026-09-26T08:00:00+08:00"},
        "model_version": "risk-v1",
        "evidence": ["/media/patrol-1/point-1.jpg"],
        "status": PENDING,
    }
    record.update(overrides)
    return record


def test_status_set_is_exact_and_status_validation_is_strict():
    assert VALID_STATUSES == {
        "confirmed_positive",
        "confirmed_negative",
        "pending",
        "insufficient",
        "intervened",
        "unknown",
    }
    assert validate_status(PENDING) == PENDING
    with pytest.raises(InvalidStatusError):
        validate_status("resolved")


def test_new_record_must_start_pending():
    assert ALLOWED_TRANSITIONS[None] == {PENDING}
    assert transition_status(None, PENDING) == PENDING
    with pytest.raises(InvalidTransitionError):
        transition_status(None, CONFIRMED_POSITIVE)


@pytest.mark.parametrize(
    "target",
    [CONFIRMED_POSITIVE, CONFIRMED_NEGATIVE, "insufficient", INTERVENED, "unknown"],
)
def test_pending_can_be_resolved_to_each_feedback_outcome(target):
    validate_transition(PENDING, target)
    assert is_valid_transition(PENDING, target)
    assert transition_status(PENDING, target) == target


def test_insufficient_and_unknown_can_be_reopened_for_more_evidence():
    assert is_valid_transition("insufficient", PENDING)
    assert is_valid_transition("unknown", PENDING)
    assert is_valid_transition("insufficient", CONFIRMED_NEGATIVE)
    assert is_valid_transition("unknown", CONFIRMED_POSITIVE)


@pytest.mark.parametrize("terminal", [CONFIRMED_POSITIVE, CONFIRMED_NEGATIVE, INTERVENED])
def test_terminal_statuses_are_immutable_except_idempotent_update(terminal):
    assert is_valid_transition(terminal, terminal)
    with pytest.raises(InvalidTransitionError):
        transition_status(terminal, PENDING)


def test_invalid_status_transition_is_rejected_and_boolean_helper_is_safe():
    with pytest.raises(InvalidStatusError):
        validate_transition("not-a-status", PENDING)
    assert not is_valid_transition("not-a-status", PENDING)
    assert not is_valid_transition(PENDING, "not-a-status")


def test_apply_transition_is_pure_and_does_not_mutate_input():
    original = _record()
    updated = apply_transition(original, "unknown")
    assert original["status"] == PENDING
    assert updated["status"] == "unknown"
    assert updated["alert_id"] == original["alert_id"]


def test_pending_record_with_alert_provenance_is_complete():
    report = check_completeness(_record())
    assert isinstance(report, CompletenessReport)
    assert report.complete
    assert report.missing == ()
    assert report.invalid == ()
    assert is_complete(_record())


@pytest.mark.parametrize("field", [
    "alert_id",
    "observation_region",
    "prediction_window",
    "model_version",
    "evidence",
    "status",
])
def test_missing_provenance_is_reported_by_canonical_field(field):
    record = _record()
    record[field] = None
    report = check_completeness(record)
    assert not report.complete
    assert field in report.missing
    assert field in report.issues


def test_invalid_window_and_status_are_reported_separately():
    report = check_completeness(_record(prediction_window={"start": "only-start"}, status="bad"))
    assert not report.complete
    assert "prediction_window" in report.invalid
    assert "status" in report.invalid


def test_confirmed_outcome_requires_a_human_or_follow_up_conclusion():
    report = check_completeness(_record(status=CONFIRMED_POSITIVE))
    assert not report.complete
    assert "human_conclusion_or_follow_up" in report.missing

    complete = check_completeness(
        _record(status=CONFIRMED_POSITIVE, human_conclusion="专家确认阳性")
    )
    assert complete.complete

    by_follow_up = check_completeness(
        _record(status=CONFIRMED_NEGATIVE, follow_up={"evidence": ["point-2.jpg"]})
    )
    assert by_follow_up.complete


def test_intervened_outcome_requires_intervention_record():
    missing = check_completeness(
        _record(status=INTERVENED, human_conclusion="已处置，不能作未干预标签")
    )
    assert not missing.complete
    assert "intervention" in missing.missing

    complete = check_completeness(
        _record(
            status=INTERVENED,
            human_conclusion="已处置，随访受干预影响",
            intervention={"at": "2026-09-24T10:00:00+08:00", "action": "施药"},
        )
    )
    assert complete.complete


def test_require_follow_up_can_be_disabled_for_staging_records():
    report = check_completeness(
        _record(status=CONFIRMED_NEGATIVE), require_follow_up=False
    )
    assert report.complete


def test_aliases_are_accepted_without_mutating_record():
    record = {
        "risk_prediction_id": "risk-002",
        "region_id": 3,
        "forecast_window": ["2026-09-24", "2026-09-26"],
        "analyzer_version": "placeholder-color-v0",
        "evidence_refs": ["point-3.jpg"],
        "follow_up_status": PENDING,
    }
    report = check_completeness(record)
    assert report.complete
    assert "status" not in record


def test_non_mapping_record_is_incomplete():
    report = check_completeness([])  # type: ignore[arg-type]
    assert not report.complete
    assert report.invalid == ("record",)


def test_assert_complete_raises_with_actionable_fields():
    with pytest.raises(ValueError, match="human_conclusion_or_follow_up"):
        assert_complete(_record(status=CONFIRMED_POSITIVE))\n