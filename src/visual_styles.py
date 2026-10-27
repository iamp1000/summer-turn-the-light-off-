from __future__ import annotations
import functools
import math
import random
import time
from typing import List, Tuple, Dict, Any, Optional

import numpy as np

from src.audio_dsp import MusicState, Section, SourcePreset
from src.screen_sync import ScreenData
from src.pipeline import (
    lerp_oklab,
    rgb_to_tapo_hsv,
    tapo_hsv_to_rgb,
    oklch_to_rgb,
    rgb_to_oklch,
)

NUM_SEGMENTS = 50

# Default rich musical palette if none provided
DEFAULT_PALETTE = [(215, 85, 75), (180, 90, 80), (280, 80, 70), (45, 95, 85)]


# ── Continuous OKLab Palette Interpolation ───────────────────────────────────

@functools.lru_cache(maxsize=1024)
def _cached_tapo_hsv_to_rgb(h: int, s: int, v: int) -> Tuple[float, float, float]:
    return tapo_hsv_to_rgb(h, s, v)


def sample_palette_oklab(
    palette: Optional[List[Tuple[int, int, int]]],
    t: float,
    cyclic: bool = False
) -> Tuple[int, int, int]:
    """
    Samples continuously along a discrete palette in perceptual OKLab space.
    Eliminates hard color banding and prevents muddy grey/brown midpoints.

    Args:
        palette: List of (h, s, v) color stops (Tapo HSV format: 0..360, 0..100, 0..100).
        t: Normalized position along palette (0.0 to 1.0).
        cyclic: If True, wraps continuously around (0.0 -> end -> 0.0).
    """
    pal = palette or DEFAULT_PALETTE
    n = len(pal)
    if n == 0:
        return (215, 85, 75)
    if n == 1:
        return pal[0]

    if cyclic:
        norm_t = (t % 1.0 + 1.0) % 1.0
        scaled = norm_t * n
        i0 = int(scaled) % n
        i1 = (i0 + 1) % n
        frac = scaled - math.floor(scaled)
    else:
        norm_t = max(0.0, min(1.0, float(t)))
        scaled = norm_t * (n - 1)
        i0 = int(scaled)
        i1 = min(n - 1, i0 + 1)
        frac = scaled - i0

    rgb0 = _cached_tapo_hsv_to_rgb(*pal[i0])
    rgb1 = _cached_tapo_hsv_to_rgb(*pal[i1])
    interp_rgb = lerp_oklab(rgb0, rgb1, frac)
    return rgb_to_tapo_hsv(*interp_rgb)


def blend_zones_oklab(
    frame_a: List[Tuple[int, int, int] | List[int]],
    frame_b: List[Tuple[int, int, int] | List[int]],
    blend_factor: float
) -> List[Tuple[int, int, int]]:
    """Crossfades between two full zone frames smoothly along shortest angular path with hue preservation."""
    t = max(0.0, min(1.0, blend_factor))
    if t <= 0.0:
        return [(int(x[0]), int(x[1]), int(x[2])) for x in frame_a]
    if t >= 1.0:
        return [(int(x[0]), int(x[1]), int(x[2])) for x in frame_b]

    out = []
    n = min(len(frame_a), len(frame_b))
    for i in range(n):
        ha, sa, va = frame_a[i]
        hb, sb, vb = frame_b[i]

        # If one zone is dark/off (V<=3) or desaturated (S<=5), preserve the other zone's hue so lighting up never flashes red
        if va <= 3 or sa <= 5:
            h = hb
            s = sb
        elif vb <= 3 or sb <= 5:
            h = ha
            s = sa
        else:
            diff_h = (hb - ha + 180) % 360 - 180
            h = int(round((ha + diff_h * t) % 360))
            s = int(round(sa + (sb - sa) * t))

        v = int(round(va + (vb - va) * t))
        out.append((h, s, max(0, min(100, v))))
    return out


def exp_smooth_fast(current: float, target: float, dt: float, tau: float) -> float:
    """Continuous exponential filter alpha = 1 - exp(-dt / tau), rate independent."""
    if tau <= 1e-6:
        return target
    alpha = 1.0 - math.exp(-max(0.0, dt) / tau)
    return current + alpha * (target - current)


# ── Internal Shared Events: Build Tension & Drop Bloom ──────────────────────

class BuildTensionAccent:
    """
    Unified Riser & Drop Build-up Engine for L930 (Active in all music modes):
    During Section.BUILD, pulses accelerate exponentially with growing tempo and section progress:
    1/4 notes -> 1/8 notes -> 1/16 notes -> 1/32 notes -> hyper-strobe right into the drop!
    Concentrates energy toward center, desaturates toward blinding white at peak tension,
    and drops to momentary pitch black right before the drop explosion.
    """
    def __init__(self):
        self.tension_env: float = 0.0
        self._build_time: float = 0.0

    def render_accent(
        self,
        state: MusicState,
        dt: float,
        num_zones: int,
        frame: List[Tuple[int, int, int]]
    ) -> List[Tuple[int, int, int]]:
        is_build = (state.section == Section.BUILD)
        target_t = state.tension if is_build else 0.0
        tau = 0.20 if target_t > self.tension_env else 0.60
        self.tension_env = exp_smooth_fast(self.tension_env, target_t, dt, tau)

        if self.tension_env < 0.04 or len(frame) <= 1:
            self._build_time = 0.0
            return frame

        self._build_time += dt
        half = (num_zones - 1) / 2.0
        bpm = max(60.0, min(180.0, float(getattr(state, "bpm", 120.0) or 120.0)))
        prog = max(float(getattr(state, "section_progress", 0.0)), self.tension_env)

        # Exponentially accelerating riser pulse: 1/4 -> 1/8 -> 1/16 -> 1/32 note pulses
        base_hz = bpm / 60.0
        riser_freq = base_hz * (2.0 ** min(4.0, prog * 3.8))
        strobe_val = math.sin(self._build_time * riser_freq * 2.0 * math.pi)

        # Duty cycle sharpens as build accelerates
        pulse_gate = 1.0 if strobe_val > (-0.2 + prog * 0.4) else max(0.12, 1.0 - prog * 0.88)
        sat_drain = max(0.20, 1.0 - prog * 0.70)

        out = []
        for i, (h, s, v) in enumerate(frame):
            dist_norm = abs(i - half) / half
            narrow_factor = max(0.15, 1.0 - dist_norm * (self.tension_env * 0.75))
            new_v = int(v * narrow_factor * pulse_gate)
            new_s = max(16, int(s * sat_drain))
            out.append((h, new_s, new_v))
        return out


class DropBloomAccent:
    """
    Pure white full-strip strobe and bloom for extreme bass beats and drops.
    Flashes on and off with pure white on extreme bass beats, and blooms on heavy drops.
    Fast rhythmic recovery ensures each beat transient in extreme bass triggers a visible flash.
    """
    def __init__(self):
        self.cooldown: float = 0.0
        self.stage: str = "IDLE"  # "IDLE", "HOLD", "DECAY"
        self.stage_time: float = 0.0
        self.bloom_intensity: float = 0.0
        self.last_drop_time: float = -10.0

    def render_accent(
        self,
        state: MusicState,
        dt: float,
        num_zones: int,
        frame: List[Tuple[int, int, int]]
    ) -> List[Tuple[int, int, int]]:
        self.cooldown = max(0.0, self.cooldown - dt)

        # Trigger white beat flash on extreme bass or drop
        is_white_strobe = getattr(state, "white_strobe", False)
        is_extreme = getattr(state, "is_extreme_bass", False) or is_white_strobe
        is_drop = (getattr(state, "section", "") == Section.DROP and getattr(state, "drop_strength", 0.0) > 0.80)
        
        can_trigger = (
            (is_extreme and (is_white_strobe or getattr(state, "kick", 0.0) > 0.74))
            or is_drop
        ) and self.cooldown <= 0.0

        if can_trigger:
            self.stage = "HOLD"
            self.stage_time = 0.0
            self.bloom_intensity = 1.0
            # Extreme bass beats use fast rhythmic flash cooldown; song drop events use 8s spacing
            self.cooldown = 0.14 if is_extreme else 8.0

        if self.stage != "IDLE":
            self.stage_time += dt
            if self.stage == "HOLD":
                self.bloom_intensity = 1.0
                if self.stage_time >= 0.065:
                    self.stage = "DECAY"
                    self.stage_time = 0.0
            elif self.stage == "DECAY":
                self.bloom_intensity = max(0.0, 1.0 - (self.stage_time / 0.075))
                if self.stage_time >= 0.075:
                    self.stage = "IDLE"
                    self.stage_time = 0.0
                    self.bloom_intensity = 0.0

        if self.bloom_intensity <= 0.01:
            return frame

        # Apply pure white flash (saturation drops to 0, brightness punches to 100)
        # For multi-zone addressable strips, preserve pure negative space (inactive ICs remain OFF)
        # unless an explicit full-strip white strobe is firing.
        out = []
        half = (num_zones - 1) / 2.0
        full_strobe = bool(getattr(state, "white_strobe", False))
        for i, (h, s, v) in enumerate(frame):
            dist = abs(i - half) / half if num_zones > 1 else 0.0
            spatial = math.exp(-0.5 * (dist / 0.85) ** 2) if num_zones > 1 else 1.0
            weight = self.bloom_intensity * spatial
            new_s = max(0, int(round(s * (1.0 - weight))))
            if num_zones > 1 and v == 0 and not full_strobe:
                new_v = 0
            else:
                new_v = min(100, int(round(v + (100 - v) * weight)))
            out.append((h, new_s, new_v))
        return out


# ── Base VisualStyle Class ───────────────────────────────────────────────────

class VisualStyle:
    """
    Base visual style.
    Strictly 100% OFF (0% brightness) on silence for music styles.
    Events have persistent envelopes lasting >= 2 send periods (>400 ms).
    """
    name: str = "BaseStyle"

    def __init__(self):
        self.speed: float = 1.0        # 0.2x to 3.0x
        self.intensity: float = 1.0    # 0.2x to 2.5x
        self.smoothing: float = 1.0    # 0.2x to 3.0x (independent envelope time factor)
        self.palette_mode: str = "auto" # "auto", "fixed", "preset"
        self._preset_palette: Optional[List[Tuple[int, int, int]]] = None
        self.measured_latency_s: float = 0.0

    def set_params(
        self,
        speed: Optional[float] = None,
        intensity: Optional[float] = None,
        smoothing: Optional[float] = None,
        palette_mode: Optional[str] = None,
        preset_palette: Optional[List[Tuple[int, int, int]]] = None,
        measured_latency_s: Optional[float] = None,
        **kwargs: Any,
    ):
        if speed is not None:
            self.speed = max(0.2, min(3.0, float(speed)))
        if intensity is not None:
            self.intensity = max(0.2, min(2.5, float(intensity)))
        if smoothing is not None:
            self.smoothing = max(0.2, min(3.0, float(smoothing)))
        if palette_mode is not None:
            self.palette_mode = palette_mode
        if preset_palette is not None:
            self._preset_palette = preset_palette
        if measured_latency_s is not None:
            self.measured_latency_s = max(0.0, min(1.0, float(measured_latency_s)))

    def get_palette(self, state: MusicState) -> List[Tuple[int, int, int]]:
        if self.palette_mode in ("album_art", "artwork"):
            try:
                from src.artwork_sync import get_artwork_provider
                art_pal = get_artwork_provider().get_palette()
                if art_pal:
                    return art_pal
            except Exception:
                pass
        if self.palette_mode == "preset" and self._preset_palette:
            return self._preset_palette
        return state.palette or DEFAULT_PALETTE

    def is_silent_state(self, state: MusicState) -> bool:
        if state.energy <= 0.005 and getattr(state, "kick", 0.0) <= 0.05 and getattr(state, "bass", 0.0) <= 0.05:
            return True
        if getattr(state, "silent", False) and state.energy <= 0.015:
            return True
        if state.section == Section.SILENT and state.energy <= 0.015:
            return True
        return False

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        raise NotImplementedError


# ── 1. MOVIE MODE (Cinema Ambilight + Room Fill) ──────────────────────────────

class MovieStyle(VisualStyle):
    """
    Cinema Synchronization Mode:
    - L900 (behind monitor): Ambilight strip. Colour = luminance-weighted average of
      the screen content (letterbox detection on), smoothing tau 0.4-0.8 s, never below
      a configurable floor (default ~18%), small flare on low-band audio impacts.
    - L930 (behind bed backboard): Room fill. Warm base (2700K) drifting toward the
      screen's average colour with tau 3-5 s, plus a gentle left-to-right gradient from
      the screen's column colours (NOT 1:1 mapped). Audio layer: slow loudness swell
      (+-10-15%, tau ~400 ms) and a warm centre-out flare on relative low-band impacts
      (attack ~60 ms, decay ~800 ms); reduce audio layer to near zero when speech-band
      energy dominates. Silence or static screen = steady room light.
    - Never drops below configurable room floor.
    """
    name = "Movie"

    def __init__(self):
        super().__init__()
        self.room_level: float = 18.0          # Default ~18% room floor
        self.brightness_cap: float = 70.0      # Default ~70% ceiling
        self.screen_influence: float = 0.70    # 0.0 to 1.0
        self.audio_reactivity: float = 0.50    # 0.0 to 1.0

        self.screen_data: ScreenData = ScreenData()

        # L900 state: smoothed (h, s, v) and audio impact flare envelope
        self._l900_hsv: List[float] = [30.0, 45.0, 18.0]
        self._l900_flare_env: float = 0.0

        # L930 state: room fill warm base drifting toward screen, swell, flare
        self._l930_avg_hsv: List[float] = [30.0, 45.0, 18.0]
        self._l930_swell: float = 0.0
        self._l930_flare_env: float = 0.0

    def set_screen_data(self, data: ScreenData):
        self.screen_data = data

    def set_params(
        self,
        speed: Optional[float] = None,
        intensity: Optional[float] = None,
        palette_mode: Optional[str] = None,
        preset_palette: Optional[List[Tuple[int, int, int]]] = None,
        measured_latency_s: Optional[float] = None,
        room_level: Optional[float] = None,
        brightness_cap: Optional[float] = None,
        screen_influence: Optional[float] = None,
        audio_reactivity: Optional[float] = None,
        **kwargs: Any,
    ):
        super().set_params(speed, intensity, palette_mode, preset_palette, measured_latency_s)
        if room_level is not None:
            self.room_level = max(5.0, min(50.0, float(room_level)))
        if brightness_cap is not None:
            self.brightness_cap = max(30.0, min(100.0, float(brightness_cap)))
        if screen_influence is not None:
            self.screen_influence = max(0.0, min(1.0, float(screen_influence)))
        if audio_reactivity is not None:
            self.audio_reactivity = max(0.0, min(1.0, float(audio_reactivity)))

    def render(
        self,
        state: MusicState,
        dt: float,
        num_zones: int,
        screen_data: Optional[ScreenData] = None,
        **kwargs: Any
    ) -> List[Tuple[int, int, int]]:
        sd = screen_data or self.screen_data
        gh, gs, gv = sd.global_hsv
        cols = sd.column_hsvs if len(sd.column_hsvs) >= 50 else [sd.global_hsv] * 50

        # Vocal & Speech presence extraction (250 Hz - 3.4 kHz):
        speech_dom = float(getattr(state, "speech_dominance", 0.0))
        bands = getattr(state, "bands", None)
        if bands is not None and len(bands) >= 35:
            vocal_raw = float(np.mean(bands[12:35]))
        else:
            vocal_raw = float(getattr(state, "mid", 0.0))
        vocal_energy = max(0.0, min(1.0, vocal_raw * 1.5 + speech_dom * 0.4))

        if not hasattr(self, "_vocal_env"):
            self._vocal_env = 0.0
        alpha_vocal = 1.0 - math.exp(-dt / (0.08 if vocal_energy > self._vocal_env else 0.35))
        self._vocal_env += alpha_vocal * (vocal_energy - self._vocal_env)
        audio_factor = self.audio_reactivity

        # Theme music sound building up intensity (soundtrack energy & harmonic tension):
        harmonic_ratio = float(getattr(state, "harmonic_ratio", 0.5))
        energy = float(getattr(state, "energy", 0.0))
        target_theme = max(0.0, min(1.0, energy * 0.70 + (harmonic_ratio - 0.25) * 0.35))

        if not hasattr(self, "_theme_intensity_env"):
            self._theme_intensity_env = 0.0
        alpha_theme = 1.0 - math.exp(-dt / (0.40 if target_theme > self._theme_intensity_env else 0.80))
        self._theme_intensity_env += alpha_theme * (target_theme - self._theme_intensity_env)

        # ── Single-Zone L900 Mapping (Ambilight behind monitor) ──
        if num_zones == 1:
            # Luminance-weighted screen colour with tau 0.4-0.8s (tau = 0.6s)
            alpha_900 = 1.0 - math.exp(-dt / 0.60)
            diff_h = (gh - self._l900_hsv[0] + 180) % 360 - 180
            self._l900_hsv[0] = (self._l900_hsv[0] + diff_h * alpha_900) % 360.0
            self._l900_hsv[1] += (gs - self._l900_hsv[1]) * alpha_900

            norm_v = gv / 100.0
            target_b = self.room_level + norm_v * (self.brightness_cap - self.room_level)
            self._l900_hsv[2] += (target_b - self._l900_hsv[2]) * alpha_900

            # Vocal presence swell + theme music sound building up intensity
            vocal_b = self._vocal_env * 14.0 * audio_factor
            theme_b = self._theme_intensity_env * 18.0 * audio_factor
            final_b = int(max(self.room_level, min(self.brightness_cap, self._l900_hsv[2] + vocal_b + theme_b)))
            return [(int(round(self._l900_hsv[0])), int(round(self._l900_hsv[1])), final_b)]

        # ── 50-Zone L930 Mapping (Room fill behind bed backboard) ──
        # Warm base 2700K: H=30, S=45
        warm_h, warm_s = 30.0, 45.0

        # Drift toward screen average colour with tau 3-5s (tau = 4.0s)
        alpha_drift = 1.0 - math.exp(-dt / 4.0)
        target_h = gh if self.screen_influence > 0.01 else warm_h
        target_s = min(75.0, gs * 0.70 + warm_s * 0.30)
        diff_h = (target_h - self._l930_avg_hsv[0] + 180) % 360 - 180
        self._l930_avg_hsv[0] = (self._l930_avg_hsv[0] + diff_h * alpha_drift) % 360.0
        self._l930_avg_hsv[1] += (target_s - self._l930_avg_hsv[1]) * alpha_drift

        # Slow loudness & theme music intensity swell
        target_swell = (self._theme_intensity_env * 20.0) * audio_factor
        alpha_swell = 1.0 - math.exp(-dt / 0.400)
        self._l930_swell += alpha_swell * (target_swell - self._l930_swell)

        # Baseline room brightness: [room_level, brightness_cap]
        base_v = self.room_level + (gv / 100.0) * (self.brightness_cap - self.room_level) * self.screen_influence
        base_v = max(self.room_level, min(self.brightness_cap, base_v + self._l930_swell))

        # 5-tap spatial Gaussian kernel directly over screen column colours
        n_cols = len(cols)
        kernel = [0.061, 0.242, 0.383, 0.242, 0.061]  # Gaussian sigma ~ 1.0
        offsets = [-2, -1, 0, 1, 2]

        segs: List[Tuple[int, int, int]] = []
        half = (num_zones - 1) / 2.0

        for i in range(num_zones):
            c_center = (i / float(max(1, num_zones - 1))) * float(max(1, n_cols - 1))
            c_idx = int(round(c_center))

            accum_sin = 0.0
            accum_cos = 0.0
            accum_s = 0.0
            accum_v = 0.0
            total_w = 0.0

            for w, off in zip(kernel, offsets):
                idx = max(0, min(n_cols - 1, c_idx + off))
                col_h, col_s, col_v = cols[idx]
                rad = math.radians(col_h)
                accum_sin += math.sin(rad) * w
                accum_cos += math.cos(rad) * w
                accum_s += col_s * w
                accum_v += col_v * w
                total_w += w

            conv_h = (math.degrees(math.atan2(accum_sin, accum_cos)) + 360.0) % 360.0
            conv_s = accum_s / max(1e-4, total_w)
            conv_v = accum_v / max(1e-4, total_w)

            # Spatial blend with room fill base
            diff_grad = (conv_h - self._l930_avg_hsv[0] + 180) % 360 - 180
            zone_h = (self._l930_avg_hsv[0] + diff_grad * 0.65) % 360.0
            zone_s = max(25.0, min(75.0, self._l930_avg_hsv[1] * 0.4 + conv_s * 0.6))

            # Theme music sound building up intensity + dialogue vocal presence halo
            dist_centre = abs(i - half)
            theme_b = 0.0
            if self._theme_intensity_env > 0.03:
                theme_spread = 0.70 + 0.30 * math.exp(-0.5 * (dist_centre / 14.0) ** 2)
                theme_b = theme_spread * self._theme_intensity_env * 20.0 * audio_factor

            vocal_b = 0.0
            if self._vocal_env > 0.04:
                vocal_halo = math.exp(-0.5 * (dist_centre / 8.5) ** 2)
                vocal_b = vocal_halo * self._vocal_env * 18.0 * audio_factor
                vocal_tint = vocal_halo * self._vocal_env * 0.25 * audio_factor
                diff_vocal = (32.0 - zone_h + 180) % 360 - 180
                zone_h = (zone_h + diff_vocal * vocal_tint) % 360.0

            # Localized column brightness blended with room baseline + theme/vocal intensity
            col_brightness = self.room_level + (conv_v / 100.0) * (self.brightness_cap - self.room_level) * self.screen_influence
            zone_b = int(max(self.room_level, min(self.brightness_cap, max(base_v, col_brightness) + theme_b + vocal_b)))
            segs.append((int(round(zone_h)), int(round(zone_s)), zone_b))

        return segs


# ── 2. PULSE MODE (Concurrent Gaussian Ripples & Beat Swell) ─────────────────

class PulseStyle(VisualStyle):
    """
    Rhythm Mode:
    - L930: Bass kicks launch strong expanding waves from musical phrase origins.
            Snare hits launch sharp counter-pulses; hi-hats create small scattered sparks.
            Wave origins shift in response to musical phrases and bar progression.
    - L900: Beat-synced swell with trailing decay.
    - Internal shared events: Build Tension & Drop Bloom.
    """
    name = "Pulse"

    def __init__(self):
        super().__init__()
        self.ripples: List[Dict[str, Any]] = []
        self._spawn_cooldown: float = 0.0
        self._snare_cooldown: float = 0.0
        self._prev_bar: int = -1
        self._bar_color_idx: int = 0
        self._phrase_step: int = 0
        self._single_b: float = 0.0
        self._single_color: Tuple[int, int, int] = (215, 85, 75)
        self._output_interval_s: float = 0.5

        # Internal shared event layers
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def set_params(self, output_interval_s: Optional[float] = None, **kwargs: Any):
        super().set_params(**kwargs)
        if output_interval_s is not None:
            self._output_interval_s = max(0.125, min(2.0, float(output_interval_s)))

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self.ripples.clear()
            self._single_b = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        self._spawn_cooldown = max(0.0, self._spawn_cooldown - dt)
        self._snare_cooldown = max(0.0, self._snare_cooldown - dt)

        # Musical phrase tracking (advance origin based on bar changes and section age)
        if state.bar_pos != self._prev_bar:
            if state.bar_pos == 0:
                self._bar_color_idx = (self._bar_color_idx + 1) % len(pal)
                self._phrase_step = (self._phrase_step + 1) % 4
            self._prev_bar = state.bar_pos

        cur_color = sample_palette_oklab(
            pal,
            (self._bar_color_idx / float(len(pal))
             + float(getattr(state, "centroid_norm", 0.25)) * 0.18
             + float(getattr(state, "beat_phase", 0.0)) * 0.12) % 1.0,
            cyclic=True,
        )

        # Dynamic Bar & Phrase Origins:
        # bar_pos 0: Center (24.5)
        # bar_pos 1: Left-third (12.0)
        # bar_pos 2: Right-third (37.0)
        # bar_pos 3: Bilateral ends / apex
        half = (num_zones - 1) / 2.0
        BAR_ORIGINS = [half, 12.0, 37.0, half]
        bar_idx = getattr(state, "bar_pos", 0) % 4
        origin = BAR_ORIGINS[bar_idx]

        # 1. Strong expanding wave on Bass Kick / low-frequency punch
        kick_hit = (state.kick > 0.40 and (getattr(state, "is_onset", False) or state.kick > 0.60)) and self._spawn_cooldown <= 0.0
        if kick_hit:
            self._spawn_cooldown = max(0.08, 0.12 / self.speed)
            # Use stable theme palette color; do not jump 55 degrees on every kick
            ripple_color = pal[0] if pal else (215, 95, 95)
            bpm = max(60.0, min(180.0, state.bpm)) if state.bpm_confidence > 0.5 else 120.0
            lifetime = max(0.65, self._output_interval_s * 2.2)
            requested_speed = (50.0 + state.intensity * 45.0) * (bpm / 120.0) * self.speed
            speed_zones_per_sec = min(requested_speed, max(6.0, max(1.0, half) / lifetime))
            init_pos = 0.0
            if getattr(self, "measured_latency_s", 0.0) > 0.0:
                init_pos = min(float(half), speed_zones_per_sec * float(self.measured_latency_s))
            self.ripples.append({
                "type": "kick",
                "origin": origin,
                "pos": init_pos,
                "speed": speed_zones_per_sec,
                "sigma": 3.0 + state.kick * 2.0,  # Broad, strong physical punch
                "life": 1.0,
                "lifetime": lifetime,
                "energy": max(0.70, state.kick),
                "color": ripple_color,
            })

        # 2. Shorter, sharper counter-pulse on Snare hits (originates from opposite end / apex)
        snare_hit = state.snare > 0.45 and self._snare_cooldown <= 0.0
        if snare_hit:
            self._snare_cooldown = max(0.08, 0.12 / self.speed)
            snare_color = pal[(self._bar_color_idx + 2) % len(pal)]
            # Counter-pulse originates symmetrically or opposite to current phrase origin
            snare_origin = (num_zones - 1) - origin if abs(origin - half) > 2.0 else 0.0
            snare_lifetime = max(0.55, self._output_interval_s * 1.75)
            requested_snare_speed = (85.0 + state.intensity * 40.0) * self.speed
            snare_speed = min(requested_snare_speed, max(6.0, max(1.0, half) / snare_lifetime))
            self.ripples.append({
                "type": "snare",
                "origin": snare_origin,
                "pos": 0.0,
                "speed": snare_speed,
                "sigma": 1.5,  # Narrow, crisp shock
                "life": 0.85,
                "lifetime": snare_lifetime,
                "energy": state.snare,
                "color": snare_color,
            })

        if len(self.ripples) > 8:
            self.ripples.pop(0)

        # Update active waves
        alive = []
        for r in self.ripples:
            r["pos"] += r["speed"] * dt
            # Hold wave energy over multiple physical send periods, including 1 Hz fallback.
            lifetime = max(0.4, float(r.get("lifetime", 0.65)))
            r["life"] -= dt / lifetime
            max_dist = max(r.get("origin", half), num_zones - r.get("origin", half)) + 6.0
            if r["pos"] <= max_dist and r["life"] > 0.0:
                alive.append(r)
        self.ripples = alive

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            if getattr(state, "white_strobe", False) or getattr(state, "is_extreme_bass", False):
                return [(0, 0, 100)]
            if kick_hit:
                target_b = (state.energy ** 1.1) * 70.0 + state.kick * 30.0
                self._single_b = max(self._single_b, target_b * self.intensity)
                # Hold hue steady; only advance on downbeat bar changes to eliminate random hue jitter
                self._single_color = pal[self._bar_color_idx % len(pal)]
            elif snare_hit:
                self._single_b = max(self._single_b, state.snare * 80.0 * self.intensity)
            else:
                decay_tau = (0.12 * self.smoothing) / self.speed
                self._single_b *= math.exp(-dt / max(0.01, decay_tau))

            # Pulse drops down cleanly between beats with zero un-reactive baseline
            final_b = int(max(0, min(100, self._single_b)))
            h, s, _ = self._single_color
            frame = [(h, s, final_b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        # ── 50-Zone L930 Mapping ──
        segs: List[Tuple[int, int, int]] = []
        base_h, base_s, _ = pal[0]
        if base_s <= 5:
            base_h, base_s = cur_color[0], cur_color[1]
        bands = state.bands if len(state.bands) >= 50 else np.full(50, state.energy, dtype=np.float32)
        bass_band = float(np.mean(bands[:10]))
        mid_band = float(np.mean(bands[10:35]))
        high_band = float(np.mean(bands[35:]))
        bass_drive = max(float(getattr(state, "bass", 0.0)), bass_band)
        mid_drive = max(float(getattr(state, "mid", 0.0)), mid_band)
        build_drive = max(0.0, float(getattr(state, "energy_trend", 0.0)))
        is_build = (getattr(state, "section", Section.VERSE) == Section.BUILD or build_drive > 0.25)
        build_wash = (build_drive * 25.0 * self.intensity) if is_build else 0.0
        kick_punch = (state.kick * 75.0) * self.intensity

        # Seed pseudo-random hi-hat sparks
        hat_active = state.hat > 0.35
        hat_seed = int((time.time() * 25) % 1000) if hat_active else 0
        has_kick_punch = kick_punch >= 5.0
        has_snare = state.snare > 0.40

        # Deterministic musical role allocations across all 50 ICs:
        # Center (18..31): Lead Vocals, Speech presence & Snare
        # Inner Wings (10..17 & 32..39): Bassline, Keyboards, Rhythm Guitars
        # Outer Wings (3..9 & 40..46): Bass Drum & Sub-Bass Detonations
        # End Caps (0..2 & 47..49): Hi-Hats, Cymbals & Treble Air
        vocal_drive = max(mid_drive, float(getattr(state, "speech_dominance", 0.0)))
        low_mid_drive = float(np.mean(bands[6:16])) if len(bands) >= 16 else mid_drive * 0.8
        sub_bass_drive = float(np.mean(bands[:6])) if len(bands) >= 6 else bass_drive
        effective_interval = float(getattr(self, "_output_interval_s", 0.125))

        # Precompute active ripple parameters outside the 50-zone loop
        active_r_data = []
        for r in self.ripples:
            orig = r.get("origin", half)
            speed = r.get("speed", 50.0)
            sigma = r.get("sigma", 2.0)
            eff_sigma = max(sigma, speed * effective_interval * 0.50)
            peak_b = r["life"] * (50.0 + r.get("energy", 0.5) * 50.0) * self.intensity
            active_r_data.append((
                orig,
                r["pos"],
                eff_sigma,
                3.0 * eff_sigma,
                -0.5 / (max(0.5, eff_sigma) ** 2),
                peak_b,
                r["color"][0],
                r["color"][1],
            ))

        for i in range(num_zones):
            dist_c = abs(i - half) / half  # 0.0 at center (24.5), 1.0 at ends (0, 49)
            accum_b = 0.0
            instrument_b = 0.0

            # 1. Center Core: Lead Vocals, Speech & Melody (Zones 18-31)
            if dist_c < 0.28:
                vocal_halo = math.exp(-0.5 * (dist_c / 0.14) ** 2)
                if vocal_drive > 0.06:
                    instrument_b = (vocal_drive - 0.06) / 0.94 * 85.0 * vocal_halo * self.intensity
                col = pal[1] if len(pal) > 1 else (175, 95, 90)
                chosen_h, chosen_s = col[0], col[1]

            # 2. Inner Wings: Bassline, Chords, Rhythm Synths (Zones 10-17 & 32-39)
            elif dist_c < 0.60:
                wing_d = abs(dist_c - 0.44)
                wing_halo = math.exp(-0.5 * (wing_d / 0.12) ** 2)
                if low_mid_drive > 0.06:
                    instrument_b = (low_mid_drive - 0.06) / 0.94 * 80.0 * wing_halo * self.intensity
                col = pal[0] if len(pal) > 0 else (38, 95, 90)
                chosen_h, chosen_s = col[0], col[1]

            # 3. Outer Wings: Kick Drum & Sub-Bass (Zones 3-9 & 40-46)
            elif dist_c < 0.88:
                bass_d = abs(dist_c - 0.74)
                bass_halo = math.exp(-0.5 * (bass_d / 0.10) ** 2)
                bass_val = max(sub_bass_drive, state.kick)
                if bass_val > 0.08:
                    instrument_b = (bass_val - 0.08) / 0.92 * 95.0 * bass_halo * self.intensity
                col = pal[2] if len(pal) > 2 else (0, 100, 95)
                chosen_h, chosen_s = col[0], col[1]

            # 4. End Caps: Hi-Hats, Cymbals & Air (Zones 0-2 & 47-49)
            else:
                end_d = abs(dist_c - 0.94)
                end_halo = math.exp(-0.5 * (end_d / 0.08) ** 2)
                high_val = max(high_band, state.hat)
                if high_val > 0.10:
                    instrument_b = (high_val - 0.10) / 0.90 * 85.0 * end_halo * self.intensity
                col = pal[3] if len(pal) > 3 else (265, 90, 90)
                chosen_h, chosen_s = col[0], col[1]

            # Add propagating ripple wavefronts from drum kicks
            max_r_b = 0.0
            for orig, r_pos, eff_sigma, cutoff, inv_2_sig_sq, peak_b, r_h, r_s in active_r_data:
                dist = abs(i - orig)
                diff = abs(dist - r_pos)
                if diff > cutoff:
                    continue
                gaussian = math.exp(diff * diff * inv_2_sig_sq)
                r_b = gaussian * peak_b
                if r_b > max_r_b:
                    max_r_b = r_b
                    chosen_h = r_h
                    chosen_s = r_s
                accum_b += r_b

            # Center bass wash during kicks with brilliant punch detonation core
            if has_kick_punch:
                dist_center_norm = abs(i - half) / half
                center_accent = max(0.0, 1.0 - dist_center_norm * 1.5) * kick_punch
                if kick_punch >= 35.0 and dist_center_norm < 0.20:
                    punch_ratio = min(1.0, (kick_punch - 35.0) / 40.0)
                    chosen_s = max(20, int(chosen_s * (1.0 - punch_ratio * 0.70)))
            else:
                center_accent = 0.0

            # Snare hit localized flash boost at center stage
            if has_snare:
                dist_snare = abs(i - half)
                if dist_snare <= 5.0:
                    snare_flash = (1.0 - dist_snare / 5.0) * (state.snare * 75.0) * self.intensity
                    accum_b += snare_flash
                    chosen_s = max(0, chosen_s - int(snare_flash * 0.85))

            # Hi-hat sparks on end caps & outer wings
            if hat_active and dist_c > 0.60:
                spark_hash = ((i + hat_seed) * 2654435761) % 100
                if spark_hash < 32:
                    spark_v = state.hat * 70.0 * self.intensity
                    accum_b += spark_v
                    chosen_s = max(0, chosen_s - int(spark_v * 0.85))

            # Total brightness for this IC
            total_b = accum_b + instrument_b + center_accent
            if is_build:
                dist_mid = abs(dist_c - 0.5)
                total_b += build_wash * max(0.0, 1.0 - dist_mid * 1.5)

            # Inactive zones stay strictly True Black ([0, 0, 0])
            if total_b < 2.5:
                final_b = 0
            else:
                final_b = int(max(0, min(100, total_b)))

            segs.append((chosen_h, chosen_s, final_b))

        # Apply internal shared events: build tension and drop bloom
        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


# ── 3. SPECTRUM & SEGMENTED VU MODES ─────────────────────────────────────────

class SegmentedVUStyle(VisualStyle):
    """
    Segmented VU Visualizer Mode:
    - L930: Multi-Pod Bi-Directional Staccato Blocks (5 instrument pods of 10 ICs each
            expanding from pod centers with floating peak dots and dynamic breaks).
            Also supports layout="unidirectional" (0->49 progression).
    - L900: Smooth single-zone energy & frequency wash.
    - Internal shared events: Build Tension & Drop Bloom.
    """
    name = "SegmentedVU"

    def __init__(self, layout: str = "multi_pod"):
        super().__init__()
        self.layout: str = layout
        self.fill_level: float = 0.0
        self.peak_zone: float = 0.0
        self.peak_hold_timer: float = 0.0
        self.break_offset: int = 0
        self._last_impact_time: float = 0.0
        self._single_level: float = 0.0
        self._output_interval_s: float = 0.5
        self._cached_pal: Optional[Tuple[Tuple[int, int, int], ...]] = None
        self._cached_gradient: List[Tuple[int, int]] = []
        self.pod_levels = [0.0] * 5
        self.pod_peaks = [0.0] * 5
        self.pod_peak_timers = [0.0] * 5

        # Internal shared event layers
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def set_params(self, layout: Optional[str] = None, output_interval_s: Optional[float] = None, **kwargs: Any):
        super().set_params(**kwargs)
        if layout is not None:
            self.layout = layout.strip().lower()
        if output_interval_s is not None:
            self._output_interval_s = max(0.125, min(2.0, float(output_interval_s)))

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self.fill_level = 0.0
            self.peak_zone = 0.0
            self.peak_hold_timer = 0.0
            self.pod_levels = [0.0] * 5
            self.pod_peaks = [0.0] * 5
            self._single_level = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            target_b = (state.energy * 70.0 + state.kick * 30.0) * self.intensity
            tau = 0.015 if target_b > self._single_level else 0.22
            self._single_level = exp_smooth_fast(self._single_level, target_b, dt, tau)

            # Studio VU Ballistic Color: Green -> Yellow -> Red -> White Peak
            lvl = self._single_level / 100.0
            if lvl < 0.38:
                h, s = 135, 95  # Studio VU Green
            elif lvl < 0.72:
                h, s = 45, 95   # Studio VU Amber / Yellow
            elif lvl < 0.92:
                h, s = 0, 100   # Studio VU Crimson Red
            else:
                h, s = 0, 10    # Peak Overload White

            b = int(max(0, min(100, self._single_level)))
            frame = [(h, s, b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        # ── 50-Zone L930 Mapping: Unidirectional Legacy Fallback ──
        if self.layout == "unidirectional":
            pal_tuple = tuple(pal)
            if pal_tuple != self._cached_pal or len(self._cached_gradient) != num_zones:
                self._cached_gradient = [
                    sample_palette_oklab(pal, i / max(1, num_zones - 1))[:2]
                    for i in range(num_zones)
                ]
                self._cached_pal = pal_tuple

            raw_target_zones = (state.energy * 0.65 + state.kick * 0.35) * num_zones * self.intensity
            raw_target_zones = max(0.0, min(float(num_zones), raw_target_zones))

            if raw_target_zones > self.fill_level:
                self.fill_level = exp_smooth_fast(self.fill_level, raw_target_zones, dt, 0.015)
            else:
                self.fill_level = exp_smooth_fast(self.fill_level, raw_target_zones, dt, 0.085 / self.speed)

            if self.fill_level >= self.peak_zone:
                self.peak_zone = self.fill_level
                self.peak_hold_timer = max(0.12, self._output_interval_s * 1.25)
            else:
                if self.peak_hold_timer > 0.0:
                    self.peak_hold_timer = max(0.0, self.peak_hold_timer - dt)
                else:
                    decay_tau = max(0.55, self._output_interval_s * 1.5)
                    self.peak_zone = max(
                        self.fill_level,
                        exp_smooth_fast(self.peak_zone, self.fill_level, dt, decay_tau),
                    )

            now = time.time()
            if (state.hat > 0.45 or state.impact > 0.5) and (now - self._last_impact_time > 0.12):
                self.break_offset = (self.break_offset + 1) % 5
                self._last_impact_time = now

            cur_fill_int = int(math.ceil(self.fill_level))
            peak_idx = int(round(self.peak_zone))

            segs: List[Tuple[int, int, int]] = []
            for i in range(num_zones):
                h, s = self._cached_gradient[i]
                is_break = ((i + self.break_offset) % 5 == 4)
                if is_break and state.snare > 0.7 and state.hat > 0.6:
                    is_break = False

                if i < cur_fill_int:
                    if is_break:
                        b_val = 0
                    else:
                        dist_to_head = abs(i - self.fill_level)
                        b_norm = max(35, 100 - dist_to_head * 2.0)
                        b_val = int(max(0, min(100, b_norm)))
                elif i == peak_idx and peak_idx < num_zones:
                    b_val = 90
                else:
                    b_val = 0
                segs.append((h, s, b_val))

            segs = self._tension.render_accent(state, dt, num_zones, segs)
            segs = self._bloom.render_accent(state, dt, num_zones, segs)
            return segs

        # ── 50-Zone L930 Mapping: Multi-Pod Bi-Directional Staccato Mode (Default) ──
        num_pods = 5
        pod_size = num_zones // num_pods
        segs = [(0, 0, 0)] * num_zones

        if len(self.pod_levels) != num_pods:
            self.pod_levels = [0.0] * num_pods
            self.pod_peaks = [0.0] * num_pods
            self.pod_peak_timers = [0.0] * num_pods

        if len(state.bands) >= 50 and float(np.max(state.bands)) > 0.001:
            bands = state.bands
        else:
            bands = np.full(50, max(state.energy, state.kick * 0.8), dtype=np.float32)

        now = time.time()
        if (state.hat > 0.45 or state.impact > 0.5) and (now - self._last_impact_time > 0.12):
            self.break_offset = (self.break_offset + 1) % 5
            self._last_impact_time = now

        # Deliberate musical instrument frequency band mapping:
        # Pod 0: Sub & Kick (bands 0..5, 20-100 Hz)
        # Pod 1: Bass & Low-Mids (bands 6..15, 100-350 Hz)
        # Pod 2: Mids & Vocals/Guitars (bands 16..27, 350-1500 Hz)
        # Pod 3: Upper Mids & Snare snap (bands 28..38, 1500-5000 Hz)
        # Pod 4: Treble, Air & Hi-Hats (bands 39..49, 5000-16000 Hz)
        POD_BAND_RANGES = [
            (0, 6),
            (6, 16),
            (16, 28),
            (28, 39),
            (39, 50),
        ]
        # Independent attack and release envelope constants per pod:
        # Lower frequencies have slightly longer sustain; treble has snappy instant recovery
        POD_ATTACK_TAUS = [0.012, 0.015, 0.018, 0.012, 0.008]
        POD_RELEASE_TAUS = [0.120, 0.100, 0.085, 0.070, 0.050]
        POD_PEAK_HOLDS = [0.150, 0.130, 0.110, 0.090, 0.070]
        POD_PEAK_FALLS = [12.0, 15.0, 18.0, 22.0, 28.0]

        for p in range(num_pods):
            b_low, b_high = POD_BAND_RANGES[p]
            pod_slice = bands[b_low:b_high]
            raw_e = float(np.mean(pod_slice)) if len(pod_slice) > 0 else 0.0

            # Weight by transient metrics where appropriate (Pod 0 boost on kick, Pod 3 on snare, Pod 4 on hat)
            if p == 0:
                raw_e = max(raw_e, state.kick * 0.9)
            elif p == 3:
                raw_e = max(raw_e, state.snare * 0.85)
            elif p == 4:
                raw_e = max(raw_e, state.hat * 0.80)

            # Noise-floor threshold gating (DAW spectrum pod gate)
            if raw_e < 0.06:
                raw_e = 0.0
            else:
                raw_e = (raw_e - 0.06) / 0.94

            # Square root dynamics expansion
            pod_energy = math.sqrt(max(0.0, raw_e)) * self.intensity
            target_half = min(pod_size / 2.0, pod_energy * (pod_size / 2.0) * 1.6)

            att_tau = POD_ATTACK_TAUS[p]
            rel_tau = (POD_RELEASE_TAUS[p] * self.smoothing) / self.speed

            if target_half > self.pod_levels[p]:
                self.pod_levels[p] = exp_smooth_fast(self.pod_levels[p], target_half, dt, att_tau)
            else:
                self.pod_levels[p] = exp_smooth_fast(self.pod_levels[p], target_half, dt, rel_tau)

            if self.pod_levels[p] < 0.15:
                self.pod_levels[p] = 0.0

            if self.pod_levels[p] >= self.pod_peaks[p]:
                self.pod_peaks[p] = self.pod_levels[p]
                self.pod_peak_timers[p] = max(POD_PEAK_HOLDS[p], self._output_interval_s * 1.30)
            else:
                if self.pod_peak_timers[p] > 0.0:
                    self.pod_peak_timers[p] = max(0.0, self.pod_peak_timers[p] - dt)
                else:
                    decay_tau = max(0.55, self._output_interval_s * 1.60)
                    self.pod_peaks[p] = max(self.pod_levels[p], exp_smooth_fast(self.pod_peaks[p], self.pod_levels[p], dt, decay_tau))

            if self.pod_peaks[p] < 0.25:
                self.pod_peaks[p] = 0.0

            pod_center = p * pod_size + (pod_size - 1) / 2.0
            h, s, _ = sample_palette_oklab(pal, p / float(num_pods - 1))

            cur_half = self.pod_levels[p]
            peak_dist = self.pod_peaks[p]

            for local_i in range(pod_size):
                ic = p * pod_size + local_i
                dist = abs(ic - pod_center)

                is_break = ((ic + self.break_offset) % 5 == 4)
                if is_break and state.snare > 0.7 and state.hat > 0.6:
                    is_break = False

                if is_break:
                    v = 0
                    pod_s = s
                elif dist <= cur_half:
                    falloff = dist / max(0.5, pod_size / 2.0)
                    v = int(max(25, 100 * (1.0 - falloff * 0.40)))
                    pod_s = s
                    # White punch at pod center on heavy percussion
                    if dist <= 0.6 and (state.kick > 0.65 or state.snare > 0.60):
                        pod_s = max(20, int(s * 0.25))
                        v = 100
                elif abs(dist - peak_dist) < 0.65:
                    v = 100
                    pod_s = 10  # Floating diamond white peak dot
                else:
                    v = 0
                    pod_s = s

                segs[ic] = (h, pod_s, v)

        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


class SpectrumStyle(VisualStyle):
    """
    Equalizer Mode:
    - L930: Mirrored 50-band display (bass at centre, treble at ends), peak-hold markers
            (fall time ~600 ms), colour from smooth palette gradient by frequency position.
            Supports layout="mirrored" or layout="segmented" (unidirectional VU with staccato breaks).
    - L900: Smoothed energy wash reflecting overall spectrum balance.
    - Internal shared events: Build Tension & Drop Bloom.
    """
    name = "Spectrum"

    def __init__(self, layout: str = "linear"):
        super().__init__()
        self.layout: str = layout
        self._segmented_delegate = SegmentedVUStyle()
        self.levels = [0.0] * NUM_SEGMENTS
        self.peaks = [0.0] * NUM_SEGMENTS
        self.peak_hold_timers = [0.0] * NUM_SEGMENTS
        self._single_level: float = 0.0
        self._output_interval_s: float = 0.5
        self._cached_pal: Optional[Tuple[Tuple[int, int, int], ...]] = None
        self._cached_gradient: List[Tuple[int, int]] = []

        # Internal shared event layers
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def set_params(self, layout: Optional[str] = None, output_interval_s: Optional[float] = None, **kwargs: Any):
        super().set_params(**kwargs)
        if layout is not None:
            self.layout = layout.strip().lower()
        if output_interval_s is not None:
            self._output_interval_s = max(0.125, min(2.0, float(output_interval_s)))
        self._segmented_delegate.set_params(output_interval_s=self._output_interval_s, **kwargs)

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.layout in ("segmented", "vu", "staccato"):
            return self._segmented_delegate.render(state, dt, num_zones, **kwargs)

        if self.is_silent_state(state):
            self.levels = [0.0] * num_zones
            self.peaks = [0.0] * num_zones
            self._single_level = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        bands = state.bands if len(state.bands) >= 50 else np.full(50, state.energy, dtype=np.float32)

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            if getattr(state, "white_strobe", False) or getattr(state, "is_extreme_bass", False):
                return [(0, 0, 100)]

            # 3-Band Frequency Energy Mapping: Bass (Crimson/Violet 330°), Mids (Warm Gold 42°), Treble (Electric Cyan 190°)
            b_energy = max(0.01, float(np.mean(bands[:12])))
            m_energy = max(0.01, float(np.mean(bands[12:35])))
            t_energy = max(0.01, float(np.mean(bands[35:])))
            total_e = b_energy + m_energy + t_energy

            w_bass = b_energy / total_e
            w_mid = m_energy / total_e
            w_treble = t_energy / total_e

            # Vector sum on color circle:
            # 330° (bass), 42° (mids), 190° (treble)
            rad_b = math.radians(330.0)
            rad_m = math.radians(42.0)
            rad_t = math.radians(190.0)

            vx = w_bass * math.cos(rad_b) + w_mid * math.cos(rad_m) + w_treble * math.cos(rad_t)
            vy = w_bass * math.sin(rad_b) + w_mid * math.sin(rad_m) + w_treble * math.sin(rad_t)
            spec_h = int(math.degrees(math.atan2(vy, vx)) % 360.0)

            target_b = (state.energy * 70.0 + state.kick * 30.0) * self.intensity
            tau = 0.02 if target_b > self._single_level else 0.16
            self._single_level = exp_smooth_fast(self._single_level, target_b, dt, tau)

            b = int(max(0, min(100, self._single_level)))
            frame = [(spec_h, 95, b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        # ── 50-Zone L930 Mapping ──
        if len(self.levels) != num_zones:
            self.levels = [0.0] * num_zones
            self.peaks = [0.0] * num_zones
            self.peak_hold_timers = [0.0] * num_zones

        half = (num_zones - 1) / 2.0
        # Dedicated DAW studio acoustic frequency gradient:
        # Center (Bass) = Deep Flame Red (0, 100), Mids = Warm Gold (42, 95) & Emerald (140, 95), Treble = Electric Cyan (185, 95) & Violet (275, 95)
        if self.palette_mode in ("auto", "dynamic", "spectrum", "frequency") or pal == DEFAULT_PALETTE:
            spec_pal = [(0, 100, 95), (42, 95, 90), (140, 95, 85), (185, 95, 90), (275, 95, 90)]
        else:
            spec_pal = pal

        is_mirrored = (self.layout == "mirrored")
        pal_key = (tuple(spec_pal), self.layout)
        if pal_key != self._cached_pal or len(self._cached_gradient) != num_zones:
            self._cached_gradient = [
                sample_palette_oklab(
                    spec_pal,
                    (abs(i - half) / half) if is_mirrored else (i / float(max(1, num_zones - 1)))
                )[:2]
                for i in range(num_zones)
            ]
            self._cached_pal = pal_key

        segs: List[Tuple[int, int, int]] = []

        for i in range(num_zones):
            # Mirrored: Center (dist=0) -> Bass, Outer edges -> Treble
            # Linear: Zone 0 -> Bass, Zone 49 -> Treble
            if is_mirrored:
                norm_dist = abs(i - half) / half
            else:
                norm_dist = i / float(max(1, num_zones - 1))
            band_idx = min(49, int(norm_dist * 49.0))
            raw_val = float(bands[band_idx])

            # Strict noise-floor threshold gating (DAW heatmap gating): quiet bands drop to True Black
            if raw_val < 0.08:
                raw_target = 0.0
            else:
                band_val = math.sqrt((raw_val - 0.08) / 0.92)
                raw_target = band_val * 100.0 * self.intensity

            # Instant attack (0 delay), snappy responsive decay (75ms * smoothing / speed)
            if raw_target > self.levels[i]:
                self.levels[i] = raw_target
            else:
                self.levels[i] = exp_smooth_fast(self.levels[i], raw_target, dt, (0.075 * self.smoothing) / self.speed)

            # Snap down to true zero when decayed to prevent faint idle glow
            if self.levels[i] < 1.0:
                self.levels[i] = 0.0

            # Keep the transient marker visible at the protected send cadence.
            # At 1 Hz, a 140 ms hold would expire entirely between physical frames.
            if self.levels[i] >= self.peaks[i]:
                self.peaks[i] = self.levels[i]
                self.peak_hold_timers[i] = max(0.14, self._output_interval_s * 1.35)
            else:
                if self.peak_hold_timers[i] > 0.0:
                    self.peak_hold_timers[i] = max(0.0, self.peak_hold_timers[i] - dt)
                else:
                    decay_tau = max(0.55, self._output_interval_s * 1.6)
                    self.peaks[i] = max(self.levels[i], exp_smooth_fast(self.peaks[i], self.levels[i], dt, decay_tau))

            if self.peaks[i] < 1.5:
                self.peaks[i] = 0.0

            # Continuous OKLab palette gradient across strip
            h, s = self._cached_gradient[i]

            # Directed white percussion punches across physical 50 ICs
            kick_val = float(getattr(state, "kick", 0.0))
            snare_val = float(getattr(state, "snare", 0.0))
            hat_val = float(getattr(state, "hat", 0.0))
            if is_mirrored:
                dist_metric = abs(i - half) / half if num_zones > 1 else 0.0
                in_bass = dist_metric < 0.20
                in_mids = 0.25 <= dist_metric <= 0.65
                in_highs = dist_metric > 0.70
            else:
                pos_ratio = i / float(max(1, num_zones - 1)) if num_zones > 1 else 0.0
                in_bass = pos_ratio < 0.25
                in_mids = 0.28 <= pos_ratio <= 0.70
                in_highs = pos_ratio > 0.75

            if kick_val > 0.65 and in_bass:
                punch_w = min(1.0, (kick_val - 0.65) / 0.35)
                s = max(20, int(s * (1.0 - punch_w * 0.70)))
            elif snare_val > 0.55 and in_mids:
                punch_s = min(1.0, (snare_val - 0.55) / 0.45)
                s = max(20, int(s * (1.0 - punch_s * 0.65)))
            elif hat_val > 0.50 and in_highs:
                punch_h = min(1.0, (hat_val - 0.50) / 0.50)
                s = max(20, int(s * (1.0 - punch_h * 0.70)))

            # True dynamic bounce: brightness follows the live bouncing equalizer levels directly!
            # Removes the 95% peak hold floor so the strip drops into high-contrast black valleys between beats.
            b_val = self.levels[i]
            # Floating peak marker dot above the bar for studio VU aesthetic
            if self.peaks[i] > b_val + 12.0 and self.peak_hold_timers[i] > 0.0:
                b_val = max(b_val, self.peaks[i] * 0.85)

            final_b = int(max(0, min(100, b_val)))
            if final_b < 2:
                final_b = 0
            segs.append((h, s, final_b))

        # Apply internal shared events: build tension and drop bloom
        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


# ── 4. FLOW MODE (Noise Curtains & Melody Pitch Glow) ─────────────────────────

class FlowStyle(VisualStyle):
    """
    Organic Flow Mode:
    - L930: 2-octave noise curtains coloured from the palette, speed and brightness scaled
            by energy and local band energy. When harmonic_ratio is high (>0.65), adds Melody
            glow (dominant pitch maps to position, sustained notes spread, ~400 ms falloff).
    - L900: Slow palette wash with organic breathing.
    - Internal shared events: Build Tension & Drop Bloom.
    """
    name = "Flow"

    def __init__(self):
        super().__init__()
        self.phase: float = 0.0
        self._single_phase: float = 0.0
        self.chroma_levels = np.zeros(12, dtype=np.float32)
        self.pitch_sustain = np.zeros(12, dtype=np.float32)

        # Internal shared event layers
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self.chroma_levels.fill(0.0)
            self.pitch_sustain.fill(0.0)
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        speed_factor = (0.35 + state.energy * 0.90 + (1.0 - state.harmonic_ratio) * 0.35) * self.speed
        self.phase += speed_factor * dt

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            self._single_phase += speed_factor * dt * 0.5
            t_col = (math.sin(self._single_phase) * 0.5 + 0.5)
            h, s, _ = sample_palette_oklab(pal, t_col, cyclic=True)
            # WLED standard ballistics: instant attack (<20ms), fluid musical decay, zero quiet floor
            raw_b = (state.energy * 85.0 + (1.0 - state.harmonic_ratio * 0.2) * 15.0 * state.energy) * self.intensity
            tau = 0.02 / self.speed if raw_b > getattr(self, "_single_b", 0.0) else (0.18 * self.smoothing) / self.speed
            self._single_b = exp_smooth_fast(getattr(self, "_single_b", 0.0), raw_b, dt, tau)
            if self._single_b < 1.0:
                self._single_b = 0.0
            frame = [(h, s, int(min(100, self._single_b)))]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        # ── 50-Zone L930 Mapping: 2-Octave Noise Curtains ──
        segs: List[Tuple[int, int, int]] = []
        bands = state.bands if len(state.bands) >= 50 else np.full(50, state.energy, dtype=np.float32)

        # 1. Update Chroma & Melody Tracking (active when harmonic_ratio is high)
        chroma = state.chroma if len(state.chroma) == 12 else np.full(12, 0.08, dtype=np.float32)
        for p in range(12):
            raw_c = chroma[p]
            if raw_c > self.chroma_levels[p]:
                self.chroma_levels[p] = exp_smooth_fast(self.chroma_levels[p], raw_c, dt, 0.04)
                self.pitch_sustain[p] = min(2.0, self.pitch_sustain[p] + dt)
            else:
                # ~400 ms falloff for melody glow
                self.chroma_levels[p] = exp_smooth_fast(self.chroma_levels[p], raw_c, dt, 0.400 / self.speed)
                self.pitch_sustain[p] = max(0.0, self.pitch_sustain[p] - dt * 2.0)

        is_melody_active = (state.harmonic_ratio > 0.65)
        # Polyphonic Pitch Constellation: top 3 active pitches mapped via Circle of Fifths
        top_pitches = []
        pitch_data = []
        if is_melody_active:
            top_pitches = [p for p in np.argsort(self.chroma_levels)[-3:] if self.chroma_levels[p] > 0.12]
            for p in top_pitches:
                p_center = (((p * 7) % 12) / 11.0) * (num_zones - 1)
                sustain = self.pitch_sustain[p]
                sigma = 1.8 + sustain * 2.8
                pitch_data.append((
                    p_center,
                    3.0 * sigma,
                    -0.5 / (max(0.5, sigma) ** 2),
                    self.chroma_levels[p] * 55.0,
                    (p * 30.0 + 15.0) % 360.0,
                ))

        # Multi-frequency dynamic flow:
        # Low frequencies create broad, slow curtains;
        # Mids modulate movement speed and direction (+ or - based on mid balance);
        # High transients briefly disturb and ripple the curtains.
        low_e = float(np.mean(bands[:10])) if len(bands) >= 10 else state.energy
        mid_e = float(np.mean(bands[10:35])) if len(bands) >= 35 else state.energy
        high_e = float(np.mean(bands[35:])) if len(bands) > 35 else state.energy

        # Mids steer the direction and body of the flow
        dir_sign = 1.0 if (mid_e >= low_e * 0.8) else -0.7
        speed_factor = (0.25 + low_e * 0.40 + mid_e * 0.70) * self.speed * dir_sign
        self.phase += speed_factor * dt

        # High transients briefly perturb the flow
        transient_disturbance = (state.hat * 0.6 + state.onset * 0.4) if (state.hat > 0.3 or state.onset > 0.4) else 0.0

        # Cached 16-point LUT for instantaneous palette interpolation
        lut_size = 16
        pal_tuple = tuple(pal)
        if pal_tuple != getattr(self, "_cached_pal", None):
            self._cached_lut = [
                sample_palette_oklab(pal, k / float(lut_size), cyclic=True)
                for k in range(lut_size + 1)
            ]
            self._cached_pal = pal_tuple
        palette_lut = self._cached_lut

        effective_phase = self.phase + speed_factor * self.measured_latency_s
        phase_sin_02 = math.sin(effective_phase * 0.20) * 0.40 + 0.5
        broad_mult = 0.6 + low_e * 0.4
        mid_mult = 0.5 + mid_e * 0.5
        ripple_mult = transient_disturbance * 0.4
        energy_scale = (state.energy * 0.85 + 0.30) * 110.0 * self.intensity

        for i in range(num_zones):
            x = i / float(num_zones - 1)

            # Low frequencies create broad, deep spatial curtains (low spatial frequency)
            broad_curtain = math.sin(x * 2.0 * math.pi + effective_phase * 1.2) * broad_mult
            # Mids create the flowing body (medium spatial frequency)
            mid_body = math.sin(x * 5.0 * math.pi - effective_phase * 2.4) * mid_mult
            # High transients briefly disturb the surface with rapid high-frequency ripples
            high_ripple = math.sin(x * 16.0 * math.pi + effective_phase * 8.0) * ripple_mult

            noise_val = max(0.0, min(1.0, (broad_curtain + mid_body + high_ripple + 2.0) * 0.25))

            # Scale brightness by local frequency energy with square-root lift
            band_e = math.sqrt(max(0.0, float(bands[i])))
            # Dynamic contrast: scale from ambient base up to full brightness
            brightness = (noise_val * 0.45 + band_e * 0.33) * energy_scale

            # Non-linear organic palette sampling via LUT
            t_pal = (noise_val * 0.60 + phase_sin_02) % 1.0
            t_scaled = t_pal * lut_size
            k0 = int(t_scaled)
            frac = t_scaled - k0
            c0 = palette_lut[k0]
            c1 = palette_lut[min(lut_size, k0 + 1)]
            diff_h = ((c1[0] - c0[0] + 180) % 360) - 180
            h = int((c0[0] + frac * diff_h) % 360)
            s = int(c0[1] + frac * (c1[1] - c0[1]))

            # 2. Localized Sustained Note Color Blooms (Polyphonic Pitch Constellation)
            if pitch_data:
                for p_center, cutoff, inv_2_sig, boost_mult, pitch_h in pitch_data:
                    diff = abs(i - p_center)
                    if diff > cutoff:
                        continue
                    gauss = math.exp(diff * diff * inv_2_sig)
                    pitch_boost = gauss * boost_mult
                    brightness = min(100.0, brightness + pitch_boost)
                    if pitch_boost > 12.0:
                        diff_h = (pitch_h - h + 180) % 360 - 180
                        h = int(round((h + diff_h * 0.65) % 360))

            # Crisp transient punch on kick drum core
            dist_center = abs(i - (num_zones - 1) / 2.0)
            if getattr(state, "kick", 0.0) > 0.70 and dist_center < 3.5:
                punch = min(1.0, (state.kick - 0.70) / 0.30)
                s = max(20, int(s * (1.0 - punch * 0.75)))
                brightness = max(brightness, min(100.0, brightness + 45.0 * punch))

            final_b = int(max(0, min(100, brightness)))
            if final_b < 3:
                final_b = 0
            segs.append((h, s, final_b))

        # Apply internal shared events: build tension and drop bloom
        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


# ── Custom Vibe & Genre Engines (Party, Chill, EDM) ──────────────────────────

class PartyStyle(VisualStyle):
    """
    High-energy club/party mode with intentional chaos:
    - Moving, saturated base palette wave.
    - Spawns sparks strictly on fresh onset edges, scaling spark density and speed with treble energy.
    """
    name = "Party"

    def __init__(self):
        super().__init__()
        self._sparks: List[Dict[str, Any]] = []
        self._prev_onset: float = 0.0
        self._last_spark_time: float = 0.0

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._sparks.clear()
            self._prev_onset = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        now = time.time()
        onset_val = float(getattr(state, "onset", 0.0))
        hat_val = float(getattr(state, "hat", 0.0))
        kick_val = float(getattr(state, "kick", 0.0))

        # Fresh onset edge detection: requires rising edge (current > prev + threshold)
        is_fresh_onset = (onset_val > 0.50 and (onset_val - self._prev_onset) > 0.15) or (hat_val > 0.60 and (now - self._last_spark_time) > 0.08)
        self._prev_onset = onset_val

        # Spawn sparks on real onset events, density proportional to treble energy (hat_val)
        if is_fresh_onset and (now - self._last_spark_time) > 0.06:
            self._last_spark_time = now
            spark_count = max(1, min(6, int(1 + hat_val * 5.0)))
            for _ in range(spark_count):
                pos = random.randint(0, max(0, num_zones - 1))
                spark_color = pal[random.randint(0, len(pal) - 1)]
                self._sparks.append({
                    "pos": pos,
                    "life": 1.0,
                    "decay": (4.5 + hat_val * 4.0) * self.speed,
                    "color": spark_color
                })

        # Decay active sparks
        alive_sparks = []
        for s in self._sparks:
            s["life"] -= dt * s["decay"]
            if s["life"] > 0.0:
                alive_sparks.append(s)
        self._sparks = alive_sparks

        # Expose active spark positions for telemetry and backward-compatibility
        self._spark_positions = [s["pos"] for s in self._sparks]
        spark_dict = {s["pos"]: s for s in self._sparks}

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            bar_pos = int(getattr(state, "bar_pos", 0))
            if bar_pos != getattr(self, "_prev_bar_l900", -1):
                self._prev_bar_l900 = bar_pos
                self._color_idx = (getattr(self, "_color_idx", 0) + 1) % len(pal)

            # High-energy chromatic party pops on snare and beats
            if state.snare > 0.55:
                col = pal[(getattr(self, "_color_idx", 0) + 1) % len(pal)]
            else:
                col = pal[getattr(self, "_color_idx", 0) % len(pal)]

            energy_factor = max(0.0, (state.energy - 0.04) / 0.96)
            target_b = (energy_factor * 60.0 + kick_val * 40.0) * self.intensity
            tau = 0.015 / self.speed if target_b > getattr(self, "_single_level", 0.0) else (0.16 * self.smoothing) / self.speed
            self._single_level = exp_smooth_fast(getattr(self, "_single_level", 0.0), target_b, dt, tau)
            if self._single_level < 1.0:
                self._single_level = 0.0
            return [(col[0], col[1], int(np.clip(self._single_level, 0, 100)))]

        segs = []
        half = (num_zones - 1) / 2.0 if num_zones > 1 else 0.5
        beat_phase = float(getattr(state, "beat_phase", 0.0))

        for i in range(num_zones):
            dist_centre = abs(i - half)
            norm_dist = dist_centre / max(1.0, half)

            # High-impact palette color selection tied to beat progression
            h, s, _ = sample_palette_oklab(pal, (norm_dist * 0.45 + beat_phase * 0.35) % 1.0, cyclic=True)

            if i in spark_dict:
                spk = spark_dict[i]
                v = 100  # Staccato peak spark hit
                # Complementary pop
                h = (spk["color"][0] + 120) % 360
                s = max(20, spk["color"][1] - int(spk["life"] * 40))
            elif dist_centre < 6.0 and kick_val > 0.20:
                # Center kick punch (20-29) with brilliant white detonation core
                if kick_val > 0.65 and dist_centre < 3.0:
                    s = max(20, int(s * 0.20))
                    v = 100
                else:
                    v = int((kick_val * 90.0) * (1.0 - dist_centre / 6.0) * self.intensity)
            elif state.snare > 0.40 and abs(dist_centre - 12.0) < 4.0:
                # Mid-wing snare snap (10-19 & 30-39) with bright white/neon snap
                if state.snare > 0.55:
                    s = max(20, int(s * 0.30))
                    v = 100
                else:
                    v = int(state.snare * 80.0 * self.intensity)
            else:
                # Inactive ICs stay strictly True Black ([0, 0, 0])
                v = 0

            segs.append((h, s, max(0, min(100, v))))

        return segs


class ChillStyle(VisualStyle):
    """
    Slow, relaxed lounge/lo-fi mode:
    - Velvety warm lighting without becoming a club effect.
    - Chord changes (chroma shifts) produce slow, smooth palette shifts.
    - Bass beats create soft, localized blooms that ripple gently and fade.
    """
    name = "Chill"

    def __init__(self):
        super().__init__()
        self._smooth_v: float = 30.0
        self._pal_drift_phase: float = 0.0
        self._prev_key_hue: float = 30.0
        self._cur_key_hue: float = 30.0
        self._blooms: List[Dict[str, float]] = []

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._smooth_v = 0.0
            self._blooms.clear()
            return [(0, 0, 0)] * num_zones

        pal = [(32, 85, 80), (22, 90, 85), (345, 60, 75), (45, 50, 90)] if self.palette_mode == "auto" else self.get_palette(state)

        # Chord change tracking: key hue moves smoothly with long tau (1.5s)
        target_hue = float(getattr(state, "key_hue", 30.0))
        diff_h = (target_hue - self._cur_key_hue + 180) % 360 - 180
        alpha_hue = 1.0 - math.exp(-dt / 1.5)
        self._cur_key_hue = (self._cur_key_hue + diff_h * alpha_hue) % 360.0

        # Organic breathing envelope: zero quiet floor for pure negative space
        kick_val = float(getattr(state, "kick", 0.0))
        energy_factor = max(0.0, (state.energy - 0.04) / 0.96) ** 1.1
        target_v = (energy_factor * 75.0) * self.intensity
        alpha_v = 1.0 - math.exp(-dt / ((0.65 * self.smoothing) / self.speed))
        self._smooth_v += alpha_v * (target_v - self._smooth_v)
        if self._smooth_v < 1.0:
            self._smooth_v = 0.0

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            # Soft velvety ambient breathing: zero sudden flashing or strobing, drops cleanly when quiet
            h, s, _ = sample_palette_oklab(pal, (self._cur_key_hue / 360.0) % 1.0, cyclic=True)
            return [(int(h), int(s), int(np.clip(self._smooth_v, 0, 100)))]

        # Bass beats create soft, localized blooms
        if kick_val > 0.35:
            # Spawn a soft bloom centered around apex or quadrant
            if not self._blooms or (time.time() - self._blooms[-1]["t0"] > 0.25):
                half = (num_zones - 1) / 2.0
                bloom_center = half if len(self._blooms) % 2 == 0 else (half * 0.6 if random.random() < 0.5 else half * 1.4)
                self._blooms.append({
                    "center": bloom_center,
                    "radius": 1.0,
                    "intensity": kick_val,
                    "life": 1.0,
                    "t0": time.time(),
                })

        alive_blooms = []
        for b in self._blooms:
            b["radius"] += 14.0 * self.speed * dt
            b["life"] -= dt * (1.8 * self.speed)
            if b["life"] > 0.0:
                alive_blooms.append(b)
        self._blooms = alive_blooms

        self._pal_drift_phase += dt * 0.08 * self.speed
        segs = []
        half = (num_zones - 1) / 2.0 if num_zones > 1 else 0.5

        for i in range(num_zones):
            dist_center = abs(i - half) / max(0.5, half)
            spatial_curve = 1.0 - (dist_center * 0.18)

            # Palette drift influenced by chord changes
            t_pal = (i / float(max(1, num_zones)) * 0.4 + self._pal_drift_phase) % 1.0
            h, s, _ = sample_palette_oklab(pal, t_pal, cyclic=True)
            # Gentle harmonic bias
            h = int((h * 0.80 + self._cur_key_hue * 0.20) % 360)

            # Accumulate localized soft bloom brightness
            bloom_boost = 0.0
            for b in self._blooms:
                dist_b = abs(i - b["center"])
                if dist_b <= b["radius"]:
                    bloom_gauss = math.exp(-0.5 * (dist_b / max(1.5, b["radius"])) ** 2)
                    bloom_boost = max(bloom_boost, bloom_gauss * b["intensity"] * b["life"] * 24.0)

            v_val = self._smooth_v * spatial_curve + bloom_boost
            v = int(max(0, min(85, v_val))) if v_val >= 2.5 else 0
            segs.append((h, s, v))

        return segs


class EdmModeStyle(VisualStyle):
    """
    High-impact EDM mode with colored, progressive dynamics.

    White is only used for a confidently bass-led drop. Ordinary kicks, mids,
    highs, flux and builds shape a continuous palette-driven response. Transient
    envelopes stay alive long enough to survive a protected 1 Hz output cadence.
    """
    name = "EDM"

    def __init__(self):
        super().__init__()
        self.ripples: List[Dict[str, Any]] = []
        self._flash_decay: float = 0.0
        self._last_flash_time: float = 0.0
        self._last_shockwave_time: float = 0.0
        self._prev_kick: float = 0.0
        self._output_interval_s: float = 0.5

    def set_params(self, output_interval_s: Optional[float] = None, **kwargs: Any):
        super().set_params(**kwargs)
        if output_interval_s is not None:
            # Renderer timing follows the existing sender cap; it never changes that cap.
            self._output_interval_s = max(0.125, min(2.0, float(output_interval_s)))

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self.ripples.clear()
            self._flash_decay = 0.0
            self._prev_kick = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        if not pal:
            pal = DEFAULT_PALETTE
        half = (num_zones - 1) / 2.0 if num_zones > 1 else 0.5
        sp = max(0.2, self.speed)
        now = time.time()
        bands = np.asarray(getattr(state, "bands", []), dtype=np.float32).reshape(-1)
        if bands.size:
            bass_band = float(np.mean(bands[:max(1, min(10, bands.size))]))
            mid_band = float(np.mean(bands[10:min(35, bands.size)])) if bands.size > 10 else 0.0
            high_band = float(np.mean(bands[35:])) if bands.size > 35 else 0.0
        else:
            bass_band = mid_band = high_band = 0.0

        kick_val = float(getattr(state, "kick", 0.0))
        onset_val = float(getattr(state, "onset", 0.0))
        impact_val = float(getattr(state, "impact", 0.0))
        energy = float(np.clip(getattr(state, "energy", 0.0), 0.0, 1.0))
        bass_signal = max(float(getattr(state, "bass", 0.0)), bass_band)
        bass_relative = bass_band >= max(0.22, mid_band * 1.12)
        bass_qualified = bass_signal >= 0.50 or bass_relative

        # A pure-white strike requires a clear bass-led transient in a verified drop.
        # Melodic builds and high-frequency sweeps stay colorful even when loud.
        sec_is_drop = getattr(state, "section", Section.SILENT) == Section.DROP
        high_confidence_drop = (
            (sec_is_drop or kick_val >= 0.65) and float(getattr(state, "drop_strength", 0.0)) >= 0.70
            and kick_val >= 0.50 and bass_qualified
        )
        extreme_bass_impact = (
            (impact_val >= 0.80 or kick_val >= 0.70) and bass_qualified
        )
        if (high_confidence_drop or extreme_bass_impact) and (now - self._last_flash_time) > 1.4 and self._flash_decay <= 0.05:
            self._flash_decay = 1.0
            self._last_flash_time = now
        flash_tau = max(0.70, self._output_interval_s * 1.10)
        self._flash_decay *= math.exp(-max(0.0, dt) / flash_tau)
        if self._flash_decay < 0.015:
            self._flash_decay = 0.0

        kick_rising_edge = (kick_val > 0.22) and (kick_val > self._prev_kick + 0.08)
        self._prev_kick = kick_val
        if kick_rising_edge and (now - self._last_shockwave_time) > max(0.12, self._output_interval_s * 0.45):
            self._last_shockwave_time = now
            palette_pos = (
                float(getattr(state, "beat_phase", 0.0)) * 0.24
                + float(getattr(state, "centroid_norm", 0.25)) * 0.28
                + high_band * 0.18
                + bass_signal * 0.30
            ) % 1.0
            ripple_color = sample_palette_oklab(pal, palette_pos, cyclic=True)
            ripple_lifetime = max(1.2, self._output_interval_s * 2.0)
            self.ripples.append({
                "pos": half,
                "speed": (half / max(0.9, self._output_interval_s * 1.6)) * self.speed,
                "radius": 0.0,
                "life": 1.0,
                "lifetime": ripple_lifetime,
                "energy": max(kick_val, onset_val * 0.65),
                "color": ripple_color,
            })

        alive_ripples = []
        for ripple in self.ripples:
            ripple["radius"] += ripple["speed"] * dt
            ripple["life"] -= max(0.0, dt) / max(1.2, float(ripple.get("lifetime", 1.2)))
            if ripple["life"] > 0.0 and ripple["radius"] < num_zones * 1.3:
                alive_ripples.append(ripple)
        self.ripples = alive_ripples

        # Section builds grow from tension, spectral energy trend and section progress;
        # they affect colored brightness rather than pushing the whole strip to white.
        is_build = getattr(state, "section", Section.SILENT) == Section.BUILD
        build_envelope = max(
            float(getattr(state, "tension", 0.0)) if is_build else 0.0,
            float(getattr(state, "section_progress", 0.0)) * 0.70 if is_build else 0.0,
            max(0.0, float(getattr(state, "energy_trend", 0.0))) * 1.6,
        )
        build_envelope = float(np.clip(build_envelope, 0.0, 1.0))
        palette_phase = (
            float(getattr(state, "beat_phase", 0.0)) * 0.18
            + float(getattr(state, "centroid_norm", 0.25)) * 0.32
            + bass_signal * 0.18
            + high_band * 0.16
            + energy * 0.16
        ) % 1.0
        base_v = (
            energy * 10.0 + kick_val * 12.0 + bass_signal * 6.0 + build_envelope * 18.0
        ) * self.intensity
        t_anim = now * 0.35 * self.speed

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            if getattr(state, "white_strobe", False) or getattr(state, "is_extreme_bass", False) or high_confidence_drop or extreme_bass_impact:
                return [(0, 0, 100)]
            elif sec_is_drop or kick_val > 0.35:
                # Saturated four-on-the-floor beat pulses with pure black valleys
                bar_step = int(getattr(state, "bar_pos", 0))
                col = pal[bar_step % len(pal)]
                b = int(np.clip(kick_val * 100.0 * self.intensity, 0, 100))
                return [(col[0], col[1], b)]
            elif is_build or build_envelope > 0.35:
                # Riser build tension: rapid staccato flutter rising towards white with pure black valleys
                strobe_tick = math.sin(now * 26.0 * self.speed) > 0.0
                b = int(np.clip(build_envelope * 100.0 * (1.0 if strobe_tick else 0.0), 0, 100))
                s = int(max(10, 85 - build_envelope * 65.0))
                return [(pal[0][0], s, b)]
            else:
                energy_factor = max(0.0, (energy - 0.04) / 0.96)
                b = int(np.clip(energy_factor * 85.0 * self.intensity, 0, 100))
                return [(pal[0][0], pal[0][1], b)]

        segs = []
        for i in range(num_zones):
            dist_centre = abs(i - half)
            ring_intensity = 0.0
            ring_color = None
            for ripple in self.ripples:
                ring_dist = abs(dist_centre - ripple["radius"])
                if ring_dist < 4.8:
                    intensity_sample = (
                        (1.0 - ring_dist / 4.8) * ripple["life"] * ripple.get("energy", 1.0)
                    )
                    if intensity_sample > ring_intensity:
                        ring_intensity = intensity_sample
                        ring_color = ripple.get("color")

            # Many intermediate palette shades are sampled in OKLab, never RGB primaries.
            palette_pos = (
                i / float(max(1, num_zones)) * 0.30
                + palette_phase + t_anim * 0.025
            ) % 1.0
            h, sat, _ = sample_palette_oklab(pal, palette_pos, cyclic=True)
            wave = 0.5 + 0.5 * math.sin(i * 0.28 - t_anim + onset_val * 0.8)
            colored_base = base_v + wave * (5.0 + high_band * 8.0)

            # 50-IC Directing across Musical Roles
            if ring_intensity > 0.06 and ring_color:
                h, sat = int(ring_color[0]), int(ring_color[1])
                value = ring_intensity * 86.0 * self.intensity
            elif is_build:
                # Progressive build tension illuminates mid-wings and builds toward center
                value = colored_base
            elif dist_centre < 6.0 and kick_val > 0.2:
                # Center ICs (20-29): Bass kick detonation core with trap 808 sub-bass slide
                value = (kick_val * 85.0) * (1.0 - dist_centre / 6.0) * self.intensity
            elif (dist_centre > (half - 6.0)) and high_band > 0.18:
                # Outer edge ICs (0-9 & 40-49): Percussive air & machine-gun trap hi-hat rolls
                # Rapid 32nd-note stutter flutter for trap/metal hi-hats
                roll_tick = math.sin(now * 36.0 * sp + i * 2.1) > 0.15
                value = high_band * (85.0 if roll_tick else 45.0) * self.intensity
                if high_band > 0.40 and roll_tick:
                    sat = max(15, int(sat * 0.25))  # Diamond white sparkles on trap hi-hat rolls
            elif abs(dist_centre - 12.0) < 5.0 and mid_band > 0.22:
                # Mid-wings (10-19 & 30-39): Synth lead, brass stabs & prog rock guitar riffs
                value = mid_band * 65.0 * self.intensity
            else:
                # Inactive ICs stay strictly True Black ([0, 0, 0])
                value = 0.0

            # White remains a qualified bass-drop accent, not the default high-frequency response.
            if self._flash_decay > 0.48 and dist_centre < min(14.0, num_zones * 0.30):
                white_weight = self._flash_decay * math.exp(-0.5 * (dist_centre / max(2.0, half * 0.22)) ** 2)
                sat = int(round(sat * (1.0 - white_weight)))
                value = value + (96.0 - value) * white_weight
            elif kick_val > 0.68 and dist_centre < 5.0:
                # Bass kick white detonation core
                punch_w = min(1.0, (kick_val - 0.68) / 0.32)
                sat = int(round(sat * (1.0 - punch_w * 0.90)))
                value = max(value, min(100.0, value + (100.0 - value) * punch_w))

            final_v = int(round(value))
            if final_v < 3:
                final_v = 0
            segs.append((int(h) % 360, max(0, min(100, int(sat))), min(100, final_v)))

        return segs

# ── LumiSync Spatial Reaction Styles ─────────────────────────────────────────

class BassBounceStyle(VisualStyle):
    """
    Symmetrical inward bass reaction:
    - Sub-bass and kicks drive light filling symmetrically from the outer ends inward toward the center.
    - Creates a continuous brightness gradient at the advancing leading edge rather than a hard block.
    - Active depth follows low-frequency energy dynamically with smooth envelope response.
    - Single-zone fallback (L900): Breathes dynamically with kick punch and bass-energy scale.
    """
    name = "BassBounce"

    def __init__(self):
        super().__init__()
        self._fill_level: float = 0.0

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._fill_level = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        kick_val = float(getattr(state, "kick", 0.0))
        energy = float(getattr(state, "energy", 0.0))
        intensity = self.intensity

        # Low-frequency energy calculation from bands
        if hasattr(state, "bands") and len(state.bands) > 0:
            bass_slice = state.bands[:max(1, len(state.bands) // 8)]
            bass_energy = float(np.mean(bass_slice))
            total_energy = float(np.mean(state.bands)) + 1e-6
            bass_share = float(np.clip(bass_energy / total_energy, 0.0, 1.0))
        else:
            bass_share = float(np.clip(kick_val * 0.7 + energy * 0.3, 0.0, 1.0))

        # Target fill depth [0.0, 1.0] follows low-frequency energy
        raw_fill = (energy * 0.35 + kick_val * 0.65) * math.sqrt(max(0.12, bass_share)) * intensity
        target_fill = float(np.clip(raw_fill, 0.0, 1.0))

        # Smooth envelope: fast attack (50ms), smooth musical decay
        tau = 0.05 / self.speed if target_fill > self._fill_level else (0.22 * self.smoothing) / self.speed
        self._fill_level = exp_smooth_fast(self._fill_level, target_fill, dt, tau)

        # Single-zone L900 fallback
        if num_zones <= 1:
            bar_step = int(getattr(state, "bar_pos", 0))
            col = pal[bar_step % len(pal)] if pal else (215, 85, 75)
            v = int(np.clip(self._fill_level * 100.0, 0, 100))
            return [(col[0], col[1], v)]

        half = (num_zones + 1) / 2.0
        active_reach = self._fill_level * half

        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            edge_dist = min(i, (num_zones - 1) - i)
            norm_pos = edge_dist / max(1.0, half)
            h, s, _ = sample_palette_oklab(pal, norm_pos, cyclic=False)

            # Continuous brightness gradient at the advancing leading edge
            if edge_dist <= active_reach:
                # Advancing gradient: brighter at outer edge / leading wavefront, tapering inward
                head_dist = active_reach - edge_dist
                grad_factor = max(0.40, min(1.0, 1.0 - (edge_dist / max(0.5, active_reach)) * 0.45))
                boost = 1.0 + kick_val * 0.40
                v = int(np.clip(85.0 * boost * intensity * grad_factor, 10, 100))
                # Brilliant white crest flash at the leading advancing bass edge
                if kick_val > 0.65 and abs(edge_dist - active_reach) < 2.2:
                    s = max(0, int(s * 0.15))
                    v = 100
            else:
                # Soft taper past advancing edge, then true black for unreached inner zones
                past_dist = edge_dist - active_reach
                if past_dist > 2.5:
                    v = 0
                else:
                    soft_taper = math.exp(-0.5 * (past_dist / 1.5) ** 2)
                    v = int(np.clip(65.0 * soft_taper * self._fill_level * intensity, 0, 80))

            frame.append((h, s, v))
        return frame


class CenterBurstStyle(VisualStyle):
    """
    Symmetrical outward ripple burst:
    - Transients and kicks launch vivid color ripples from the center outward to both ends.
    - Uses accumulated fractional movement from elapsed time (no forced 1-zone step bug).
    - Spawns waves on fresh onset rising edges rather than repeatedly stamping the center.
    """
    name = "CenterBurst"

    def __init__(self):
        super().__init__()
        self._output_interval_s: float = 0.5
        self._ripples: List[Dict[str, Any]] = []
        self._accum_phase: float = 0.0
        self._single_v: float = 0.0
        self._last_spawn_time: float = 0.0
        self._prev_onset: float = 0.0

    def set_params(self, output_interval_s: Optional[float] = None, **kwargs: Any):
        super().set_params(**kwargs)
        if output_interval_s is not None:
            self._output_interval_s = max(0.125, min(2.0, float(output_interval_s)))

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._ripples.clear()
            self._single_v = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        kick_val = float(getattr(state, "kick", 0.0))
        onset_val = float(getattr(state, "onset", 0.0))
        energy = float(getattr(state, "energy", 0.0))
        now = time.time()

        beat_strength = float(np.clip(kick_val * 0.70 + onset_val * 0.30 + energy * 0.20, 0.0, 1.0))

        # Single-zone L900 fallback
        if num_zones <= 1:
            target_v = beat_strength * 100.0 * self.intensity
            tau = 0.02 / self.speed if target_v > self._single_v else (0.18 * self.smoothing) / self.speed
            self._single_v = exp_smooth_fast(self._single_v, target_v, dt, tau)
            bar_step = int(getattr(state, "bar_pos", 0))
            col = pal[bar_step % len(pal)] if pal else (280, 95, 75)
            return [(col[0], col[1], int(np.clip(self._single_v, 0, 100)))]

        # Spawn outward ripples strictly on fresh onset edges (cooldown >= 90ms)
        is_fresh_onset = (onset_val > 0.45 and (onset_val - self._prev_onset) > 0.12) or (kick_val > 0.50 and (now - self._last_spawn_time) > 0.15)
        self._prev_onset = onset_val

        half = (num_zones - 1) / 2.0
        if is_fresh_onset and (now - self._last_spawn_time) > 0.09:
            self._last_spawn_time = now
            phase = float(getattr(state, "beat_phase", 0.0))
            wave_color = sample_palette_oklab(pal, phase, cyclic=True)
            # Keep the moving ring alive for multiple device sends, while slowing
            # its travel to a distance the hardware can visibly sample.
            lifetime = max(0.70, self._output_interval_s * 2.0)
            requested_speed = (40.0 + kick_val * 35.0) * self.speed
            speed = min(requested_speed, max(5.0, half / lifetime))
            self._ripples.append({
                "radius": 0.0,
                "speed": speed,
                "life": 1.0,
                "lifetime": lifetime,
                "color": wave_color,
                "energy": beat_strength,
                "sigma": 2.5 + kick_val * 1.5,
            })

        # Update ripples using continuous time-accumulated propagation
        alive_ripples = []
        for r in self._ripples:
            r["radius"] += r["speed"] * dt
            lifetime = max(0.5, float(r.get("lifetime", 0.70)))
            r["life"] *= math.exp(-max(0.0, dt) / lifetime)
            if r["life"] > 0.025 and r["radius"] <= half + 4.0:
                alive_ripples.append(r)
        self._ripples = alive_ripples

        segs: List[Tuple[int, int, int]] = []
        ambient_h, ambient_s, _ = pal[0] if pal else (215, 85, 75)
        ambient_b = max(8, int(energy * 20.0 * self.intensity))

        for i in range(num_zones):
            dist_center = abs(i - half)
            accum_v = 0.0
            chosen_h = ambient_h
            chosen_s = ambient_s
            max_r_b = 0.0

            for r in self._ripples:
                diff = abs(dist_center - r["radius"])
                gauss = math.exp(-0.5 * (diff / max(0.5, r["sigma"])) ** 2)
                r_v = gauss * r["life"] * r["energy"] * 95.0 * self.intensity
                if r_v > max_r_b:
                    max_r_b = r_v
                    chosen_h = r["color"][0]
                    chosen_s = r["color"][1]
                    # Pure white detonation core at center on heavy kicks
                    if kick_val > 0.65 and dist_center < 3.0:
                        chosen_s = max(0, int(chosen_s * 0.10))
                accum_v += r_v

            # Center kick punch (22-27)
            if dist_center <= 3.5:
                center_glow = (3.5 - dist_center) / 3.5 * kick_val * 65.0 * self.intensity
                accum_v += center_glow

            # Inactive zones stay strictly True Black ([0, 0, 0])
            if accum_v < 2.5:
                final_b = 0
            else:
                final_b = int(max(0, min(100, accum_v)))
            segs.append((chosen_h, chosen_s, final_b))

        return segs


class TwinkleStyle(VisualStyle):
    """
    Event-driven Sparkle & Ambient Glow:
    - Sparkles vary in position, duration, and density based on high-frequency transients.
    - Background remains dim (~8-15%), so each sparkle blooms and fades independently.
    - Single-zone fallback (L900): Soft ambient glow with treble micro-shimmers.
    """
    name = "Twinkle"

    def __init__(self):
        super().__init__()
        self._active_sparkles: List[Dict[str, Any]] = []
        self._prev_hat: float = 0.0
        self._last_spawn_time: float = 0.0

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._active_sparkles.clear()
            self._prev_hat = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        hat_val = float(getattr(state, "hat", 0.0))
        energy = float(getattr(state, "energy", 0.0))
        onset_val = float(getattr(state, "onset", 0.0))
        now = time.time()

        # Single-zone L900 fallback
        if num_zones <= 1:
            is_sparkle = (hat_val > 0.28 and (hat_val - self._prev_hat > 0.08)) or (onset_val > 0.45 and hat_val > 0.25)
            self._prev_hat = hat_val
            if is_sparkle:
                # Diamond ice-white / champagne shimmer flash on treble transients
                h = int(getattr(state, "key_hue", 45)) if random.random() < 0.45 else 210
                s = random.randint(0, 25)
                b = int(np.clip((65.0 + hat_val * 35.0) * self.intensity, 0, 100))
            else:
                h, s, _ = pal[0] if pal else (225, 80, 75)
                b = int(np.clip(energy * 35.0 * self.intensity, 0, 100))
            return [(h, s, b)]

        # Spawn real event-driven sparkles on high-frequency transients / hat hits
        is_treble_transient = (hat_val > 0.28 and (hat_val - self._prev_hat) > 0.08) or (onset_val > 0.50 and hat_val > 0.35)
        self._prev_hat = hat_val

        if is_treble_transient and (now - self._last_spawn_time) > 0.04:
            self._last_spawn_time = now
            # Sparkle density scales with treble transient energy
            count = max(1, min(7, int(1 + hat_val * 6.0)))
            for _ in range(count):
                idx = random.randint(0, num_zones - 1)
                duration = random.uniform(0.12, 0.35) / max(0.5, self.speed)
                spk_hue = (int(getattr(state, "key_hue", 180)) + random.choice([0, 45, 90, 180])) % 360
                self._active_sparkles.append({
                    "pos": idx,
                    "life": 1.0,
                    "duration": duration,
                    "color": (spk_hue, random.randint(5, 30), 100),
                })

        # Update active sparkles independently
        alive_sparkles = []
        for s in self._active_sparkles:
            s["life"] -= dt / max(0.01, s["duration"])
            if s["life"] > 0.0:
                alive_sparkles.append(s)
        self._active_sparkles = alive_sparkles

        # Keep background dim (~8-18%)
        dim_ambient_v = int(max(6, min(20, (8.0 + energy * 18.0) * self.intensity)))
        t_drift = now * 0.08 * self.speed
        frame: List[Tuple[int, int, int]] = []

        sparkle_map: Dict[int, float] = {}
        sparkle_col_map: Dict[int, Tuple[int, int]] = {}
        for spk in self._active_sparkles:
            pos = spk["pos"]
            # Bloom and fade envelope: peak immediately or upon bloom, decaying smoothly
            life = max(0.0, min(1.0, spk["life"]))
            # High-luminance micro-sparkle (50-100% brightness)
            b_val = (30.0 + 70.0 * (life ** 0.8)) * self.intensity
            if b_val > sparkle_map.get(pos, 0.0):
                sparkle_map[pos] = b_val
                sparkle_col_map[pos] = (spk["color"][0], spk["color"][1])

        for i in range(num_zones):
            if i in sparkle_map:
                h, s = sparkle_col_map[i]
                v = int(min(100, sparkle_map[i]))
                frame.append((h, s, v))
            else:
                # Deep velvet space: inactive zones remain True Black between sparkles
                frame.append((0, 0, 0))

        return frame


class AcousticStringStyle(VisualStyle):
    """
    Acoustic String Resonator / Harmonic Standing Wave:
    Simulates a vibrating guitar/piano string. The center of the strip vibrates with
    low-mid notes, while fret/pluck transients send ripple pulses toward both ends.
    Intensity maps to acoustic sustain. Best for indie, acoustic, guitar, piano, vocals.
    """
    def __init__(self):
        super().__init__()
        self._phase: float = 0.0
        self._sustain: float = 0.0
        self._ripples: List[Tuple[float, float, float]] = []  # (pos, vel, life)

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._ripples.clear()
            self._sustain = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        energy = float(getattr(state, "energy", 0.0))
        bass = float(getattr(state, "bass", 0.0))
        mid = float(getattr(state, "mid", 0.0))
        transient = float(getattr(state, "transient", 0.0))

        # Sustain envelope
        target_sustain = max(energy, mid * 0.9)
        tau = 0.15 if target_sustain > self._sustain else 0.8
        self._sustain = exp_smooth_fast(self._sustain, target_sustain, dt, tau)

        # String oscillation frequency modulated by pitch/mids
        self._phase += dt * (4.0 + mid * 6.0) * self.speed

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            is_pluck = transient > 0.45 or (getattr(state, "onset", 0.0) > 0.50 and transient > 0.30)
            pal_pos = (self._sustain * 0.45 + energy * 0.25) % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=False)
            vibration = abs(math.sin(self._phase))
            amp = (0.20 + 0.80 * self._sustain) * (0.65 + 0.35 * vibration)
            if is_pluck:
                amp = max(amp, 0.95)
                s = max(15, int(s * 0.45))  # Bright metallic pluck shimmer
            b = int(np.clip(amp * 100.0 * self.intensity, 0, 100))
            return [(h, s, b)]

        # Pluck trigger launches a traveling string wave from picking zone (e.g. zone 12)
        if transient > 0.45:
            pick_origin = (10.0 + (transient * 15.0)) % float(max(1, num_zones - 1))
            self._ripples.append((pick_origin, (24.0 + transient * 32.0) * self.speed, 1.0))

        # Update traveling ripples with physical string boundary reflection at ends
        updated_ripples = []
        for pos, vel, life in self._ripples:
            new_pos = pos + vel * dt
            new_life = life - dt * 2.0
            if new_pos >= num_zones - 1:
                new_pos = num_zones - 1
                vel = -abs(vel) * 0.75  # Wave reflection off bridge!
            elif new_pos <= 0.0:
                new_pos = 0.0
                vel = abs(vel) * 0.75   # Wave reflection off nut!
            if new_life > 0.0:
                updated_ripples.append((new_pos, vel, new_life))
        self._ripples = updated_ripples

        half = (num_zones - 1) / 2.0
        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            x = (i - half) / max(1.0, half)  # -1.0 to 1.0
            # Fundamental standing wave: zero at ends, maximum in center
            fundamental = math.cos(x * (math.pi / 2.0)) * math.sin(self._phase)
            # Harmonic overtone
            overtone = math.sin(x * math.pi) * math.sin(self._phase * 2.0) * 0.5
            vibration = abs(fundamental + overtone * 0.6)

            # Check traveling ripple along physical string coordinate
            ripple_val = 0.0
            for r_pos, _, r_life in self._ripples:
                d = abs(i - r_pos)
                if d < 3.2:
                    ripple_val = max(ripple_val, (1.0 - d / 3.2) * r_life)

            amp = (0.2 + 0.8 * self._sustain) * (0.4 + 0.6 * vibration) + ripple_val * 0.6
            v = int(np.clip((12.0 + amp * 88.0) * self.intensity, 5, 100))

            # OKLab palette sampling along string
            pal_pos = (abs(x) * 0.5 + self._sustain * 0.3) % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=False)
            if ripple_val > 0.5:
                s = max(0, int(s * 0.15))  # Pure white metallic sparkle on pluck
                v = 100
            elif ripple_val > 0.2:
                s = max(10, int(s * 0.5))  # Shimmer on pluck

            frame.append((h, s, v))
        return frame


class HydroAcousticStyle(VisualStyle):
    """
    Hydro-Acoustic Shockwave & Spray:
    Low-frequency kicks trigger hydraulic displacement expanding outward from center.
    High-frequency percussion (hi-hats, snares) creates randomized sparkling water droplets
    on the outer extremities. Best for hip-hop, R&B, modern pop.
    """
    def __init__(self):
        super().__init__()
        self._waves: List[Tuple[float, float, float]] = []  # (radius, velocity, strength)
        self._droplets: List[float] = [0.0] * NUM_SEGMENTS

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._waves.clear()
            self._droplets = [0.0] * len(self._droplets)
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        kick = float(getattr(state, "kick", 0.0))
        hat = float(getattr(state, "hat", 0.0))
        bass = float(getattr(state, "bass", 0.0))

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            is_hydraulic_surge = kick > 0.45 or bass > 0.50
            if is_hydraulic_surge:
                h = 175  # Luminous turquoise surge on kick
                s = 85
                b = int(np.clip((kick * 75.0 + bass * 35.0) * self.intensity, 0, 100))
            elif hat > 0.35:
                h = 190  # Sparkling seafoam droplet on hi-hat
                s = max(15, int(70 - hat * 50.0))
                b = int(np.clip((hat * 65.0 + getattr(state, "energy", 0.0) * 25.0) * self.intensity, 0, 100))
            else:
                h = 215  # Deep marine blue baseline
                s = 90
                b = int(np.clip((bass * 30.0 + getattr(state, "energy", 0.0) * 25.0) * self.intensity, 0, 100))
            return [(h, s, b)]

        # Kick produces hydraulic expanding shockwave
        if kick > 0.5:
            self._waves.append((0.0, (14.0 + kick * 20.0) * self.speed, kick))

        # Update shockwaves
        updated_waves = []
        for r, v, str_val in self._waves:
            new_r = r + v * dt
            new_str = str_val - dt * 1.8
            if new_str > 0.0 and new_r < (num_zones / 2.0 + 8.0):
                updated_waves.append((new_r, v, new_str))
        self._waves = updated_waves

        # Hi-hat percussion produces droplets at the outer 25% of both sides
        decay = math.exp(-dt * 4.0)
        for i in range(len(self._droplets)):
            self._droplets[i] *= decay

        if hat > 0.4:
            count = int(1 + hat * 4)
            for _ in range(count):
                if random.random() < 0.5:
                    idx = random.randint(0, int(num_zones * 0.25))
                else:
                    idx = random.randint(int(num_zones * 0.75), num_zones - 1)
                if idx < len(self._droplets):
                    self._droplets[idx] = max(self._droplets[idx], hat)

        half = (num_zones - 1) / 2.0
        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            dist = abs(i - half)
            wave_amp = 0.0
            for r, _, s_val in self._waves:
                dr = abs(dist - r)
                if dr < 3.5:
                    wave_amp = max(wave_amp, (1.0 - dr / 3.5) * s_val)

            drop_val = self._droplets[i] if i < len(self._droplets) else 0.0
            center_pool = (max(0.0, 1.0 - dist / 4.5) * bass * 60.0) if dist <= 4.5 else 0.0
            active_signal = wave_amp * 80.0 + drop_val * 70.0 + center_pool
            if active_signal < 3.0:
                total_v = 0
            else:
                total_v = int(np.clip(active_signal * self.intensity, 0, 100))

            pal_pos = (dist / max(1.0, half)) * 0.7
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=False)
            if kick > 0.65 and dist < 3.5:
                # Hydraulic cavitation white detonation at center
                s = max(0, int(s * 0.10))
                total_v = 100
            elif drop_val > 0.4:
                s = max(0, int(s * 0.15))  # Pure white seafoam droplet sparkle
            elif drop_val > 0.2:
                s = max(5, int(s * 0.3))  # Seafoam / sparkling droplet
            frame.append((h, s, total_v))
        return frame




class LofiVinylStyle(VisualStyle):
    """
    Lofi Vinyl Glow & Drift:
    Ultra-warm analog glow (warm amber / vintage gold). Subtle energy swells pulse gently
    with rhythm, while subtle micro-flickers mimic the crackle of a vinyl record.
    Never drops to zero; stays comforting and ambient.
    Best for lofi hip hop, jazz, chillout study sessions.
    """
    def __init__(self):
        super().__init__()
        self._crackle: List[float] = [0.0] * NUM_SEGMENTS
        self._phase: float = 0.0
        self._swell: float = 0.0

    def get_palette(self, state: MusicState) -> List[Tuple[int, int, int]]:
        if self._preset_palette:
            return self._preset_palette
        if state.palette and state.palette != DEFAULT_PALETTE:
            return state.palette
        return [(35, 82, 80), (28, 88, 75), (42, 78, 85)]

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._swell = 0.0
            self._crackle = [0.0] * len(self._crackle)
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        energy = float(getattr(state, "energy", 0.0))
        bass = float(getattr(state, "bass", 0.0))

        # Smooth analog swell
        target_swell = 0.25 + energy * 0.45 + bass * 0.3
        self._swell = exp_smooth_fast(self._swell, target_swell, dt, 0.4)
        self._phase += dt * 0.25 * self.speed

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            drift = 0.5 + 0.5 * math.sin(self._phase)
            crackle = random.uniform(-0.06, 0.08) if random.random() < 0.35 else 0.0
            val = self._swell * (0.85 + 0.15 * drift) + crackle
            b = int(np.clip(val * 85.0 * self.intensity, 0, 100))
            pal_pos = (drift * 0.35 + self._swell * 0.25) % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=False)
            return [(h, s, b)]

        # Vinyl micro-crackle: rare, localized analog fluctuations
        decay = math.exp(-dt * 6.0)
        for i in range(len(self._crackle)):
            self._crackle[i] *= decay
            if random.random() < 0.04:
                self._crackle[i] = random.uniform(-0.15, 0.25)

        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            x = i / float(max(1, num_zones - 1))
            drift = 0.5 + 0.5 * math.sin(self._phase + x * 2.5)
            crackle_val = self._crackle[i] if i < len(self._crackle) else 0.0

            val = self._swell * (0.8 + 0.2 * drift) + crackle_val
            v = int(np.clip((18.0 + val * 65.0) * self.intensity, 12, 90))

            pal_pos = (x * 0.4 + drift * 0.3) % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=False)
            frame.append((h, s, v))
        return frame


class MelodicContourStyle(VisualStyle):
    """
    Melodic Contour Ribbon:
    Rather than a static VU meter, the spatial position of the illuminated segment
    follows the melodic pitch centroid. Loudness controls ribbon width and glow radius.
    Best for classical, instrumental, synthwave, progressive rock.
    """
    def __init__(self):
        super().__init__()
        self._pos: float = 24.5
        self._width: float = 6.0
        self._vel: float = 0.0

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._vel = 0.0
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        energy = float(getattr(state, "energy", 0.0))
        centroid = float(getattr(state, "centroid_norm", getattr(state, "spectral_centroid", 0.5)))
        if centroid <= 0.0 or centroid > 1.0:
            centroid = 0.5

        # Target position on strip
        target_pos = centroid * (num_zones - 1)
        target_width = 4.0 + energy * 12.0

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            # Pitch centroid guides the room's color continuously along the melodic scale
            pal_pos = centroid % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=True)
            b = int(np.clip((energy * 85.0 + (1.0 - getattr(state, "harmonic_ratio", 0.5) * 0.2) * 15.0 * energy) * self.intensity, 0, 100))
            return [(h, s, b)]

        # Physical tracking with smooth spring damper
        self._pos = exp_smooth_fast(self._pos, target_pos, dt, 0.12)
        self._width = exp_smooth_fast(self._width, target_width, dt, 0.20)

        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            dist = abs(i - self._pos)
            glow = math.exp(-0.5 * (dist / max(1.5, self._width * 0.45)) ** 2)

            base_floor = 6.0
            v = int(np.clip((base_floor + glow * (30.0 + energy * 64.0)) * self.intensity, 4, 100))

            pal_pos = (self._pos / float(max(1, num_zones - 1))) % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_pos, cyclic=True)
            # Brilliant white melodic peak cursor at leading pitch note
            if dist < 1.6 and energy > 0.60:
                s = max(20, int(s * 0.30))
                v = 100
            frame.append((h, s, v))
        return frame


class BpmResonatorStyle(VisualStyle):
    """
    BPM Resonator:
    True beat-synchronized multi-harmonic standing and traveling wave resonator.
    Timing is driven directly by detected musical tempo (bpm), continuous PLL beat phase (beat_phase),
    and bar downbeats (bar_pos).
    Sub-harmonics (0.5x half-time), fundamentals (1x beat), and upper harmonics (2x, 4x sixteenths)
    interfere constructively across zones, with kick and bass transients exciting resonant ripples.
    """
    name: str = "BPM Resonator"

    def __init__(self):
        super().__init__()
        self.name = "BPM Resonator"
        self._local_phase: float = 0.0
        self._resonator_energy: float = 0.0

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._resonator_energy = 0.0
            return [(0, 0, 0)] * num_zones

        energy = float(getattr(state, "energy", 0.0))
        kick = float(getattr(state, "kick", 0.0))
        bass = float(getattr(state, "bass", 0.0))
        transient = float(getattr(state, "transient", 0.0))

        target_resonance = max(energy, kick * 1.2, bass * 1.0)
        if target_resonance > self._resonator_energy:
            # Immediate attack on musical transient
            self._resonator_energy = target_resonance
        else:
            # Smooth exponential decay
            self._resonator_energy = exp_smooth_fast(self._resonator_energy, target_resonance, dt, 0.35)

        # Strictly dark during quiet passages; never glow or cycle autonomously
        if self._resonator_energy < 0.03 and energy < 0.02:
            return [(0, 0, 0)] * num_zones

        pal = self.get_palette(state)
        bpm = float(getattr(state, "bpm", 120.0) or 120.0)
        beat_phase = float(getattr(state, "beat_phase", 0.0))
        bar_pos = int(getattr(state, "bar_pos", 0))

        tempo_freq = (bpm / 60.0) * self.speed
        bpm_conf = float(getattr(state, "bpm_confidence", 0.0))
        if bpm_conf > 0.2:
            phi_beat = (bar_pos + beat_phase) * 0.25 * 2.0 * math.pi
        else:
            self._local_phase = (self._local_phase + dt * tempo_freq * 2.0 * math.pi) % (8.0 * math.pi)
            phi_beat = self._local_phase

        # Multi-harmonic standing wave frequencies
        h1 = math.sin(phi_beat * 1.0)
        h_sub = math.cos(phi_beat * 0.5)
        h2 = math.sin(phi_beat * 2.0)
        h4 = math.cos(phi_beat * 4.0)

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            downbeat_accent = 1.30 if (bar_pos == 0 and beat_phase < 0.25) else (0.85 if bar_pos == 2 and beat_phase < 0.25 else 0.55)
            beat_pulse = math.exp(-beat_phase * 3.2)
            val_norm = (beat_pulse * 0.70 + 0.30) * self._resonator_energy * downbeat_accent
            b = int(np.clip(val_norm * 100.0 * self.intensity, 0, 100))
            pal_t = ((bar_pos * 0.25) + beat_phase * 0.08) % 1.0
            h, s, _ = sample_palette_oklab(pal, pal_t, cyclic=True)
            if kick > 0.65:
                s = max(10, int(s * 0.55))
            return [(h, s, b)]

        # Precompute 16-point LUT for instantaneous palette interpolation
        lut_size = 16
        palette_lut = [sample_palette_oklab(pal, k / float(lut_size), cyclic=True) for k in range(lut_size + 1)]

        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            x = i / float(max(1, num_zones - 1))
            w_fund = math.sin(x * 2.0 * math.pi + h1) * 0.35
            w_sub = math.cos(x * math.pi + h_sub) * 0.30
            w_fast = math.sin(x * 4.0 * math.pi + h2) * 0.20
            w_ripple = math.cos(x * 8.0 * math.pi + h4 * 0.5) * 0.15

            wave = (w_fund + w_sub + w_fast + w_ripple + 1.0) * 0.5

            downbeat_accent = 1.25 if (bar_pos == 0 and beat_phase < 0.25) else 1.0
            val_norm = wave * self._resonator_energy * downbeat_accent
            v = int(np.clip(val_norm * 100.0 * self.intensity, 0, 100))

            pal_t = (wave * 0.6 + phi_beat / (2.0 * math.pi) * 0.15 + transient * 0.25) % 1.0
            t_scaled = pal_t * lut_size
            k0 = int(t_scaled)
            frac = t_scaled - k0
            c0 = palette_lut[k0]
            c1 = palette_lut[min(lut_size, k0 + 1)]
            diff_h = ((c1[0] - c0[0] + 180) % 360) - 180
            h = int((c0[0] + frac * diff_h) % 360)
            s = int(c0[1] + frac * (c1[1] - c0[1]))
            if kick > 0.65 and abs(i - (num_zones / 2.0)) < 4.5:
                s = max(20, int(s * 0.25))
                v = 100
            elif kick > 0.50 and abs(i - (num_zones / 2.0)) < 6:
                s = max(20, int(s * 0.6))
                v = min(100, int(v * 1.2))

            frame.append((h, s, v))

        return frame


class RandomChainReactionStyle(VisualStyle):
    """
    Beat-locked stochastic IC bursts with a living electrical chain reaction.
    Transients ignite scattered ICs; neighboring zones can catch the spark, but
    no effect is forced to travel from one end of the strip to the other.
    Each zone has its own smooth attack/decay envelope and retained hue.
    """
    name = "Random Chain Reaction"

    def __init__(self):
        super().__init__()
        self._levels = [0.0] * NUM_SEGMENTS
        self._hues = [(185, 95)] * NUM_SEGMENTS
        self._prev_onset = 0.0
        self._prev_hat = 0.0
        self._prev_phase = 0.0
        self._beat_flash = 0.0
        self._chain_budget = 0.0
        self._rng = random.Random()

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs) -> List[Tuple[int, int, int]]:
        if num_zones <= 0:
            return []
        if self.is_silent_state(state):
            self._levels = [0.0] * num_zones
            self._prev_onset = 0.0
            self._prev_hat = 0.0
            return [(0, 0, 0)] * num_zones

        if len(self._levels) != num_zones:
            self._levels = [0.0] * num_zones
            self._hues = [(185, 95)] * num_zones

        pal = self.get_palette(state)
        kick = float(np.clip(getattr(state, "kick", 0.0), 0.0, 1.0))
        snare = float(np.clip(getattr(state, "snare", 0.0), 0.0, 1.0))
        hat = float(np.clip(getattr(state, "hat", 0.0), 0.0, 1.0))
        onset = float(np.clip(getattr(state, "onset", 0.0), 0.0, 1.0))
        transient = float(np.clip(getattr(state, "transient", 0.0), 0.0, 1.0))
        energy = float(np.clip(getattr(state, "energy", 0.0), 0.0, 1.0))
        phase = float(np.clip(getattr(state, "beat_phase", 0.0), 0.0, 1.0))
        bpm_conf = float(getattr(state, "bpm_confidence", 0.0))

        # A wrapped phase is a beat edge. Onsets remain useful for syncopated notes.
        beat_edge = (
            bpm_conf >= 0.25
            and self._prev_phase > 0.68
            and phase < 0.32
        )
        fresh_onset = onset > 0.30 and onset - self._prev_onset > 0.045
        fresh_hat = hat > 0.30 and hat - self._prev_hat > 0.10
        self._prev_phase = phase
        self._prev_onset = onset
        self._prev_hat = hat

        # Beat makes a broad energetic ignition; individual transients create
        # smaller, scattered note sparks between beats.
        if beat_edge or kick > 0.52:
            count = 4 + int(kick * 5) + int(energy * 2)
            strength = max(0.58, kick, energy * 0.75)
            self._beat_flash = max(self._beat_flash, strength)
        elif fresh_onset or transient > 0.52:
            count = 2 + int(transient * 3)
            strength = max(0.35, transient, onset * 0.75)
        elif fresh_hat:
            count = 1 + int(hat * 2)
            strength = max(0.22, hat * 0.75)
        else:
            count = 0
            strength = 0.0

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            if strength > 0.0:
                self._beat_flash = max(self._beat_flash, strength)
                hue_pos = (phase * 0.35 + self._rng.random() * 0.65) % 1.0
                h, s, _ = sample_palette_oklab(pal, hue_pos, cyclic=True)
                self._hues[0] = (h, max(45, s))
            self._beat_flash *= math.exp(-max(0.0, dt) / (0.16 / max(0.5, self.speed)))
            h, s = self._hues[0]
            v = int(np.clip((self._beat_flash * 85.0 + energy * 20.0) * self.intensity, 0, 100))
            if self._beat_flash > 0.65:
                s = max(20, int(s * 0.70))
            return [(int(h) % 360, int(np.clip(s, 0, 100)), v)]

        if count:
            # Random scatter is intentionally non-contiguous. Stronger events
            # ignite more ICs, and bass hits leave a longer afterglow.
            for _ in range(min(count, max(1, num_zones // 2))):
                idx = self._rng.randrange(num_zones)
                hue_pos = (
                    float(getattr(state, "beat_phase", 0.0)) * 0.20
                    + float(getattr(state, "centroid_norm", 0.5)) * 0.35
                    + self._rng.random() * 0.65
                ) % 1.0
                h, s, _ = sample_palette_oklab(pal, hue_pos, cyclic=True)
                self._levels[idx] = max(self._levels[idx], min(1.0, strength * self._rng.uniform(0.78, 1.0)))
                self._hues[idx] = (h, max(45, s))

        # Chain reactions are local and stochastic: a live spark may jump one
        # or two neighboring ICs, with probability driven by current audio.
        live = [i for i, level in enumerate(self._levels) if level > 0.30]
        chain_probability = min(0.42, 0.08 + energy * 0.18 + transient * 0.22)
        if live and self._rng.random() < chain_probability:
            seed = self._rng.choice(live)
            neighbors = [j for j in (seed - 1, seed + 1) if 0 <= j < num_zones]
            self._rng.shuffle(neighbors)
            for idx in neighbors[:self._rng.randint(1, min(2, len(neighbors)))] if neighbors else []:
                if self._rng.random() < 0.72:
                    h, s = self._hues[seed]
                    self._levels[idx] = max(self._levels[idx], self._levels[seed] * self._rng.uniform(0.55, 0.82))
                    self._hues[idx] = (int((h + self._rng.choice([-18, -8, 8, 18])) % 360), s)

        # Smooth, rate-independent envelope: crisp note attack, fluid afterglow.
        # Beat pulse follows tempo but never turns the whole strip into a wash.
        self._beat_flash *= math.exp(-max(0.0, dt) / (0.16 / max(0.5, self.speed)))
        decay_tau = (0.24 + kick * 0.16) * self.smoothing / max(0.5, self.speed)
        attack_tau = 0.025 / max(0.5, self.speed)
        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            target = self._levels[i]
            tau = attack_tau if target > 0.0 else decay_tau
            self._levels[i] = exp_smooth_fast(self._levels[i], target, dt, tau)
            # Every IC decays independently, so the result has motion and
            # afterglow without a hard left-to-right wipe.
            self._levels[i] *= math.exp(-max(0.0, dt) / max(0.08, decay_tau))
            if self._levels[i] < 0.012:
                self._levels[i] = 0.0
            h, s = self._hues[i]
            local = self._levels[i]
            v = int(np.clip((local * (72.0 + kick * 24.0) + self._beat_flash * 9.0) * self.intensity, 0, 100))
            if local > 0.68:
                s = max(15, int(s * (1.0 - local * 0.20)))
            frame.append((int(h) % 360, int(np.clip(s, 0, 100)), v))
        return frame


class ReactiveAuroraStyle(VisualStyle):
    """
    Reactive Aurora — an expressive music-reactive style.

    - Bass gently drives the curtain's lateral drift and movement.
    - Mids influence the curtain's body, harmonic thickness, and color balance (emerald <-> violet).
    - Detected transient events create brief sparkling highlights at the ribbon crests.
    - Quiet passages remain atmospheric and gentle; louder passages become more expressive
      without flashing the whole strip.
    """
    name = "Reactive Aurora"

    def __init__(self):
        super().__init__()
        self._phase1: float = 0.0
        self._phase2: float = 0.0
        self._smooth_bass: float = 0.0
        self._smooth_mid: float = 0.0
        self._smooth_energy: float = 0.0
        self._highlight_env: float = 0.0
        self._crest_pos: float = 25.0
        self._measured_latency_s: float = 0.0

    def set_params(self, measured_latency_s: Optional[float] = None, **kwargs: Any):
        super().set_params(**kwargs)
        if measured_latency_s is not None:
            self._measured_latency_s = float(measured_latency_s)

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._smooth_energy = 0.0
            self._highlight_env = 0.0
            return [(0, 0, 0)] * num_zones

        energy = float(getattr(state, "energy", 0.15))
        bass = float(getattr(state, "bass", 0.0))
        mid = float(getattr(state, "mid", 0.0))
        kick = float(getattr(state, "kick", 0.0))
        transient = float(getattr(state, "transient", 0.0))
        onset = float(getattr(state, "onset", 0.0))

        # Smooth inputs with continuous exponential filters
        eff_bass = max(bass, kick * 0.9)
        self._smooth_bass = exp_smooth_fast(self._smooth_bass, eff_bass, dt, 0.18)
        self._smooth_mid = exp_smooth_fast(self._smooth_mid, mid, dt, 0.22)
        self._smooth_energy = exp_smooth_fast(self._smooth_energy, max(0.08, energy), dt, 0.35)

        # 1. Bass gently drives the curtain's lateral drift and phase advection
        drift_speed = (0.35 + self._smooth_bass * 1.8) * self.speed
        self._phase1 += dt * drift_speed * 1.4
        self._phase2 += dt * drift_speed * 0.9

        # Evaluate phase with latency compensation (forward prediction for Wi-Fi transit)
        eval_phase1 = self._phase1 + (self._measured_latency_s * drift_speed * 1.4)
        eval_phase2 = self._phase2 + (self._measured_latency_s * drift_speed * 0.9)

        # 2. Mids influence the curtain's body (thickness) and color
        body_thickness = 0.85 + 0.65 * self._smooth_mid
        color_shift = self._smooth_mid  # 0.0 (emerald) to 1.0 (violet/magenta)

        # 3. Detected transient events create brief localized highlights at ribbon crests
        transient_hit = max(transient, onset * 0.8)
        if transient_hit > 0.35:
            target_hl = min(1.0, transient_hit * 1.2)
            if target_hl > self._highlight_env:
                self._highlight_env = target_hl

        # Smooth highlight decay (~120ms decay)
        self._highlight_env = exp_smooth_fast(self._highlight_env, 0.0, dt, 0.12)

        # Base Aurora hues: Emerald 145, Cyan 185, Violet 280
        emerald_hue = 145.0
        violet_hue = 280.0
        cyan_hue = 185.0

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            drift_t = (math.sin(eval_phase1) * 0.5 + 0.5)
            # Smooth polar advection from Emerald (145) to Violet (280)
            target_hue = emerald_hue + drift_t * (violet_hue - emerald_hue) * (0.5 + 0.5 * color_shift)
            h = int(target_hue % 360)
            s = int(max(60, 92 - self._highlight_env * 35.0))
            b = int(np.clip((self._smooth_energy * 60.0 + self._smooth_bass * 30.0 + self._highlight_env * 25.0) * self.intensity, 0, 100))
            return [(h, s, b)]

        frame: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            x = (i / float(max(1, num_zones - 1))) * 2.0 * math.pi

            # Dual undulating curtain ribbons
            w1 = math.sin(x * body_thickness - eval_phase1)
            w2 = math.cos(x * (body_thickness * 1.6) + eval_phase2 * 0.8)

            # Spatial ribbon envelope (peaked wave with dark valleys)
            ribbon = (w1 * 0.65 + w2 * 0.35 + 1.0) * 0.5  # 0.0 to 1.0

            # Quiet passages remain atmospheric; louder passages expand in spatial richness
            base_v = 10.0 + 18.0 * self._smooth_energy
            modulated_v = base_v + ribbon * (25.0 + 45.0 * self._smooth_energy)

            # Localized transient highlight at ribbon crests (shimmering sparkling highlights)
            crest_factor = max(0.0, (ribbon - 0.4) / 0.6) ** 2.0
            sparkle = 0.85 + 0.15 * math.sin(float(i) * 4.2 + self._phase1 * 6.0)
            hl_boost = self._highlight_env * crest_factor * sparkle * 38.0

            v = int(np.clip((modulated_v + hl_boost) * self.intensity, 5, 100))

            # Color: influenced by mids
            ribbon_hue_offset = (w1 * 25.0 + w2 * 15.0)
            if color_shift > 0.5:
                blend = (color_shift - 0.5) * 2.0
                base_h = violet_hue * blend + cyan_hue * (1.0 - blend)
            else:
                blend = color_shift * 2.0
                base_h = emerald_hue * (1.0 - blend) + cyan_hue * blend

            h = int((base_h + ribbon_hue_offset + 360.0) % 360.0)

            # Saturation dips on highlights for ethereal white-hot shimmer at crests
            s = int(np.clip(92.0 - hl_boost * 0.4, 45, 100))

            frame.append((h, s, v))

        return frame


# ── Backward Compatibility Shims & Aliases ───────────────────────────────────

ShockwaveStyle = PulseStyle
MirrorEQStyle = SpectrumStyle
AuroraStyle = ReactiveAuroraStyle
CometStyle = FlowStyle
FireStyle = PulseStyle
PlasmaStyle = FlowStyle
StarfieldStyle = FlowStyle
MelodyStyle = FlowStyle
DirectorStyle = PulseStyle
HybridStyle = PulseStyle
WaveStyle = FlowStyle
CinematicStyle = MovieStyle
AmbientStyle = FlowStyle
ParticlesStyle = FlowStyle

class BeatFlashAccent:
    def __init__(self):
        self.flash_env: float = 0.0

    def render_accent(self, state, dt, num_zones, frame):
        target = float(getattr(state, "kick", 0.0))
        if target > self.flash_env:
            self.flash_env = target
        else:
            self.flash_env = max(0.0, self.flash_env - dt * 2.0)
        return frame

class HatSparkleAccent:
    def __init__(self): pass
    def render_accent(self, state, dt, num_zones, frame): return frame

class AccentCompositor:
    """Backward compatibility shim."""
    def __init__(self):
        pass
    def set_accent_enabled(self, name: str, enabled: bool):
        pass
    def composite(self, state: MusicState, dt: float, num_zones: int, base_frame: List[Tuple[int, int, int]]) -> List[Tuple[int, int, int]]:
        return base_frame


# ── Per-Device Style Factory ─────────────────────────────────────────────────


# ── 15. NEON DRIVE (80s Retrowave Grid & Snappy Synthwave Beat Sync) ───────────

class NeonDriveStyle(VisualStyle):
    """
    80s Retrowave / Synthwave Grid Driver:
    - Dual electric neon palettes: Electric Cyan (185°) and Neon Magenta (315°).
    - Bass kicks launch high-speed outward grid lines.
    - Snares trigger sharp chromatic flashes.
    - Hi-hats create twinkling highway reflectors.
    """
    name = "NeonDrive"

    def __init__(self):
        super().__init__()
        self.phase: float = 0.0
        self.kick_waves: List[Dict[str, float]] = []
        self._spawn_cooldown: float = 0.0
        self._snare_flash: float = 0.0
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self.kick_waves.clear()
            self._snare_flash = 0.0
            return [(0, 0, 0)] * num_zones

        sp = max(0.2, self.speed)
        self.phase = (self.phase + dt * 0.8 * sp * (0.8 + state.energy * 0.8)) % 1.0
        self._spawn_cooldown = max(0.0, self._spawn_cooldown - dt)

        self._snare_flash = exp_smooth_fast(self._snare_flash, 0.0, dt, 0.12)
        if state.snare > 0.45:
            self._snare_flash = max(self._snare_flash, min(1.0, state.snare * 1.2))

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            # 80s Retrowave Grid: Cyan (185) on bass kick, Hot Magenta (315) on snare hit
            kick_pulse = min(1.0, state.kick * 1.3)
            snare_pulse = self._snare_flash
            total_activity = kick_pulse + snare_pulse
            if total_activity > 0.05:
                ratio = snare_pulse / total_activity
                h = int((185.0 + ratio * 130.0) % 360)
            else:
                h = 270  # Resting neon purple
            s = int(max(60, 95 - snare_pulse * 30))
            b = int(np.clip((state.energy * 20.0 + kick_pulse * 65.0 + snare_pulse * 60.0) * self.intensity, 0, 100))
            frame = [(h, s, b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        if (state.kick > 0.22 or state.onset > 0.40) and self._spawn_cooldown <= 0.0:
            self._spawn_cooldown = max(0.08, 0.14 / sp)
            self.kick_waves.append({"pos": 0.0, "speed": 42.0 * sp, "energy": state.kick, "life": 1.0})

        alive_waves = []
        for w in self.kick_waves:
            w["pos"] += w["speed"] * dt
            w["life"] -= dt * 1.8
            if w["life"] > 0.0 and w["pos"] <= (num_zones * 0.75):
                alive_waves.append(w)
        self.kick_waves = alive_waves[-6:]

        half = (num_zones - 1) / 2.0
        segs: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            dist_center = abs(i - half) / max(1.0, half)
            grid_phase = (dist_center * 3.5 - self.phase * 2.0) % 1.0
            grid_line = math.exp(-0.5 * ((grid_phase - 0.5) / 0.14) ** 2)

            wave_boost = 0.0
            for w in self.kick_waves:
                dw = abs(abs(i - half) - w["pos"])
                wave_boost += math.exp(-0.5 * (dw / 2.2) ** 2) * w["life"] * w["energy"]

            hue = int((185 + dist_center * 130 + self._snare_flash * 25) % 360)
            sat = int(max(70, 95 - self._snare_flash * 35))

            # Directed 50-IC dynamic response: Cyan kick waves, Magenta snare hits, Staccato black
            snare_zone_boost = self._snare_flash * 75.0 if abs(dist_center - 0.45) < 0.25 else 0.0
            total_activity = wave_boost * 85.0 + snare_zone_boost + (grid_line * 35.0 if state.energy > 0.55 else 0.0)

            # Brilliant white percussion flashes on center kicks and wing snares
            if state.kick > 0.68 and dist_center < 0.16:
                sat = max(0, int(sat * 0.10))
                total_activity = max(total_activity, 95.0)
            elif self._snare_flash > 0.65 and abs(dist_center - 0.45) < 0.18:
                sat = max(0, int(sat * 0.20))

            if total_activity < 3.0:
                final_v = 0
            else:
                final_v = int(max(0, min(100, total_activity * self.intensity)))

            segs.append((hue, sat, final_v))

        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


# ── 16. SUB BLAST (High-Impact Low-Frequency Kinetic Detonation) ───────────────

class SubBlastStyle(VisualStyle):
    """
    Sub-Bass Cannon:
    - Pure sub-bass frequency isolation (20 - 120 Hz) with deep shockwave acoustics.
    - Low-end punch detonates from center outward.
    - Saturated wide spectrum colors (cyans, purples, blues, magentas) with new colors on each bass ripple.
    - Beat-synced white flashes on extreme bass.
    """
    name = "SubBlast"

    def __init__(self):
        super().__init__()
        self._blast_radius: float = 0.0
        self._blast_energy: float = 0.0
        self._sub_smoothed: float = 0.0
        self._ripple_color_phase: float = 0.0
        self._prev_kick: float = 0.0
        self._prev_sub: float = 0.0
        self._strobe_phase: float = 0.0
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._blast_radius = 0.0
            self._blast_energy = 0.0
            self._prev_kick = 0.0
            self._prev_sub = 0.0
            return [(0, 0, 0)] * num_zones

        sub_bass = float(getattr(state, "sub_bass", np.mean(state.bands[:6]) if len(state.bands) >= 6 else state.kick))
        self._sub_smoothed = exp_smooth_fast(self._sub_smoothed, sub_bass, dt, 0.04)

        # Launch new shockwave only on rising transient impact or surge, not continuously holding radius 0 on sustained bass
        is_kick_onset = state.kick > 0.28 and (state.kick > self._prev_kick + 0.08 or getattr(state, "is_kick", False))
        is_sub_onset = sub_bass > 0.32 and (sub_bass > self._prev_sub + 0.10)
        is_transient_onset = float(getattr(state, "transient", 0.0)) > 0.45 and (state.kick > 0.25 or sub_bass > 0.25)
        # Also allow re-triggering if the previous blast has already expanded past the core (> 12 zones)
        can_retrigger = self._blast_radius > 12.0 or self._blast_energy < 0.25

        if (is_kick_onset or is_sub_onset or is_transient_onset) and can_retrigger:
            self._blast_energy = max(self._blast_energy, float(max(state.kick, sub_bass)))
            self._blast_radius = 0.0
            # Advance color across wide spectrum on each distinct bass ripple
            self._ripple_color_phase = (self._ripple_color_phase + 67.0) % 360.0

        self._prev_kick = state.kick
        self._prev_sub = sub_bass

        self._blast_radius += (42.0 * max(0.5, self.speed)) * dt
        self._blast_energy = exp_smooth_fast(self._blast_energy, 0.0, dt, 0.28)

        pal = self.get_palette(state)
        half = (num_zones - 1) / 2.0
        segs: List[Tuple[int, int, int]] = []

        base_h = float(getattr(state, "bass_ripple_phase", self._ripple_color_phase))
        is_extreme = bool(getattr(state, "is_extreme_bass", False) or getattr(state, "white_strobe", False) or (state.kick > 0.82 and sub_bass > 0.65))

        # Flash on and off with white color for extreme bass
        if is_extreme:
            self._strobe_phase = (self._strobe_phase + dt * 14.0) % 1.0
            strobe_white = self._strobe_phase < 0.50
        else:
            self._strobe_phase = 0.0
            strobe_white = False

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            if strobe_white:
                # Extreme bass: pure crisp 100% white strobe flash on the beat!
                frame = [(0, 0, int(100 * self.intensity))]
            else:
                # Sub-bass cannon: Wide-spectrum chromatic explosion that advances on every bass ripple
                h = int(self._ripple_color_phase)
                sub_val = max(state.kick, self._sub_smoothed)
                s = int(max(75, 95 - sub_val * 10.0))
                b = int(np.clip((self._blast_energy * 85.0 + sub_val * 50.0 + state.energy * 15.0) * self.intensity, 0, 100))
                frame = [(h, s, b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        for i in range(num_zones):
            d_center = abs(i - half)
            shock = math.exp(-0.5 * ((d_center - self._blast_radius) / 3.0) ** 2) * self._blast_energy
            core = math.exp(-0.5 * (d_center / 3.8) ** 2) * self._sub_smoothed

            # Wide-spectrum chromatic wave: center starts with ripple hue, edges shift dynamically
            zone_h = int((base_h + d_center * 11.0 + shock * 35.0) % 360)
            if (strobe_white and shock > 0.35) or (state.kick > 0.68 and d_center < 3.5):
                zone_s = 0  # Pure crisp white flash on bass shock core
            else:
                zone_s = int(max(75, min(100, 95 - core * 10.0)))
            v_val = (core * 70.0 + shock * 95.0) * self.intensity
            final_v = int(max(0, min(100, v_val))) if v_val >= 2.5 else 0
            segs.append((zone_h, zone_s, final_v))

        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


# ── 17. VOCAL GLOW (Human Voice & Lead Frequency Isolation Aura) ───────────────

class VocalGlowStyle(VisualStyle):
    """
    Vocal & Melodic Soloist Aura:
    - Isolates vocal/lead frequency band (300 Hz - 3.5 kHz).
    - Creates a gentle organic breathing halo that blooms with speech and song.
    """
    name = "VocalGlow"

    def __init__(self):
        super().__init__()
        self._vocal_env: float = 0.0
        self._center_shift: float = 0.0
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self._vocal_env = 0.0
            return [(0, 0, 0)] * num_zones

        vocal_energy = float(np.mean(state.bands[12:35])) if len(state.bands) >= 35 else state.mid
        self._vocal_env = exp_smooth_fast(self._vocal_env, vocal_energy, dt, 0.06 if vocal_energy > self._vocal_env else 0.22)

        self._center_shift += dt * 0.25 * (state.valence - 0.5)

        pal = self.get_palette(state)

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            # Vocal aura: blooms with vocal & lead frequency band (300 Hz - 3.5 kHz)
            t_col = (0.25 + self._vocal_env * 0.5 + state.valence * 0.25) % 1.0
            h, s, _ = sample_palette_oklab(pal, t_col)
            b = int(np.clip((self._vocal_env * 85.0 + state.energy * 20.0) * self.intensity, 0, 100))
            frame = [(h, s, b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        half = (num_zones - 1) / 2.0
        center = half + math.sin(self._center_shift) * 6.0

        segs: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            dist = abs(i - center)
            halo = math.exp(-0.5 * (dist / (6.0 + self._vocal_env * 8.0)) ** 2)
            t_col = (0.2 + (dist / max(1.0, half)) * 0.6 + self._vocal_env * 0.2) % 1.0
            h, s, _ = sample_palette_oklab(pal, t_col)

            halo_v = halo * (35.0 + self._vocal_env * 65.0) * self.intensity
            # Brilliant white presence core for powerful vocal crescendo
            if dist < 2.5 and self._vocal_env > 0.65:
                s = max(20, int(s * 0.25))
                halo_v = max(halo_v, 95.0)
            final_v = int(min(100, halo_v)) if halo_v >= 3.0 else 0
            segs.append((h, s, final_v))

        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


# ── 18. LIQUID GROOVE (Viscous Non-Newtonian Fluid Surge) ──────────────────────

class LiquidGrooveStyle(VisualStyle):
    """
    Liquid Groove:
    - Viscous fluid dynamics swelling and sloshing with downbeats and melodic energy.
    - Warm crest highlights and silky smooth meniscus curvature.
    """
    name = "LiquidGroove"

    def __init__(self):
        super().__init__()
        self.phase: float = 0.0
        self.slosh_vel: float = 0.0
        self.slosh_pos: float = 0.0
        self._tension = BuildTensionAccent()
        self._bloom = DropBloomAccent()

    def render(self, state: MusicState, dt: float, num_zones: int, **kwargs: Any) -> List[Tuple[int, int, int]]:
        if self.is_silent_state(state):
            self.slosh_pos = 0.0
            self.slosh_vel = 0.0
            return [(0, 0, 0)] * num_zones

        sp = max(0.2, self.speed)
        if state.kick > 0.25:
            dir_sign = 1.0 if (int(state.bar_pos) % 2 == 0) else -1.0
            self.slosh_vel += dir_sign * state.kick * 4.5 * sp

        self.slosh_vel -= (self.slosh_pos * 9.0 + self.slosh_vel * 3.2) * dt
        self.slosh_pos += self.slosh_vel * dt
        self.slosh_pos = max(-1.0, min(1.0, self.slosh_pos))

        self.phase = (self.phase + dt * 0.45 * sp) % 1.0
        pal = self.get_palette(state)

        # ── Single-Zone L900 Mapping ──
        if num_zones == 1:
            fluid_level = 0.5 + 0.5 * math.sin(self.slosh_pos * 2.5 + self.phase * 2.0 * math.pi) * (0.6 + state.energy * 0.4)
            t_col = (fluid_level * 0.7 + abs(self.slosh_pos) * 0.3) % 1.0
            h, s, _ = sample_palette_oklab(pal, t_col)
            b = int(np.clip((fluid_level * 75.0 + state.kick * 25.0) * self.intensity, 0, 100))
            frame = [(h, s, b)]
            frame = self._tension.render_accent(state, dt, num_zones, frame)
            frame = self._bloom.render_accent(state, dt, num_zones, frame)
            return frame

        half = (num_zones - 1) / 2.0

        segs: List[Tuple[int, int, int]] = []
        for i in range(num_zones):
            nx = (i - half) / max(1.0, half)
            wave = math.sin(nx * 3.0 + self.slosh_pos * 2.5 + self.phase * 2.0 * math.pi)
            fluid_level = 0.5 + 0.5 * wave * (0.6 + state.energy * 0.4)

            t_col = (fluid_level * 0.7 + (nx + 1.0) * 0.15) % 1.0
            h, s, _ = sample_palette_oklab(pal, t_col)

            v_val = (fluid_level * 75.0 + (state.kick * 35.0 if abs(nx) < 0.35 else 0.0)) * self.intensity
            final_v = int(max(0, min(100, v_val))) if v_val >= 2.5 else 0
            segs.append((h, s, final_v))

        segs = self._tension.render_accent(state, dt, num_zones, segs)
        segs = self._bloom.render_accent(state, dt, num_zones, segs)
        return segs


def create_style_instances() -> Dict[str, VisualStyle]:
    """
    Returns fresh, independent style instances per hardware device (L930 and L900).
    Ensures zero cross-contamination of animation buffers or mutable state.
    """
    party = PartyStyle()
    chill = ChillStyle()
    edm = EdmModeStyle()
    movie = MovieStyle()
    pulse = PulseStyle()
    spectrum = SpectrumStyle()
    flow = FlowStyle()
    segmented = SegmentedVUStyle()
    bass_bounce = BassBounceStyle()
    center_burst = CenterBurstStyle()
    twinkle = TwinkleStyle()

    # Next-Gen Music Reactivity Engines
    acoustic_string = AcousticStringStyle()
    hydro_acoustic = HydroAcousticStyle()
    lofi_vinyl = LofiVinylStyle()
    melodic_contour = MelodicContourStyle()
    bpm_resonator = BpmResonatorStyle()
    reactive_aurora = ReactiveAuroraStyle()
    chain_reaction = RandomChainReactionStyle()
    neon_drive = NeonDriveStyle()
    sub_blast = SubBlastStyle()
    vocal_glow = VocalGlowStyle()
    liquid_groove = LiquidGrooveStyle()

    registry: Dict[str, VisualStyle] = {
        # Custom Vibe & Genre Engines
        "party": party,
        "club": party,
        "chill": chill,
        "lofi": lofi_vinyl,
        "lofi_vinyl": lofi_vinyl,
        "edm": edm,
        "drop": edm,
        "edm_drop": edm,
        "neon_drive": neon_drive,
        "synthwave_pulse": neon_drive,
        "synthwave": neon_drive,
        "sub_blast": sub_blast,
        "bass_cannon": sub_blast,
        "vocal_glow": vocal_glow,
        "vocal": vocal_glow,
        "liquid_groove": liquid_groove,
        "groove": liquid_groove,

        # Next-Gen Expressive Music Styles
        "acoustic_string": acoustic_string,
        "acoustic": acoustic_string,
        "string": acoustic_string,
        "hydro_acoustic": hydro_acoustic,
        "hydro": hydro_acoustic,
        "melodic_contour": melodic_contour,
        "melodic": melodic_contour,
        "contour": melodic_contour,
        "bpm_resonator": bpm_resonator,
        "resonator": bpm_resonator,

        # LumiSync Spatial Reaction Styles
        "bass_bounce": bass_bounce,
        "bounce": bass_bounce,
        "center_burst": center_burst,
        "burst": center_burst,
        "twinkle": twinkle,
        "sparkle": twinkle,

        # Core primary modes
        "movie": movie,
        "pulse": pulse,
        "spectrum": spectrum,
        "flow": flow,
        "aurora": reactive_aurora,
        "reactive_aurora": reactive_aurora,
        "chain_reaction": chain_reaction,
        "random_chain": chain_reaction,
        "chaos": chain_reaction,

        # Segmented VU Mode & Aliases
        "segmented": segmented,
        "segmented_vu": segmented,
        "staccato": segmented,

        # Migration & Backward Compatibility Aliases:
        "shockwave": pulse,
        "mirror_eq": spectrum,
        "auto": pulse,
        "director": pulse,
        "hybrid": pulse,
        "single_color": pulse,
        "lively": spectrum,
        "classical": spectrum,
        "upbeat": flow,
        "calm": chill,
        "comet": flow,
        "fire": pulse,
        "plasma": flow,
        "starfield": flow,
        "melody": flow,
        "cinematic": movie,
        "ambient": flow,
        "wave": flow,
        "particles": flow,
    }
    return registry


# Global fallback registry
STYLE_REGISTRY: Dict[str, VisualStyle] = create_style_instances()

def get_visual_style(name: str) -> VisualStyle:
    key = (name or "pulse").strip().lower()
    return STYLE_REGISTRY.get(key, STYLE_REGISTRY["pulse"])
