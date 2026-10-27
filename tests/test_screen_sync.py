from __future__ import annotations
import numpy as np
import pytest
from src.screen_sync import detect_letterbox_bounds, extract_dominant_color_weighted, SCREEN_PROFILES

def test_letterbox_detection():
    # Create 100x100 image with 20px black bars on top and bottom, and bright red in middle
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[20:80, :, 2] = 255  # Red in center

    left, top, right, bottom = detect_letterbox_bounds(img, black_thresh=10)
    assert top >= 16 and top <= 24
    assert bottom >= 76 and bottom <= 84
    assert left == 0
    assert right == 100

def test_saturation_weighted_dominant_color():
    # Create pixels where 90% are dull grey (128, 128, 128) and 10% are vivid cyan (255, 255, 0 in BGR)
    pixels = np.full((100, 3), 128, dtype=np.uint8)
    pixels[:10] = [255, 255, 0]  # Cyan

    # A plain average gives saturation around ~8%
    # But saturation-weighted extraction should heavily favor the vivid cyan
    h, s, v = extract_dominant_color_weighted(pixels, sat_boost=1.3)
    # Cyan hue is ~180
    assert 160 <= h <= 200
    assert s > 40  # Saturated, not washed out grey!

def test_screen_profiles():
    assert "video" in SCREEN_PROFILES
    assert "gaming" in SCREEN_PROFILES
    assert "desktop" in SCREEN_PROFILES
    assert SCREEN_PROFILES["gaming"]["attack_rate"] > SCREEN_PROFILES["desktop"]["attack_rate"]

def test_screen_sync_brightness_lift_on_dark_scenes():
    # Simulate a moody cinematic scene: 40% black background, 60% low-mid brightness (RGB ~ 60,60,60)
    pixels = np.zeros((100, 3), dtype=np.uint8)
    pixels[:60] = [60, 60, 60]
    
    h, s, v = extract_dominant_color_weighted(pixels, sat_boost=1.3)
    # Brightness should be healthy and luminous (>= 25%), not crushed to single digits
    assert v >= 25, f"Expected perceptual brightness lift >= 25, got {v}"

def test_screen_sync_audio_reactivity_l930_and_l900():
    from src.screen_sync import ScreenSync
    from src.audio_dsp import MusicState
    from types import SimpleNamespace

    submitted_frames = []
    class FakeController:
        def __init__(self, is_l930=True):
            if is_l930:
                self.set_segments = lambda segs: True
            self.frames = []
        def submit_frame(self, frame):
            submitted_frames.append(frame)

    class FakeCoordinator:
        def __init__(self, state):
            self.state = state
        def get_latest_state(self):
            return self.state, {}
        @property
        def latest_state(self):
            return self.state

    # 1. Test L930 with vocal and theme music building intensity
    ctrl_l930 = FakeController(is_l930=True)
    ast_theme = MusicState(energy=0.85, harmonic_ratio=0.80, speech_dominance=0.85)
    coord = FakeCoordinator(ast_theme)

    ss_l930 = ScreenSync(ctrl_l930, loop_runner=None, app_state={"brightness": 100}, audio_coordinator=coord)
    base_segs = [[180, 80, 30] for _ in range(50)]
    ss_l930._dispatch(base_segs, (180, 80, 30), is_l930=True, profile=SCREEN_PROFILES["video"])

    assert len(submitted_frames) >= 1
    l930_frame = submitted_frames[-1]
    assert "segments" in l930_frame
    # Vocals and theme music intensity should boost center zones well above base 30
    assert l930_frame["segments"][24][2] > 40, f"Vocal/theme build-up failed to boost center IC: {l930_frame['segments'][24][2]}"
    assert l930_frame.get("_pre_corrected") is True

    # 2. Test L900 with vocal and theme music building intensity
    ctrl_l900 = FakeController(is_l930=False)
    ss_l900 = ScreenSync(ctrl_l900, loop_runner=None, app_state={"brightness": 100}, audio_coordinator=coord)
    ss_l900._dispatch(None, (180, 80, 30), is_l930=False, profile=SCREEN_PROFILES["video"])

    l900_frame = submitted_frames[-1]
    assert "b" in l900_frame
    assert l900_frame["b"] > 40, f"Vocal/theme build-up failed to boost L900 brightness: {l900_frame['b']}"
    assert l900_frame.get("_pre_corrected") is True


def test_screen_sync_pure_kicks_do_not_flash_or_strobe():
    """Verify ScreenSync ignores isolated percussive kicks and does not strobe white."""
    from src.screen_sync import ScreenSync
    from src.audio_dsp import MusicState

    submitted_frames = []
    class FakeController:
        def __init__(self, is_l930=True):
            self.set_segments = lambda segs: True
        def submit_frame(self, frame):
            submitted_frames.append(frame)

    class FakeCoordinator:
        def __init__(self, state):
            self.state = state
        def get_latest_state(self):
            return self.state, {}

    # Isolated kick without vocal or theme music buildup
    ast_kick_only = MusicState(energy=0.01, kick=0.95, bass=0.9, transient=0.9, is_extreme_bass=True)
    coord = FakeCoordinator(ast_kick_only)

    ctrl = FakeController(is_l930=True)
    ss = ScreenSync(ctrl, loop_runner=None, app_state={"brightness": 100}, audio_coordinator=coord)
    base_segs = [[180, 80, 30] for _ in range(50)]
    ss._dispatch(base_segs, (180, 80, 30), is_l930=True, profile=SCREEN_PROFILES["video"])

    frame = submitted_frames[-1]
    # Center zone should remain around base 30; no flash, no white strobe (saturation remains 80)
    assert frame["segments"][24][2] <= 32, f"Kick only should not flare screen sync, got {frame['segments'][24][2]}"
    assert frame["segments"][24][1] == 80, f"Screen sync should never strobe white or desaturate"


def test_drop_bloom_preserves_pure_negative_space():
    """Verify DropBloomAccent keeps inactive zones strictly at 0 brightness on multi-zone strips."""
    from src.visual_styles import DropBloomAccent
    from src.audio_dsp import MusicState, Section

    bloom = DropBloomAccent()
    # Trigger a drop bloom event
    ast_drop = MusicState(section=Section.DROP, drop_strength=0.95, kick=0.90, is_extreme_bass=True)
    frame = [(200, 80, 0)] * 50  # All zones inactive (0 brightness)
    frame[25] = (200, 80, 80)     # Zone 25 active

    result = bloom.render_accent(ast_drop, dt=0.01, num_zones=50, frame=frame)
    # Active zone 25 punches white/bright
    assert result[25][2] >= 80
    # Inactive zone 0 MUST stay strictly 0 brightness (pure negative space!)
    assert result[0][2] == 0, f"Inactive zone should remain 100% OFF, got {result[0][2]}"
    assert result[10][2] == 0


