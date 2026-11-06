from src.screen_sync import ScreenCaptureState


def test_fresh_valid_black_frames_enter_blackout_but_missing_frame_does_not():
    state = ScreenCaptureState(blackout_confirm_s=0.1, capture_stale_s=0.2)
    state.valid_frame(0.0, 0.0)
    assert state.scene == "DARK"
    state.valid_frame(0.01, 0.0)
    assert state.scene == "DARK"
    state.valid_frame(0.12, 0.0)
    assert state.scene == "BLACKOUT"
    state.capture_missing(0.33)
    assert state.scene == "BLACKOUT"
    assert state.capture_status == "CAPTURE_UNAVAILABLE"


def test_capture_hold_fade_and_recovery():
    state = ScreenCaptureState(capture_hold_s=0.5, capture_fade_s=0.5)
    state.valid_frame(10.0, 0.2)
    assert state.output_scale(10.49) == 1.0
    assert 0.0 < state.output_scale(10.75) < 1.0
    assert state.output_scale(11.1) == 0.0
    state.valid_frame(11.2, 0.2)
    assert state.capture_status == "AVAILABLE"
    assert state.output_scale(11.2) == 0.0
    assert 0.0 < state.output_scale(11.3) < 1.0


def test_frozen_identical_frames_are_valid_and_dark_content_is_not_blackout():
    state = ScreenCaptureState(blackout_confirm_s=0.35)
    for t in (0.0, 0.1, 0.2, 0.3, 0.4):
        state.valid_frame(t, 0.03)
    assert state.scene == "DARK"
    assert state.capture_status == "AVAILABLE"


def test_wake_requires_hysteresis_threshold_and_recovers_smoothly():
    state = ScreenCaptureState(blackout_confirm_s=0.05, recovery_attack_s=0.2)
    state.valid_frame(0.0, 0.0)
    state.valid_frame(0.06, 0.0)
    assert state.scene == "BLACKOUT"
    state.valid_frame(0.07, 0.02)
    assert state.scene == "BLACKOUT"
    state.valid_frame(0.08, 0.12)
    assert state.scene == "ACTIVE"
    assert state.output_scale(0.08) == 0.0
    assert 0.0 < state.output_scale(0.18) < 1.0
