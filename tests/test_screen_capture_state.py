from src.screen_sync import ScreenCaptureState


def test_fresh_valid_black_frames_enter_blackout_but_missing_frame_does_not():
    state = ScreenCaptureState(blackout_confirm_s=0.1, capture_stale_s=0.2)
    state.valid_frame(0.0, 0.0, 1.0)
    assert state.scene == "DARK"
    state.valid_frame(0.01, 0.0, 1.0)
    assert state.scene == "DARK"
    state.valid_frame(0.12, 0.0, 1.0)
    assert state.scene == "BLACKOUT"
    state.capture_missing(0.33)
    assert state.scene == "BLACKOUT"
    assert state.capture_status == "CAPTURE_UNAVAILABLE"
    assert state.output_scale(0.33) == 0.0


def test_capture_unavailable_hold_begins_after_stale_timeout_then_fades_and_recovers():
    state = ScreenCaptureState(
        capture_stale_s=0.2,
        capture_hold_s=0.5,
        capture_fade_s=0.5,
        recovery_attack_s=0.2,
    )
    state.valid_frame(10.0, 0.3, 0.0)
    state.valid_frame(10.21, 0.3, 0.0)  # Refresh after stale boundary.
    assert state.output_scale(10.21) == 1.0

    state.capture_missing(10.41)
    assert state.capture_status == "CAPTURE_UNAVAILABLE"
    assert state.output_scale(10.41) == 1.0
    assert state.output_scale(10.90) == 1.0  # 500 ms hold from unavailability.
    assert 0.0 < state.output_scale(11.15) < 1.0
    assert state.output_scale(11.42) == 0.0

    state.valid_frame(11.5, 0.3, 0.0)
    assert state.capture_status == "AVAILABLE"
    assert state.output_scale(11.5) == 0.0
    assert 0.0 < state.output_scale(11.6) < 1.0
    assert state.output_scale(11.71) == 1.0


def test_frozen_identical_frames_are_valid_and_dark_content_is_not_blackout():
    state = ScreenCaptureState(blackout_confirm_s=0.35)
    for t in (0.0, 0.1, 0.2, 0.3, 0.4):
        state.valid_frame(t, 0.03, 0.0)
    assert state.scene == "DARK"
    assert state.capture_status == "AVAILABLE"


def test_wake_requires_hysteresis_threshold_and_recovers_smoothly():
    state = ScreenCaptureState(blackout_confirm_s=0.05, recovery_attack_s=0.2)
    state.valid_frame(0.0, 0.0, 1.0)
    state.valid_frame(0.06, 0.0, 1.0)
    assert state.scene == "BLACKOUT"

    # A value above the entry threshold but below the wake threshold does not wake.
    state.valid_frame(0.07, 0.02, 0.0)
    assert state.scene == "BLACKOUT"

    state.valid_frame(0.08, 0.12, 0.0)
    assert state.scene == "ACTIVE"
    assert state.output_scale(0.08) == 0.0
    assert 0.0 < state.output_scale(0.18) < 1.0


def test_near_black_pixel_ratio_prevents_dark_scene_from_being_misclassified_as_blackout():
    state = ScreenCaptureState(blackout_confirm_s=0.05)
    for t in (0.0, 0.1, 0.2, 0.3, 0.4):
        state.valid_frame(t, 0.01, 0.98)
    assert state.scene == "DARK"
    assert state.capture_status == "AVAILABLE"

    state.valid_frame(0.5, 0.01, 1.0)
    state.valid_frame(0.56, 0.01, 1.0)
    assert state.scene == "BLACKOUT"


def test_dark_scene_scale_dims_without_switching_to_blackout():
    state = ScreenCaptureState()
    state.valid_frame(1.0, 0.05, 0.0)
    assert state.scene == "DARK"
    scale = state.scene_scale()
    assert 0.18 < scale < 1.0


def test_screen_luminance_uses_raw_pixels_not_perceptual_hsv_lift():
    import numpy as np
    from src.screen_sync import measure_screen_luminance

    black = np.zeros((32, 32, 3), dtype=np.uint8)
    mean_luma, near_black_ratio = measure_screen_luminance(black, stride=4)
    assert mean_luma == 0.0
    assert near_black_ratio == 1.0

    dark_movie = np.zeros((32, 32, 3), dtype=np.uint8)
    dark_movie[:24, :, :] = 20
    mean_luma, near_black_ratio = measure_screen_luminance(dark_movie, stride=4)
    assert 0.0 < mean_luma < 0.10
    assert 0.0 < near_black_ratio < 1.0
