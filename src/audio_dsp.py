from __future__ import annotations
import math
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple, List, Optional, Dict
import numpy as np

from src.pipeline import oklch_to_rgb, rgb_to_tapo_hsv, lerp_oklch


def exp_smooth(current: float, target: float, dt: float, tau: float) -> float:
    """Continuous exponential filter alpha = 1 - exp(-dt / tau), rate independent."""
    if tau <= 1e-6:
        return target
    alpha = 1.0 - math.exp(-max(0.0, dt) / tau)
    return current + alpha * (target - current)


# ── 1. Musical Section Enum & Central MusicState Dataclass ─────────────────────

def apply_sensitivity_gain(values, sensitivity: float):
    """Apply the user sensitivity to normalized features without changing their range."""
    gain = max(0.1, min(4.0, float(sensitivity)))
    return np.clip(np.asarray(values, dtype=np.float32) * gain, 0.0, 1.0)


class Section(str, Enum):
    SILENT = "SILENT"
    INTRO = "INTRO"
    VERSE = "VERSE"
    BUILD = "BUILD"
    DROP = "DROP"
    BREAKDOWN = "BREAKDOWN"
    OUTRO = "OUTRO"


class SourcePreset(str, Enum):
    STANDARD = "standard"
    MOVIE = "movie"
    LIVE = "live"


@dataclass(frozen=True)
class MusicState:
    """
    Central immutable shared state representing complete musical understanding
    across Micro (10-50ms), Meso (1-8s), and Macro (30s+) timescales.
    The renderer reads only MusicState snapshots from a lock-free slot.
    """
    # ── Micro (10–50 ms) ──
    bands: np.ndarray = field(default_factory=lambda: np.zeros(50, dtype=np.float32))
    onset: float = 0.0          # 0.0 - 1.0 continuous scale-invariant normalized onset strength
    raw_flux: float = 0.0       # Raw spectral flux for tempo tracking
    kick: float = 0.0           # 0.0 - 1.0 low-frequency transient punch (20-100 Hz)
    snare: float = 0.0          # 0.0 - 1.0 mid-frequency transient snap (200-2000 Hz)
    hat: float = 0.0            # 0.0 - 1.0 high-frequency transient sizzle (4-14 kHz)
    bass: float = 0.0           # 0.0 - 1.0 calibrated bass energy (AcousticString, HydroAcoustic, LofiVinyl)
    mid: float = 0.0            # 0.0 - 1.0 calibrated mid energy (AcousticString)
    transient: float = 0.0      # 0.0 - 1.0 composite transient event strength

    # ── Meso (1–8 s) ──
    bpm: float = 120.0          # Estimated tempo
    bpm_confidence: float = 0.0 # 0.0 - 1.0 confidence from comb/autocorrelation
    beat_phase: float = 0.0     # 0.0 - 1.0 continuous PLL phase within current beat
    bar_pos: int = 0            # 0..3 position within 4-beat bar
    energy: float = 0.0         # Smoothed loudness relative to song's range (0.0 - 1.0)
    energy_trend: float = 0.0   # Slope: rising (+), steady (0), falling (-)
    centroid: float = 1000.0    # Spectral centroid (Hz)
    centroid_norm: float = 0.25 # Normalized spectral centroid (0.0 - 1.0)
    complexity: float = 0.0     # Spectral entropy/complexity from LumiSync (0.0 - 1.0)
    intensity: float = 0.0      # Composite: onset density + bass ratio + energy trend
    tension: float = 0.0        # 0.0 - 1.0 build tension metric
    impact: float = 0.0         # 0.0 - 1.0 transient impact relative to song dynamics
    section: Section = Section.SILENT
    section_age: float = 0.0    # Elapsed seconds in current section
    section_progress: float = 0.0 # Estimated 0.0 - 1.0 progression within section
    drop_strength: float = 0.0  # 0.0 - 1.0 drop qualification score
    silent: bool = True         # True if stream is quiet or timed out
    source_preset: SourcePreset = SourcePreset.STANDARD
    speech_dominance: float = 0.0  # 0.0 - 1.0 speech vs music/bass ratio for dialogue suppression
    is_extreme_bass: bool = False  # True during heavy sub-bass / kick overload
    white_strobe: bool = False     # Beat strobe pulse for extreme bass
    bass_ripple_phase: float = 0.0 # Rolling hue phase advanced on each bass ripple
    sub_bass: float = 0.0          # 0.0 - 1.0 calibrated sub-bass fundamental energy (20-75 Hz, 808s)

    # ── Macro (30 s+) ──
    chroma: np.ndarray = field(default_factory=lambda: np.zeros(12, dtype=np.float32))
    key_hue: float = 215.0      # Hue angle from key & circle of fifths
    mode: str = "major"         # "major" or "minor"
    key_confidence: float = 0.0 # 0.0 - 1.0 K-S key correlation confidence
    valence: float = 0.5        # Positivity (from mode + centroid)
    arousal: float = 0.5        # Energy activation (from tempo + energy)
    palette: List[Tuple[int, int, int]] = field(default_factory=lambda: [(215, 85, 75), (180, 90, 80), (280, 80, 70), (45, 95, 85)])
    harmonic_ratio: float = 0.5 # Tonal vs percussive ratio
    timestamp: float = 0.0      # Sample-clock timestamp (seconds)

    # ── Stage Timing Instrumentation (Phase 0) ──
    t_audio_recv: float = 0.0
    t_analysis_done: float = 0.0
    analysis_duration_ms: float = 0.0


# ── 2. Time-Domain Low-Pass (<120 Hz) Kick Detector ─────────────────────────

class LowPassKickDetector:
    """
    Time-domain 2nd-order low-pass filter (<120 Hz) with envelope follower for transient kick punch.
    Avoids FFT window latency and fixed arbitrary multipliers.
    Biquad Butterworth response: fs=44100 Hz, fc=120 Hz, Q=0.7071.
    """
    def __init__(self, samplerate: int = 44100, fc: float = 120.0):
        self.samplerate = samplerate
        self.fc = fc
        w0 = 2.0 * math.pi * fc / samplerate
        alpha = math.sin(w0) / (2.0 * 0.7071)
        cos_w0 = math.cos(w0)

        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

        self.b0 = float(b0 / a0)
        self.b1 = float(b1 / a0)
        self.b2 = float(b2 / a0)
        self.a1 = float(a1 / a0)
        self.a2 = float(a2 / a0)

        self.x1: float = 0.0
        self.x2: float = 0.0
        self.y1: float = 0.0
        self.y2: float = 0.0
        self.envelope: float = 0.0

    def process(self, samples: np.ndarray, dt: float, bpm: float = 120.0) -> float:
        n = len(samples)
        if n == 0:
            return self.envelope

        x1, x2, y1, y2 = self.x1, self.x2, self.y1, self.y2
        b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
        y = np.empty(n, dtype=np.float32)

        for i in range(n):
            x0 = float(samples[i])
            y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            y[i] = y0
            x2 = x1
            x1 = x0
            y2 = y1
            y1 = y0

        self.x1, self.x2, self.y1, self.y2 = x1, x2, y1, y2

        rect = np.abs(y)
        k_rms = float(np.sqrt(np.mean(rect ** 2)) + 1e-9)
        k_max = float(np.max(rect)) if n > 0 else 0.0
        target = 0.5 * k_rms + 0.5 * k_max

        # Dynamic tempo-scaled decay: allows rock/metal double-kicks (>150 BPM) to separate cleanly
        tempo_factor = max(60.0, min(220.0, float(bpm))) / 120.0
        tau_decay = max(0.080, min(0.180, 0.160 / tempo_factor))
        alpha_att = 1.0 - math.exp(-dt / 0.012)
        alpha_dec = 1.0 - math.exp(-dt / tau_decay)
        if target > self.envelope:
            self.envelope += alpha_att * (target - self.envelope)
        else:
            self.envelope += alpha_dec * (target - self.envelope)

        return float(self.envelope)


# ── 3. Scale-Invariant Adaptive Whitening Onset Detector ───────────────────────

class SpectralFluxOnsetDetector:
    """
    Computes scale-invariant spectral flux using log-compressed adaptive whitening:
    1. Log-compress 50 frequency bands: X_log = log(1 + 20 * X).
    2. Adaptively whiten each band against its continuous running mean (tau = 2.5s).
    3. Half-wave rectified flux with continuous mean and variance tracking (tau = 1.5s).
    Completely invariant to input gain and volume changes.
    """

    def __init__(self, num_bins: int = 50, threshold_mult: float = 1.40):
        self.num_bins = num_bins
        self.threshold_mult = threshold_mult
        self.running_band_mean = np.full(num_bins, 0.05, dtype=np.float32)
        self.prev_whitened = np.zeros(num_bins, dtype=np.float32)
        self.flux_mean: float = 0.5
        self.flux_var: float = 0.25
        self.last_onset_time: float = -1.0
        self.normalized_onset: float = 0.0
        self._initialized: bool = False

    def process(self, spectrum: np.ndarray, now: float, dt: float = 0.02) -> Tuple[float, bool]:
        dt = max(0.001, dt)

        # 1. Log compression
        spec_log = np.log1p(20.0 * np.maximum(0.0, spectrum)).astype(np.float32)

        # 2. Continuous adaptive whitening per band (tau = 2.5s)
        alpha_whiten = 1.0 - math.exp(-dt / 2.5)
        if not self._initialized:
            self.running_band_mean = np.maximum(0.01, spec_log.copy())
            whitened = spec_log / np.maximum(1e-4, self.running_band_mean)
            self.prev_whitened = whitened.copy()
            self._initialized = True
            self.normalized_onset = 0.0
            return 0.0, False

        self.running_band_mean += alpha_whiten * (spec_log - self.running_band_mean)
        whitened = spec_log / np.maximum(1e-4, self.running_band_mean)

        # 3. Half-wave rectified flux
        diff = np.maximum(0.0, whitened - self.prev_whitened)
        flux = float(np.sum(diff))
        self.prev_whitened = whitened.copy()

        # 4. Continuous flux mean & variance tracking (tau = 1.5s)
        std_flux = math.sqrt(max(1e-5, self.flux_var))
        threshold = self.flux_mean + self.threshold_mult * std_flux

        # Calculate pre-update normalized onset strength in [0.0, 1.0]
        # using statistics prior to incorporating current frame's flux
        self.normalized_onset = float(max(0.0, min(1.0, (flux - self.flux_mean) / max(0.05, std_flux * 3.0))))

        alpha_flux = 1.0 - math.exp(-dt / 1.5)
        self.flux_mean += alpha_flux * (flux - self.flux_mean)
        self.flux_var += alpha_flux * ((flux - self.flux_mean) ** 2 - self.flux_var)

        is_onset = False
        if flux > threshold and (self.last_onset_time < 0 or (now - self.last_onset_time) >= 0.12):
            is_onset = True
            self.last_onset_time = now

        return flux, is_onset


# ── 3. Comb/Autocorrelation Tempo Tracker & Phase-Locked Loop (PLL) ───────────

class CombAutocorrTempoTracker:
    """
    Tempo estimator and beat phase-locked loop (PLL):
    1. Tracks continuous onset strength over an 8-second circular buffer.
    2. Comb-filter / autocorrelation bank over 70–180 BPM resolving octave ambiguity.
    3. Phase-Locked Loop locks to the beat grid, producing continuous beat_phase [0, 1)
       and bar_pos [0..3] without drift.
    """

    def __init__(self, min_bpm: float = 70.0, max_bpm: float = 180.0):
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.estimated_bpm: float = 120.0
        self.bpm_confidence: float = 0.0

        # Circular buffer: (sample_time, onset_flux)
        self.history: deque[Tuple[float, float]] = deque(maxlen=400)
        self.last_eval_time: float = -1.0

        # Phase-Locked Loop (PLL) state
        self.phase: float = 0.0  # [0.0, 1.0)
        self.bar_pos: int = 0
        self.beat_count: int = 0
        self.last_beat_time: float = 0.0

    def update(self, onset_flux: float, is_onset: bool, now: float, dt: float) -> Tuple[float, float, int]:
        dt = max(0.001, dt)
        self.history.append((now, onset_flux))

        # Re-estimate tempo every 0.15 seconds
        if self.last_eval_time < 0 or (now - self.last_eval_time) >= 0.15:
            self._estimate_tempo()
            self.last_eval_time = now

        # Advance PLL phase continuously
        freq = self.estimated_bpm / 60.0
        old_phase = self.phase
        self.phase = (self.phase + freq * dt) % 1.0

        if self.phase < old_phase:
            # Beat boundary wrapped
            self.beat_count += 1
            self.bar_pos = self.beat_count % 4
            self.last_beat_time = now

        # Onset phase correction in PLL
        if is_onset:
            # Phase error wrapped to [-0.5, 0.5]
            error = self.phase if self.phase < 0.5 else (self.phase - 1.0)
            correction_gain = 0.22 * max(0.2, self.bpm_confidence)
            self.phase = (self.phase - correction_gain * error) % 1.0

        return self.estimated_bpm, self.phase, self.bar_pos

    def _estimate_tempo(self):
        if len(self.history) < 30:
            return

        times = np.array([h[0] for h in self.history], dtype=np.float32)
        fluxes = np.array([h[1] for h in self.history], dtype=np.float32)

        span = times[-1] - times[0]
        if span < 2.0:
            return

        # Resample onto regular 50 Hz grid (20ms)
        grid_dt = 0.020
        grid_times = np.arange(times[0], times[-1], grid_dt)
        grid_flux = np.interp(grid_times, times, fluxes)
        grid_flux -= np.mean(grid_flux)

        if np.std(grid_flux) < 1e-4:
            self.bpm_confidence = 0.0
            return

        # Vectorized Autocorrelation / Comb Filter across BPM range
        n = len(grid_flux)
        corr_full = np.correlate(grid_flux, grid_flux, mode="full")
        corr = corr_full[n - 1 :]
        counts = np.arange(n, 0, -1, dtype=np.float32)
        norm_corr = corr / np.maximum(1.0, counts)

        bpms = np.arange(self.min_bpm, self.max_bpm + 1.0, 1.0, dtype=np.float32)
        period_sec = 60.0 / bpms
        lags1 = np.round(period_sec / grid_dt).astype(int)
        lags2 = lags1 * 2

        valid1 = (lags1 >= 0) & (lags1 < n)
        valid2 = (lags2 >= 0) & (lags2 < n)
        r1 = np.zeros(len(bpms), dtype=np.float32)
        r2 = np.zeros(len(bpms), dtype=np.float32)
        r1[valid1] = norm_corr[lags1[valid1]]
        r2[valid2] = norm_corr[lags2[valid2]]

        # Octave preference weighting (smoothes 90 - 145 BPM sweet spot)
        octave_weight = 1.0 - 0.25 * np.abs(bpms - 124.0) / 60.0
        scores = (r1 + 0.5 * r2) * octave_weight

        best_idx = int(np.argmax(scores))
        best_bpm = float(bpms[best_idx])
        max_score = float(scores[best_idx])
        mean_score = float(np.mean(scores))
        std_score = float(np.std(scores))

        conf = max(0.0, min(1.0, (max_score - mean_score) / max(1e-4, std_score * 2.5)))

        # Exponential smoothing on BPM
        alpha = 0.15 if conf > 0.4 else 0.05
        self.estimated_bpm = round((1.0 - alpha) * self.estimated_bpm + alpha * best_bpm, 1)
        self.bpm_confidence = round(0.85 * self.bpm_confidence + 0.15 * conf, 2)

    def get_phase(self, lookahead_sec: float = 0.0) -> float:
        freq = self.estimated_bpm / 60.0
        return float((self.phase + freq * max(0.0, lookahead_sec)) % 1.0)


# Backwards compatibility shim for existing tests/callers
class BPMTracker:
    def __init__(self):
        self._comb = CombAutocorrTempoTracker()
        self.estimated_bpm = 120.0
        self.confidence = 0.0
        self.bar_pos = 0
        self.last_beat_time = 0.0
        self.beat_count = 0

    def record_onset(self, now: float):
        dt = 0.025
        bpm, phase, bar = self._comb.update(1.0, True, now, dt)
        self.estimated_bpm = bpm
        self.confidence = self._comb.bpm_confidence
        self.bar_pos = bar
        self.last_beat_time = now

    def get_phase(self, now: float) -> float:
        return self._comb.phase

    def should_predictive_fire(self, now: float, lead_sec: float) -> bool:
        return False

    def predict_next_beat(self) -> float:
        period = 60.0 / max(50.0, self.estimated_bpm)
        return self.last_beat_time + period


# ── 4. Dual Fast/Slow Song Calibrator with Silence Gate ───────────────────────

class DynamicSongCalibrator:
    """
    Dual-ring buffer dynamic calibrator:
    - Fast window (5 seconds): tracks instantaneous crests and local trends.
    - Slow window (45 seconds): captures macro track percentiles (p5, p50, p95, p99).
    - Absolute silence gate (< -54 dBFS): immediately flags silent and locks percentiles.
    - Stream timeout detector (> 120ms with no buffer): triggers silence.
    - Percentiles computed every N=5 frames for high CPU efficiency.
    - Automatic slow-window reset on track transitions or long silence.
    """

    def __init__(self, fast_sec: float = 5.0, slow_sec: float = 45.0, sensitivity: float = 1.0):
        self.fast_sec = fast_sec
        self.slow_sec = slow_sec
        self.sensitivity = sensitivity

        self.fast_history: deque[Tuple[float, float, float]] = deque(maxlen=250)  # (t, rms, kick)
        self.slow_history: deque[Tuple[float, float, float]] = deque(maxlen=2250)
        self.frame_counter: int = 0

        # Conservative startup percentiles let quiet-but-real loopback audio
        # respond immediately instead of spending the first seconds below the
        # active-energy gate while the long-window calibrator warms up.
        self.p5: float = 0.003
        self.p50: float = 0.012
        self.p95: float = 0.050
        self.p99: float = 0.080

        self.smoothed_energy: float = 0.0
        self.energy_trend: float = 0.0
        self.last_update_time: float = -1.0
        self.silent_duration: float = 0.0

    def update(self, rms: float, kick: float, now: float, dt: float) -> Tuple[float, float, float, bool]:
        dt = max(0.001, dt)
        self.frame_counter += 1

        # Stream timeout detection (e.g. WASAPI gives no buffers for > 120ms)
        if self.last_update_time >= 0 and (now - self.last_update_time) > 0.120:
            self.silent_duration += (now - self.last_update_time)
        self.last_update_time = now

        # Absolute silence gate (< -54 dBFS / 0.0020 RMS)
        is_hard_silence = (rms < 0.0020)
        if is_hard_silence:
            self.silent_duration += dt
        else:
            self.silent_duration = 0.0

        is_silent = is_hard_silence or (self.silent_duration >= 0.20)

        # Discontinuity reset on long silence (> 1.8s) -> clean track boundary
        if self.silent_duration > 1.8:
            self.fast_history.clear()
            self.slow_history.clear()
            self.smoothed_energy = 0.0
            self.energy_trend = 0.0

        if not is_silent:
            self.fast_history.append((now, rms, kick))
            self.slow_history.append((now, rms, kick))

        # Recompute percentiles every 5 frames
        if self.frame_counter % 5 == 0 and len(self.slow_history) >= 20:
            rms_vals = [h[1] for h in self.slow_history]
            self.p5 = float(np.percentile(rms_vals, 5))
            self.p50 = float(np.percentile(rms_vals, 50))
            self.p95 = float(np.percentile(rms_vals, 95))
            self.p99 = float(np.percentile(rms_vals, 99))

        if is_silent:
            norm_energy = 0.0
            drop_strength = 0.0
            self.norm_kick = 0.0
        else:
            # Scale-invariant adaptive dynamic range: adapts cleanly even on quiet system volume
            floor = min(0.0025, self.p5)
            observed_span = self.p95 - floor
            dyn_range = max(0.006, observed_span)
            norm_energy = max(0.0, min(1.0, (rms - floor) / dyn_range))
            norm_energy = min(1.0, norm_energy * self.sensitivity)

            # Drop strength and scale-invariant kick punch relative to song dynamics
            kick_vals = [h[2] for h in self.slow_history]
            top_kick = float(np.percentile(kick_vals, 95)) if len(kick_vals) >= 20 else 0.10
            kick_floor = float(np.percentile(kick_vals, 5)) if len(kick_vals) >= 20 else 0.01
            kick_span = max(0.006, top_kick - kick_floor)
            drop_strength = max(0.0, min(1.0, (kick - kick_floor) / max(0.015, top_kick)))
            self.norm_kick = max(0.0, min(1.0, (kick - kick_floor) / kick_span)) * self.sensitivity

        # Continuous energy smoothing & trend slope
        old_energy = self.smoothed_energy
        alpha_energy = 1.0 - math.exp(-dt / 0.12)
        self.smoothed_energy += alpha_energy * (norm_energy - self.smoothed_energy)

        instant_slope = (self.smoothed_energy - old_energy) / dt
        alpha_trend = 1.0 - math.exp(-dt / 0.8)
        self.energy_trend += alpha_trend * (instant_slope - self.energy_trend)

        return self.smoothed_energy, self.energy_trend, drop_strength, is_silent


# Backwards compatibility shim for DynamicAudioCalibrator
class DynamicAudioCalibrator:
    def __init__(self, sensitivity: float = 1.0):
        self._sensitivity = float(sensitivity)
        self.noise_floor = 0.005
        self._calib = DynamicSongCalibrator(sensitivity=sensitivity)

    @property
    def sensitivity(self) -> float:
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, val: float):
        self._sensitivity = float(val)
        if hasattr(self, "_calib") and self._calib:
            self._calib.sensitivity = float(val)

    def update(self, rms: float) -> float:
        energy, trend, drop, silent = self._calib.update(rms, rms, time.monotonic(), 0.025)
        self.noise_floor = self._calib.p5
        return energy


# ── 5. Dedicated 4096-Sample STFT Chroma & Musical Key Estimator ──────────────

class ChromaKeyEstimator:
    """
    Musical Key & OKLCH Palette Estimator:
    1. Circular buffer of 4096 samples provides ~10.77 Hz frequency resolution.
    2. Sums peak energies across 55 Hz - 2100 Hz into 12 semitone pitch classes.
    3. Exponentially decayed 12-bin chroma vector (tau = 16s).
    4. Correlated with Krumhansl-Schmuckler (K-S) major/minor key profiles.
    5. Returns key_hue, mode, and key_confidence. When key_confidence < 0.40,
       gracefully falls back to a centroid & arousal harmonic palette.
    """

    KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float32)
    KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float32)
    FIFTHS_HUES = [0, 210, 60, 270, 120, 330, 180, 30, 240, 90, 300, 150]

    def __init__(self, samplerate: int = 44100, fft_size: int = 4096):
        self.samplerate = samplerate
        self.fft_size = fft_size
        self.sample_buffer = np.zeros(fft_size, dtype=np.float32)
        self.chroma = np.zeros(12, dtype=np.float32)

        self.current_key_hue: float = 215.0
        self.current_mode: str = "major"
        self.key_confidence: float = 0.0

        # Precompute pitch bins for FFT frequencies
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / samplerate)
        valid = (freqs >= 55.0) & (freqs <= 2100.0)
        self.valid_freq_indices = np.where(valid)[0]
        self.valid_freqs = freqs[valid]
        self.freqs = freqs
        self._hann = np.hanning(fft_size).astype(np.float32)
        mid_range = (self.freqs >= 150.0) & (self.freqs <= 900.0)
        self._mid_indices = np.where(mid_range)[0]

        # MIDI semitones: 69 + 12 * log2(f / 440)
        midi_pitches = 69.0 + 12.0 * np.log2(self.valid_freqs / 440.0)
        self.pitch_classes = (np.round(midi_pitches).astype(int)) % 12

        # Precompute normalized Krumhansl-Schmuckler profiles for instant matrix multiplication
        maj_zero = self.KS_MAJOR - np.mean(self.KS_MAJOR)
        min_zero = self.KS_MINOR - np.mean(self.KS_MINOR)
        self._ks_maj_matrix = np.array([np.roll(maj_zero / np.linalg.norm(maj_zero), r) for r in range(12)], dtype=np.float32)
        self._ks_min_matrix = np.array([np.roll(min_zero / np.linalg.norm(min_zero), r) for r in range(12)], dtype=np.float32)

    def process(self, new_samples: np.ndarray, dt: float = 0.025) -> Tuple[float, str, float, np.ndarray]:
        dt = max(0.001, dt)

        # Shift sample buffer and append new samples
        n = len(new_samples)
        if n >= self.fft_size:
            self.sample_buffer = new_samples[-self.fft_size:].astype(np.float32)
        else:
            self.sample_buffer[:-n] = self.sample_buffer[n:]
            self.sample_buffer[-n:] = new_samples

        # Compute 4096-sample Hann-windowed FFT
        fft_mag = np.abs(np.fft.rfft(self.sample_buffer * self._hann))

        # Global tuning estimation (A4 440 Hz reference)
        delta_tuning = 0.0
        mid_indices = self._mid_indices
        if len(mid_indices) > 5:
            sub_mags = fft_mag[mid_indices]
            thresh = float(np.mean(sub_mags) * 2.5)
            peaks = []
            for p_idx in range(1, len(sub_mags) - 1):
                if sub_mags[p_idx] > thresh and sub_mags[p_idx] > sub_mags[p_idx - 1] and sub_mags[p_idx] > sub_mags[p_idx + 1]:
                    alpha_bin = float(sub_mags[p_idx - 1])
                    beta_bin = float(sub_mags[p_idx])
                    gamma_bin = float(sub_mags[p_idx + 1])
                    denom = 2.0 * (alpha_bin - 2.0 * beta_bin + gamma_bin)
                    p_offset = (alpha_bin - gamma_bin) / denom if abs(denom) > 1e-6 else 0.0
                    actual_idx = mid_indices[p_idx] + p_offset
                    peak_freq = actual_idx * (self.samplerate / self.fft_size)
                    midi = 69.0 + 12.0 * math.log2(max(10.0, peak_freq) / 440.0)
                    deviation = midi - round(midi)
                    peaks.append((deviation, beta_bin))
            if peaks:
                total_w = sum(w for _, w in peaks)
                if total_w > 1e-5:
                    delta_tuning = sum(dev * w for dev, w in peaks) / total_w
                    delta_tuning = max(-0.5, min(0.5, delta_tuning))

        # Re-assign pitch classes with tuning correction
        effective_pitches = 69.0 + 12.0 * np.log2(self.valid_freqs / 440.0) - delta_tuning
        pitch_classes = (np.round(effective_pitches).astype(int)) % 12

        # Accumulate energy into 12 semitones
        instant_chroma = np.bincount(
            pitch_classes,
            weights=fft_mag[self.valid_freq_indices],
            minlength=12,
        ).astype(np.float32)

        total_c = float(np.sum(instant_chroma))
        if total_c > 1e-4:
            instant_chroma /= total_c

        # Continuous exponential smoothing (tau = 14.0s)
        alpha = 1.0 - math.exp(-dt / 14.0)
        self.chroma += alpha * (instant_chroma - self.chroma)

        # Krumhansl-Schmuckler Key Correlation (vectorized via matrix dot product)
        norm_chroma = self.chroma - np.mean(self.chroma)
        norm_c_len = float(np.linalg.norm(norm_chroma))

        if norm_c_len > 1e-4:
            x_norm = (norm_chroma / norm_c_len).astype(np.float32)
            r_maj = self._ks_maj_matrix @ x_norm
            r_min = self._ks_min_matrix @ x_norm

            best_maj_idx = int(np.argmax(r_maj))
            best_min_idx = int(np.argmax(r_min))
            if r_maj[best_maj_idx] >= r_min[best_min_idx]:
                best_root = best_maj_idx
                best_mode = "major"
                best_r = float(r_maj[best_maj_idx])
                r_maj_copy = r_maj.copy()
                r_maj_copy[best_maj_idx] = -2.0
                second_r = max(float(np.max(r_maj_copy)), float(r_min[best_min_idx]))
            else:
                best_root = best_min_idx
                best_mode = "minor"
                best_r = float(r_min[best_min_idx])
                r_min_copy = r_min.copy()
                r_min_copy[best_min_idx] = -2.0
                second_r = max(float(np.max(r_min_copy)), float(r_maj[best_maj_idx]))

            self.key_confidence = max(0.0, min(1.0, (best_r - second_r) * 6.0))
            target_hue = float(self.FIFTHS_HUES[best_root])
            if best_mode == "minor":
                target_hue = (target_hue + 30.0) % 360.0

            # Smoothly drift key hue
            diff = (target_hue - self.current_key_hue + 180) % 360 - 180
            self.current_key_hue = (self.current_key_hue + 0.10 * diff) % 360.0
            self.current_mode = best_mode
        else:
            self.key_confidence = 0.0

        return self.current_key_hue, self.current_mode, self.key_confidence, self.chroma.copy()

    def build_palette(self, centroid: float, arousal: float, ripple_phase: float = 0.0) -> List[Tuple[int, int, int]]:
        """Builds a wide-spectrum 4-colour harmonic palette in OKLCH. Eliminates golden-warm bias."""
        # Anchor to smoothly-decayed musical key hue; do not jump wildly on raw FFT centroid
        base_hue = (self.current_key_hue + ripple_phase) % 360.0

        h1 = int(base_hue)
        h2 = int((base_hue + 45) % 360)
        h3 = int((base_hue + 180) % 360)
        h4 = int((base_hue + 225) % 360)

        # High saturation for vivid club-grade lighting (80-98%)
        sat = int(np.clip(80 + arousal * 18, 75, 98))
        val = int(np.clip(70 + arousal * 28, 55, 98))

        return [(h1, sat, val), (h2, sat, val), (h3, sat - 5, val - 5), (h4, sat, val)]


# ── 6. Structure State Machine with Dwell Times & Drop Qualification ──────────

class StructureStateMachine:
    """
    Structure state machine tracking SILENT, INTRO, VERSE, BUILD, DROP, BREAKDOWN, OUTRO.
    Enforces minimum dwell times to eliminate chatter and qualifies drops based on contrast.
    """

    def __init__(self):
        self.current_section = Section.SILENT
        self.section_age: float = 0.0
        self.state_enter_time: float = 0.0
        self.last_drop_time: float = -10.0
        self.last_build_time: float = -999.0
        self.saw_build_or_break: bool = False

    def update(
        self,
        energy: float,
        energy_trend: float,
        drop_str: float,
        is_silent: bool,
        now: float,
        dt: float
    ) -> Tuple[Section, float, float]:
        dt = max(0.001, dt)
        self.section_age += dt

        if self.current_section in (Section.BUILD, Section.BREAKDOWN):
            self.last_build_time = now
            self.saw_build_or_break = True

        # 1. Silence check
        if is_silent or energy < 0.03:
            if self.current_section != Section.SILENT and self.section_age >= 0.40:
                self._transition(Section.SILENT, now)
            return self.current_section, self.section_age, 1.0

        # 2. Dynamic drop transition: responsive to real musical drops and heavy bass impacts
        time_since_drop = now - self.last_drop_time
        time_since_build = now - self.last_build_time
        # Support genuine drops from any section when bass impact surges
        is_acoustic_drop = (drop_str > 0.75 and energy > 0.60 and time_since_drop >= 0.8)
        can_drop = is_acoustic_drop or (
            (self.saw_build_or_break or time_since_build <= 12.0)
            and drop_str > 0.80
            and time_since_drop >= 1.0
        )
        if can_drop:
            self._transition(Section.DROP, now)
            self.last_drop_time = now
            self.saw_build_or_break = False
            self.last_build_time = -999.0
            return self.current_section, self.section_age, 0.0

        # State dwell times and transitions
        if self.current_section == Section.DROP:
            # Hold DROP for 4.0s
            progress = min(1.0, self.section_age / 4.0)
            if self.section_age >= 4.0:
                self._transition(Section.VERSE, now)
            return self.current_section, self.section_age, progress

        elif self.current_section == Section.BUILD:
            progress = min(1.0, self.section_age / 5.0)
            if energy < 0.35 and energy_trend < -0.10 and self.section_age >= 2.2:
                self._transition(Section.BREAKDOWN, now)
            elif energy_trend <= 0.01 and self.section_age >= 6.0:
                self._transition(Section.VERSE, now)
            return self.current_section, self.section_age, progress

        elif self.current_section == Section.BREAKDOWN:
            progress = min(1.0, self.section_age / 4.0)
            if energy_trend > 0.12 and self.section_age >= 2.0:
                self._transition(Section.BUILD, now)
            elif energy > 0.50 and self.section_age >= 3.0:
                self._transition(Section.VERSE, now)
            return self.current_section, self.section_age, progress

        elif self.current_section == Section.SILENT:
            if energy >= 0.08:
                self._transition(Section.INTRO, now)
            return self.current_section, self.section_age, 0.0

        elif self.current_section == Section.INTRO:
            progress = min(1.0, self.section_age / 8.0)
            if self.section_age >= 8.0 or energy >= 0.45:
                self._transition(Section.VERSE, now)
            return self.current_section, self.section_age, progress

        else:  # VERSE
            progress = min(1.0, self.section_age / 16.0)
            if energy_trend > 0.08 and energy > 0.45 and self.section_age >= 1.2:
                self._transition(Section.BUILD, now)
            elif energy < 0.22 and energy_trend < -0.06 and self.section_age >= 2.0:
                self._transition(Section.BREAKDOWN, now)
            return self.current_section, self.section_age, progress

    def _transition(self, new_sec: Section, now: float):
        self.current_section = new_sec
        self.section_age = 0.0
        self.state_enter_time = now


# ── 7. Central Real-Time MusicAnalyzer ────────────────────────────────────────

class MusicAnalyzer:
    """
    Central real-time music analyzer for the two-axis model.
    Analyzes raw PCM audio and produces an immutable MusicState snapshot.
    Uses audio stream sample-clock timestamps for complete bit-for-bit determinism.
    """

    def __init__(
        self,
        samplerate: int = 44100,
        blocksize: int = 1024,
        sensitivity: float = 1.0,
        latency_lookahead_ms: float = 40.0
    ):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.sensitivity = sensitivity
        self.latency_lookahead_ms = max(0.0, min(250.0, float(latency_lookahead_ms)))
        self.bass_ripple_phase: float = 0.0
        self.white_strobe_timer: float = 0.0
        self._prev_kick: float = 0.0
        self._prev_sub: float = 0.0
        self._sub_peak: float = 0.50
        self._sub_env: float = 0.0

        # 4096-sample rolling buffer for Hann-windowed bass & chroma resolution
        self.fft_size = 4096
        self._stft_buffer = np.zeros(self.fft_size, dtype=np.float32)
        self._hann_4096 = np.hanning(self.fft_size).astype(np.float32)
        self.freqs_4096 = np.fft.rfftfreq(self.fft_size, d=1.0 / samplerate)

        # 50 log-spaced continuous frequency band centers (20 Hz - 16,000 Hz)
        self.band_centers = np.logspace(np.log10(20), np.log10(16000), 50).astype(np.float32)
        # Verify continuous interpolated filterbank has no empty bands
        test_bands = np.interp(self.band_centers, self.freqs_4096, np.ones(len(self.freqs_4096)))
        assert len(test_bands) == 50 and np.all(test_bands > 0.0), "Filterbank bands must have positive weights"

        # Frequency masks for speech, sub-bass, snare, hi-hat, bass, and mid
        self.speech_mask = (self.freqs_4096 >= 250) & (self.freqs_4096 < 3400)
        self.sub_bass_mask = (self.freqs_4096 >= 20) & (self.freqs_4096 < 90)
        self.snare_mask = (self.freqs_4096 >= 200) & (self.freqs_4096 < 2000)
        self.hat_mask = (self.freqs_4096 >= 4000) & (self.freqs_4096 < 14000)
        self.bass_mask = (self.freqs_4096 >= 20) & (self.freqs_4096 < 180)
        self.mid_mask = (self.freqs_4096 >= 180) & (self.freqs_4096 < 1500)
        self._cached_inst_n = blocksize
        self._hann_inst = np.hanning(blocksize).astype(np.float32)
        self._freqs_inst = np.fft.rfftfreq(blocksize, d=1.0 / samplerate)
        self.source_preset: SourcePreset = SourcePreset.STANDARD

        # Core Analysis Modules
        self.kick_detector = LowPassKickDetector(samplerate=samplerate, fc=120.0)
        self.onset_detector = SpectralFluxOnsetDetector(num_bins=50, threshold_mult=1.40)
        self.tempo_tracker = CombAutocorrTempoTracker()
        self.calibrator = DynamicSongCalibrator(sensitivity=sensitivity)
        self.chroma_estimator = ChromaKeyEstimator(samplerate, fft_size=4096)
        self.state_machine = StructureStateMachine()

        self._sample_count: int = 0
        self._sample_clock_time: float = 0.0
        self._last_process_time: float = 0.0
        self._current_state = MusicState()
        # Hold threshold-qualified onsets across the physical strip's frame cadence.
        self._onset_strength_env: float = 0.0
        self._hat_peak: float = 0.50
        self._snare_peak: float = 0.50
        self._bass_peak: float = 0.50
        self._mid_peak: float = 0.50
        self._snare_env: float = 0.0
        self._hat_env: float = 0.0
        self._bass_env: float = 0.0
        self._mid_env: float = 0.0
        self._band_peaks: np.ndarray = np.full(50, 0.08, dtype=np.float32)
        self.backlog_warning_count: int = 0

        # Expose bpm_tracker for backwards compatibility
        self.bpm_tracker = BPMTracker()
        self.bpm_tracker._comb = self.tempo_tracker

    def set_latency_lookahead(self, lookahead_ms: float):
        self.latency_lookahead_ms = max(0.0, min(250.0, float(lookahead_ms)))

    def set_sensitivity(self, sensitivity: float):
        self.sensitivity = max(0.1, min(4.0, float(sensitivity)))
        if hasattr(self, "calibrator") and self.calibrator:
            self.calibrator.sensitivity = self.sensitivity

    def set_source_preset(self, preset: SourcePreset | str):
        if isinstance(preset, str):
            preset = SourcePreset(preset.lower())
        self.source_preset = preset

    @property
    def state(self) -> MusicState:
        return self._current_state

    def process_samples(
        self,
        samples: np.ndarray,
        now: float | None = None,
        t_recv: float | None = None,
    ) -> MusicState:
        t_start = time.perf_counter()
        t_audio_recv = t_recv if t_recv is not None else t_start

        n_samples = len(samples)
        dt = n_samples / self.samplerate

        if now is None:
            self._sample_count += n_samples
            self._sample_clock_time = self._sample_count / float(self.samplerate)
            stream_time = self._sample_clock_time
        else:
            stream_time = now
            self._sample_clock_time = now

        # Update 4096-sample rolling buffer
        if n_samples >= self.fft_size:
            self._stft_buffer = samples[-self.fft_size:].astype(np.float32)
        else:
            self._stft_buffer[:-n_samples] = self._stft_buffer[n_samples:]
            self._stft_buffer[-n_samples:] = samples

        # 1. 4096-sample Hann-windowed FFT with pink-noise pre-emphasis for full 50-band dynamic range
        fft_4096 = np.abs(np.fft.rfft(self._stft_buffer * self._hann_4096))
        bands_4096 = np.interp(self.band_centers, self.freqs_4096, fft_4096).astype(np.float32)
        pink_slope = (self.band_centers / 60.0) ** 0.30
        eq_bands = bands_4096 * pink_slope

        # Rolling per-band AGC: allows bass, vocals, and hi-hats to co-exist without inter-band ducking
        self._band_peaks = np.maximum(eq_bands, self._band_peaks * math.exp(-dt / 2.6))
        norm_bands = np.clip(eq_bands / np.maximum(0.015, self._band_peaks), 0.0, 1.0)

        # 2. Time-Domain Low-Pass (<120 Hz) Kick Detector with dynamic BPM scaling
        cur_bpm = getattr(self.tempo_tracker, "bpm", 120.0) if hasattr(self, "tempo_tracker") else 120.0
        kick_e = self.kick_detector.process(samples, dt=dt, bpm=cur_bpm)

        # 3. Low-Latency Instantaneous Onset Detection
        n_inst = len(samples)
        if n_inst == getattr(self, "_cached_inst_n", -1):
            window_inst = self._hann_inst
            freqs_inst = self._freqs_inst
        else:
            window_inst = np.hanning(n_inst).astype(np.float32)
            freqs_inst = np.fft.rfftfreq(n_inst, d=1.0 / self.samplerate)
        fft_inst = np.abs(np.fft.rfft(samples * window_inst))
        instant_bands = np.interp(self.band_centers, freqs_inst, fft_inst).astype(np.float32)
        norm_instant_bands = np.clip(instant_bands / np.maximum(0.015, self._band_peaks), 0.0, 1.0)

        flux, is_onset = self.onset_detector.process(norm_instant_bands, stream_time, dt=dt)
        norm_onset_raw = getattr(self.onset_detector, "normalized_onset", 0.0)

        # 4. Tempo & Phase-Locked Loop (PLL)
        bpm, beat_phase, bar_pos = self.tempo_tracker.update(flux, is_onset, stream_time, dt=dt)

        # Lookahead predictive beat phase (only on high confidence >= 0.65)
        lead_sec = max(0.0, self.latency_lookahead_ms / 1000.0)
        if self.tempo_tracker.bpm_confidence >= 0.65:
            predictive_phase = self.tempo_tracker.get_phase(lookahead_sec=lead_sec)
        else:
            predictive_phase = beat_phase  # Fallback strictly to real-time phase

        # 5. Dual-Window Dynamics, Silence Gate & Drop Strength
        rms = float(np.sqrt(np.mean(samples ** 2)) + 1e-9)
        energy, energy_trend, drop_str, is_silent = self.calibrator.update(rms, kick_e, stream_time, dt=dt)

        # Source Preset Adaptation (e.g. MOVIE dialogue isolation & dimming)
        speech_e = float(np.mean(fft_4096[self.speech_mask])) if np.any(self.speech_mask) else 0.0
        sub_bass_e = float(np.mean(fft_4096[self.sub_bass_mask])) if np.any(self.sub_bass_mask) else 0.0
        total_speech_bass = max(1e-4, speech_e + sub_bass_e + kick_e)
        speech_dominance = speech_e / total_speech_bass
        if self.source_preset == SourcePreset.MOVIE and speech_dominance > 0.60:
            energy *= 0.55

        sens = max(0.1, min(4.0, float(self.sensitivity)))

        # 6. Spectral Centroid, Harmonic Ratio & Spectral Complexity (Shannon Entropy)
        total_mag = float(np.sum(fft_4096))
        centroid = float(np.sum(self.freqs_4096 * fft_4096) / max(1e-5, total_mag))
        centroid_norm = float(np.clip(centroid / 4500.0, 0.0, 1.0))

        geo_mean = float(np.exp(np.mean(np.log(np.maximum(1e-6, fft_4096)))))
        arith_mean = float(np.mean(fft_4096) + 1e-6)
        flatness = geo_mean / arith_mean
        harmonic_ratio = float(max(0.0, min(1.0, 1.0 - flatness)))

        # Spectral Complexity: Normalized Shannon entropy across frequency bands
        b_sum = float(np.sum(norm_bands))
        if b_sum > 1e-9:
            shares = norm_bands / b_sum
            active_shares = shares[shares > 1e-9]
            if active_shares.size > 1:
                complexity = float(-np.sum(active_shares * np.log(active_shares)) / np.log(float(len(norm_bands))))
            else:
                complexity = 0.0
        else:
            complexity = 0.0
        complexity = float(max(0.0, min(1.0, complexity)))
        # Instantaneous band blending: 70% 512-sample low-latency FFT with 30% 4096-STFT
        # Eliminates the 46ms STFT group delay so spectrum and band visualizers react instantly
        fast_bands = 0.70 * norm_instant_bands + 0.30 * norm_bands
        norm_bands = apply_sensitivity_gain(fast_bands, sens)

        # Transient metrics with rolling scale-invariant normalization and dedicated attack/release envelopes
        raw_snare = float(np.mean(fft_4096[self.snare_mask])) if np.any(self.snare_mask) else 0.0
        raw_hat = float(np.mean(fft_4096[self.hat_mask])) if np.any(self.hat_mask) else 0.0

        if is_silent:
            self._snare_env = 0.0
            self._hat_env = 0.0
            self._bass_env = 0.0
            self._mid_env = 0.0
            self._sub_env = 0.0
            norm_snare = 0.0
            norm_hat = 0.0
            norm_bass = 0.0
            norm_mid = 0.0
            norm_sub = 0.0
        else:
            self._hat_peak = max(raw_hat, self._hat_peak * math.exp(-dt / 3.0))
            instant_hat = float(max(0.0, min(1.0, raw_hat / max(0.10, self._hat_peak))))
            # Hi-hats: snappy attack (10ms) and short, sparse sparkle decay (60ms)
            alpha_hat = 1.0 - math.exp(-dt / 0.010) if instant_hat > self._hat_env else 1.0 - math.exp(-dt / 0.060)
            self._hat_env += alpha_hat * (instant_hat - self._hat_env)
            norm_hat = float(max(0.0, min(1.0, self._hat_env * sens)))

            self._snare_peak = max(raw_snare, self._snare_peak * math.exp(-dt / 3.0))
            instant_snare = float(max(0.0, min(1.0, raw_snare / max(0.10, self._snare_peak))))
            # Snare/transient: sharp attack (12ms) with 110ms visible tail
            alpha_snare = 1.0 - math.exp(-dt / 0.012) if instant_snare > self._snare_env else 1.0 - math.exp(-dt / 0.110)
            self._snare_env += alpha_snare * (instant_snare - self._snare_env)
            norm_snare = float(max(0.0, min(1.0, self._snare_env * sens)))

            # Absolute sub-band energy for bass (20-180 Hz) and mid (180-1500 Hz) using raw FFT magnitudes
            raw_bass_abs = float(np.mean(fft_4096[self.bass_mask])) if np.any(self.bass_mask) else 0.0
            raw_mid_abs = float(np.mean(fft_4096[self.mid_mask])) if np.any(self.mid_mask) else 0.0

            # Sub-bass fundamental (20 - 75 Hz) for deep 808s and rap/trap sub-bass glides
            raw_sub_abs = float(np.mean(fft_4096[self.sub_bass_mask])) if np.any(self.sub_bass_mask) else 0.0
            self._sub_peak = max(raw_sub_abs, self._sub_peak * math.exp(-dt / 3.0))
            instant_sub = float(max(0.0, min(1.0, raw_sub_abs / max(0.12, self._sub_peak))))
            alpha_sub = 1.0 - math.exp(-dt / 0.016) if instant_sub > self._sub_env else 1.0 - math.exp(-dt / 0.160)
            self._sub_env += alpha_sub * (instant_sub - self._sub_env)
            norm_sub = float(max(0.0, min(1.0, self._sub_env * sens)))

            self._bass_peak = max(raw_bass_abs, self._bass_peak * math.exp(-dt / 3.0))
            instant_bass = float(max(0.0, min(1.0, raw_bass_abs / max(0.20, self._bass_peak))))
            alpha_bass = 1.0 - math.exp(-dt / 0.018) if instant_bass > self._bass_env else 1.0 - math.exp(-dt / 0.140)
            self._bass_env += alpha_bass * (instant_bass - self._bass_env)
            norm_bass = float(max(0.0, min(1.0, (self._bass_env * 0.7 + getattr(self.calibrator, "norm_kick", kick_e) * 0.3) * sens)))

            self._mid_peak = max(raw_mid_abs, self._mid_peak * math.exp(-dt / 3.0))
            instant_mid = float(max(0.0, min(1.0, raw_mid_abs / max(0.20, self._mid_peak))))
            alpha_mid = 1.0 - math.exp(-dt / 0.025) if instant_mid > self._mid_env else 1.0 - math.exp(-dt / 0.200)
            self._mid_env += alpha_mid * (instant_mid - self._mid_env)
            norm_mid = float(max(0.0, min(1.0, self._mid_env * (energy * 0.5 + 0.5) * sens)))

        norm_kick = float(getattr(self.calibrator, "norm_kick", kick_e))

        # Use pre-update detector statistics, then hold the event long enough to survive
        # the strip's 125ms nominal update interval. A raw sub-threshold flux rise may
        # still contribute; a detector-confirmed onset is guaranteed a visible peak.
        onset_raw = float(max(0.0, min(1.0, norm_onset_raw)))
        onset_target = 0.0 if is_silent else max(onset_raw, 0.65 if is_onset else 0.0)
        onset_tau = 0.010 if onset_target > self._onset_strength_env else 0.240
        onset_alpha = 1.0 - math.exp(-dt / onset_tau)
        self._onset_strength_env += onset_alpha * (onset_target - self._onset_strength_env)
        norm_onset = float(apply_sensitivity_gain(self._onset_strength_env, sens))
        composite_transient = float(max(0.0, min(1.0, norm_snare * 0.5 + norm_onset * 0.3 + norm_hat * 0.2))) if not is_silent else 0.0

        intensity = float(max(0.0, min(1.0, energy * 0.50 + norm_kick * 0.30 + (1.0 - flatness) * 0.20)))
        tension = float(max(0.0, min(1.0, max(0.0, energy_trend * 3.5) + centroid_norm * 0.35)))
        impact = 1.0 if (is_onset and drop_str > 0.85) else (drop_str * 0.7 if is_onset else 0.0)

        # 7. Structure State Machine
        sec, sec_age, sec_prog = self.state_machine.update(
            energy, energy_trend, drop_str, is_silent, stream_time, dt=dt
        )

        # Smooth gradual drift for ripple phase rather than discrete 48-degree jumps on every kick
        self.bass_ripple_phase = (self.bass_ripple_phase + dt * 4.0) % 360.0
        self._prev_kick = norm_kick
        self._prev_sub = norm_sub

        # Detect extreme bass & beat strobe - only during genuine drops, not ordinary beats
        is_extreme_bass = (
            sec == Section.DROP
            and drop_str > 0.80
            and (norm_bass > 0.85 or norm_kick > 0.90)
        )
        white_strobe = False
        if is_extreme_bass and is_onset and norm_kick > 0.85:
            self.white_strobe_timer = 0.060

        if self.white_strobe_timer > 0.0:
            white_strobe = True
            self.white_strobe_timer = max(0.0, self.white_strobe_timer - dt)

        # 8. Dedicated 4096-sample STFT Musical Key & Wide-Spectrum OKLCH Palette
        key_hue, mode, key_conf, chroma = self.chroma_estimator.process(samples, dt=dt)
        arousal = float(np.clip((bpm - 70.0) / 90.0 * 0.5 + energy * 0.5, 0.0, 1.0))
        palette = self.chroma_estimator.build_palette(centroid, arousal, ripple_phase=self.bass_ripple_phase)

        # 9. Timing & Backlog Alerting
        t_analysis_done = time.perf_counter()
        analysis_dur_ms = (t_analysis_done - t_start) * 1000.0
        block_dur_ms = dt * 1000.0
        if analysis_dur_ms > 0.80 * block_dur_ms:
            self.backlog_warning_count += 1

        # Construct Immutable MusicState Snapshot
        state = MusicState(
            bands=norm_bands,
            onset=norm_onset,
            raw_flux=flux,
            kick=norm_kick,
            snare=norm_snare,
            hat=norm_hat,
            bass=norm_bass,
            sub_bass=norm_sub,
            mid=norm_mid,
            transient=composite_transient,
            bpm=bpm,
            bpm_confidence=self.tempo_tracker.bpm_confidence,
            beat_phase=predictive_phase,
            bar_pos=bar_pos,
            energy=energy,
            energy_trend=energy_trend,
            centroid=centroid,
            centroid_norm=centroid_norm,
            complexity=round(complexity, 3),
            intensity=intensity,
            tension=tension,
            impact=impact,
            section=sec,
            section_age=round(sec_age, 2),
            section_progress=round(sec_prog, 2),
            drop_strength=drop_str,
            silent=is_silent,
            source_preset=self.source_preset,
            speech_dominance=round(speech_dominance, 3),
            is_extreme_bass=is_extreme_bass,
            white_strobe=white_strobe,
            bass_ripple_phase=round(self.bass_ripple_phase, 1),
            chroma=chroma,
            key_hue=round(key_hue, 1),
            mode=mode,
            key_confidence=round(key_conf, 2),
            valence=0.7 if mode == "major" else 0.35,
            arousal=round(arousal, 2),
            palette=palette,
            harmonic_ratio=round(harmonic_ratio, 2),
            timestamp=round(stream_time, 3),
            t_audio_recv=t_audio_recv,
            t_analysis_done=t_analysis_done,
            analysis_duration_ms=round(analysis_dur_ms, 3)
        )

        self._current_state = state
        return state


# ── 8. Central Audio Capture Ring Buffer & Coordinator (Phase 1) ─────────────

class AudioRingBuffer:
    """Thread-safe circular ring buffer for incoming PCM audio blocks."""
    def __init__(self, capacity_samples: int = 44100 * 4):
        self.capacity = capacity_samples
        self.buffer = np.zeros(capacity_samples, dtype=np.float32)
        self.write_idx = 0
        self.total_samples_written = 0
        self._lock = threading.Lock()

    def write(self, data: np.ndarray):
        n = len(data)
        if n == 0:
            return
        with self._lock:
            end_idx = self.write_idx + n
            if end_idx <= self.capacity:
                self.buffer[self.write_idx:end_idx] = data
            else:
                first_part = self.capacity - self.write_idx
                self.buffer[self.write_idx:] = data[:first_part]
                self.buffer[:n - first_part] = data[first_part:]
            self.write_idx = (self.write_idx + n) % self.capacity
            self.total_samples_written += n

    def read_latest(self, n_samples: int) -> np.ndarray:
        with self._lock:
            if n_samples >= self.capacity:
                n_samples = self.capacity
            start_idx = (self.write_idx - n_samples) % self.capacity
            if start_idx + n_samples <= self.capacity:
                return self.buffer[start_idx:start_idx + n_samples].copy()
            else:
                first_part = self.capacity - start_idx
                out = np.empty(n_samples, dtype=np.float32)
                out[:first_part] = self.buffer[start_idx:]
                out[first_part:] = self.buffer[:n_samples - first_part]
                return out


class AudioCaptureCoordinator:
    """
    Shared audio capture and analysis worker with explicit lifecycle status.

    Status values are "stopped", "starting", "active", and "error". A capture
    failure is terminal for this run and is exposed to the UI instead of leaving
    _running=True after the worker has silently returned.
    """
    def __init__(
        self,
        samplerate: int = 44100,
        blocksize: int = 512,
        preferred_device: str | None = None,
        sensitivity: float = 1.0,
        lookahead_ms: float = 40.0,
    ):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.preferred_device = preferred_device
        self.analyzer = MusicAnalyzer(
            samplerate=samplerate,
            blocksize=blocksize,
            sensitivity=sensitivity,
            latency_lookahead_ms=lookahead_ms,
        )
        self.ring_buffer = AudioRingBuffer(capacity_samples=samplerate * 4)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._subscribers: set = set()
        self.new_frame_event = threading.Event()
        self._stop_event = threading.Event()
        self.status = "stopped"
        self.last_error: Optional[str] = None
        self.active_device_name: Optional[str] = None

        t_now = time.perf_counter()
        self._latest_slot: Tuple[MusicState, Dict[str, float]] = (
            MusicState(),
            {"t_audio_recv": t_now, "t_analysis_done": t_now},
        )
        self.sample_clock: float = 0.0
        self.total_samples: int = 0

    def register_subscriber(self, sub: Any):
        with self._lock:
            self._subscribers.add(sub)

    def unregister_subscriber(self, sub: Any):
        with self._lock:
            self._subscribers.discard(sub)

    def get_latest_state(self) -> Tuple[MusicState, Dict[str, float]]:
        return self._latest_slot

    @property
    def latest_state(self) -> MusicState:
        return self._latest_slot[0]

    def _set_error(self, message: str):
        with self._lock:
            self._running = False
            self.status = "error"
            self.last_error = str(message)
            event = self._stop_event
        event.set()
        self.new_frame_event.set()

    def start(self):
        with self._lock:
            if self._running:
                return
            if self._thread is not None and self._thread.is_alive():
                self.status = "error"
                self.last_error = "Previous audio-capture worker is still running; refusing to start a second worker."
                return
            self._running = True
            self.status = "starting"
            self.last_error = None
            self._stop_event = threading.Event()
            stop_event = self._stop_event
            self._thread = threading.Thread(
                target=self._worker,
                args=(stop_event,),
                daemon=True,
                name="AudioCaptureCoordinatorWorker",
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False
            event = self._stop_event
            thread = self._thread
        event.set()
        self.new_frame_event.set()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            if thread and thread.is_alive():
                self.status = "error"
                self.last_error = "Audio-capture worker did not stop within 2 seconds."
            elif self.status != "error":
                self.status = "stopped"
                self.last_error = None
            if thread and not thread.is_alive() and self._thread is thread:
                self._thread = None

    def is_running(self) -> bool:
        return self._running

    def _worker(self, stop_event: Optional[threading.Event] = None):
        from src.music_reactive import get_audio_input_source
        from src.master_volume import get_master_volume_probe

        stop_event = stop_event or self._stop_event
        try:
            mic = get_audio_input_source(self.samplerate, self.blocksize, self.preferred_device)
        except Exception as exc:
            self._set_error(f"Audio input discovery failed: {exc}")
            return
        if not mic:
            self._set_error(
                "No audio input source was found. Check the selected loopback device and audio permissions."
            )
            return
        if stop_event.is_set() or not self._running:
            return
        self.active_device_name = getattr(mic, "name", None)

        try:
            vol_probe = get_master_volume_probe()
            with self._lock:
                if stop_event.is_set() or not self._running:
                    return
                self.status = "active"

            silent_chunks = 0
            next_source_probe = time.monotonic() + 2.0
            while self._running and not stop_event.is_set():
                with mic.recorder(samplerate=self.samplerate, blocksize=self.blocksize, channels=1) as rec:
                    while self._running and not stop_event.is_set():
                        t_recv = time.perf_counter()
                        data = rec.record(numframes=self.blocksize)
                        raw_samples = data[:, 0]
                        samples = vol_probe.compensate_samples(raw_samples)
                        rms = float(np.sqrt(np.mean(samples ** 2)))
                        if rms < 0.0005:
                            silent_chunks += 1
                            now_mono = time.monotonic()
                            if silent_chunks > 180 and now_mono >= next_source_probe:
                                next_source_probe = now_mono + 2.0
                                try:
                                    new_mic = get_audio_input_source(
                                        self.samplerate, self.blocksize, self.preferred_device
                                    )
                                except Exception as exc:
                                    new_mic = None
                                    print(f"[AudioCapture] Input rescan failed: {exc}")
                                if new_mic and getattr(new_mic, "id", None) != getattr(mic, "id", None):
                                    mic = new_mic
                                    self.active_device_name = getattr(mic, "name", None)
                                    print(f"[AudioCapture] Switched to live source: {self.active_device_name}")
                                    silent_chunks = 0
                                    break
                                # Reset the initial threshold so unchanged silence is not
                                # probed on every 512-sample chunk.
                                silent_chunks = 0
                        else:
                            silent_chunks = 0

                        self.ring_buffer.write(samples)
                        self.total_samples += len(samples)
                        self.sample_clock = self.total_samples / float(self.samplerate)

                        state = self.analyzer.process_samples(
                            samples, now=self.sample_clock, t_recv=t_recv
                        )
                        t_done = time.perf_counter()
                        self._latest_slot = (
                            state,
                            {
                                "t_audio_recv": t_recv,
                                "t_analysis_done": t_done,
                                "analysis_ms": (t_done - t_recv) * 1000.0,
                            },
                        )
                        self.new_frame_event.set()
        except Exception as exc:
            if self._running and not stop_event.is_set():
                self._set_error(f"Audio capture failed: {exc}")
        finally:
            with self._lock:
                if stop_event.is_set() or not self._running:
                    if self.status != "error":
                        self.status = "stopped"
                        self.last_error = None
                    self._running = False
            self.new_frame_event.set()
