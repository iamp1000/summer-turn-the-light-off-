from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Sequence


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def music_is_genuinely_active(state: Any) -> bool:
    """Conservative gate that excludes analyzed silence and low-level noise."""
    if state is None or bool(getattr(state, "silent", True)):
        return False
    if getattr(getattr(state, "section", None), "value", getattr(state, "section", None)) == "SILENT":
        return False
    try:
        energy = float(getattr(state, "energy", 0.0))
    except (TypeError, ValueError):
        return False
    return energy >= 0.015


def effective_send_rate(controller: Any, fallback_rate: float = 5.0) -> float:
    """Read current sender protection rate; does not modify or raise the cap."""
    sender = getattr(controller, "frame_sender", None) if controller is not None else None
    if sender is None:
        return max(0.5, float(fallback_rate))
    try:
        configured = float(getattr(sender, "max_updates_per_s", fallback_rate))
        aimd_cap = float(getattr(sender, "_aimd_rate_cap", configured))
        return max(0.5, min(configured, aimd_cap))
    except (TypeError, ValueError):
        return max(0.5, float(fallback_rate))


def silence_fade_duration(controller: Any, fallback_rate: float = 5.0) -> float:
    """Fade over at least ~0.75s and stretch under the sender's 1Hz protection mode."""
    rate = effective_send_rate(controller, fallback_rate)
    return max(0.75, 1.15 / rate)


def fade_hsv(hsv: Sequence[int], factor: float) -> tuple[int, int, int]:
    h, s, v = (int(hsv[0]) % 360, max(0, min(100, int(hsv[1]))), max(0, min(100, int(hsv[2]))))
    scale = clamp01(factor)
    if scale <= 0.0 or v <= 0:
        return (0, 0, 0)
    return (h, s, int(round(v * scale)))


def fade_segments(segments: Iterable[Sequence[int]], factor: float) -> list[list[int]]:
    scale = clamp01(factor)
    if scale <= 0.0:
        return [[0, 0, 0] for _ in segments]
    result: list[list[int]] = []
    for zone in segments:
        h, s, v = int(zone[0]) % 360, max(0, min(100, int(zone[1]))), max(0, min(100, int(zone[2])))
        result.append([h, s, int(round(v * scale))] if v > 0 else [0, 0, 0])
    return result


@dataclass
class MusicBrightnessFloor:
    """Small, temporary active-signal floor with asymmetric attack/release."""
    floor_percent: float = 5.5
    attack_tau: float = 0.18
    release_tau: float = 0.55
    level: float = 0.0

    def reset(self):
        self.level = 0.0

    def update(
        self,
        state: Any,
        dt: float,
        master_ceiling: float = 1.0,
        enabled: bool = True,
        force_inactive: bool = False,
    ) -> float:
        active = enabled and not force_inactive and music_is_genuinely_active(state)
        target = self.floor_percent * clamp01(master_ceiling) if active else 0.0
        tau = max(0.01, self.attack_tau if target > self.level else self.release_tau)
        alpha = 1.0 - math.exp(-max(0.0, float(dt)) / tau)
        self.level += alpha * (target - self.level)
        if self.level < 0.05:
            self.level = 0.0
        return self.level

    @staticmethod
    def apply_l900(hsv: Sequence[int], floor: float) -> tuple[int, int, int]:
        h, s, b = int(hsv[0]) % 360, max(0, min(100, int(hsv[1]))), max(0, min(100, int(hsv[2])))
        # A floor never turns a true-black renderer output on.
        return (h, s, max(b, int(round(floor)))) if b > 0 else (0, 0, 0)

    @staticmethod
    def apply_l930(segments: Iterable[Sequence[int]], floor: float) -> list[list[int]]:
        result = []
        floor_int = max(0, min(100, int(round(floor))))
        for zone in segments:
            h, s, v = int(zone[0]) % 360, max(0, min(100, int(zone[1]))), max(0, min(100, int(zone[2])))
            result.append([h, s, max(v, floor_int)] if v > 0 else [0, 0, 0])
        return result


class ZoneTemporalSmoother:
    """
    Antialiased temporal smoothing filter for 50-zone addressable LED strips.
    Smooths sharp discrete jumps in brightness and hue across successive frames
    while preserving zero-latency instant attack on musical transients and beats.
    """

    def __init__(self, num_zones: int = 50, attack_tau: float = 0.0, decay_tau: float = 0.040):
        self.num_zones = num_zones
        self.attack_tau = attack_tau
        self.decay_tau = decay_tau
        self._cur_h = [0.0] * num_zones
        self._cur_s = [0.0] * num_zones
        self._cur_v = [0.0] * num_zones
        self._initialized = False

    def reset(self):
        self._cur_v = [0.0] * self.num_zones
        self._initialized = False

    def process(
        self,
        target_segs: Sequence[Sequence[int]],
        dt: float,
        white_punch: float = 0.0,
        strobe: bool = False,
    ) -> list[list[int]]:
        num = min(len(target_segs), self.num_zones)
        dt = max(0.001, min(0.15, float(dt)))

        if not self._initialized:
            for i in range(num):
                self._cur_h[i] = float(target_segs[i][0])
                self._cur_s[i] = float(target_segs[i][1])
                self._cur_v[i] = float(target_segs[i][2])
            self._initialized = True

        out: list[list[int]] = []
        punch_active = white_punch > 15.0 or strobe
        punch_ratio = min(1.0, (white_punch - 15.0) / 85.0) if white_punch > 15.0 else (1.0 if strobe else 0.0)

        for i in range(num):
            th, ts, tv = float(target_segs[i][0]), float(target_segs[i][1]), float(target_segs[i][2])

            # White strobe / extreme bass flash compositing
            if punch_active and tv > 10.0:
                ts = ts * (1.0 - punch_ratio * 0.90)
                tv = min(100.0, tv + (100.0 - tv) * punch_ratio)

            # Asymmetric brightness smoothing: instant snappy attack, clean musical decay
            if tv > self._cur_v[i]:
                # Instant attack: beats land with immediate impact (0 lag)
                if self.attack_tau <= 0.005:
                    self._cur_v[i] = tv
                else:
                    alpha_v = 1.0 - math.exp(-dt / self.attack_tau)
                    self._cur_v[i] += alpha_v * (tv - self._cur_v[i])
            else:
                alpha_v = 1.0 - math.exp(-dt / max(0.005, self.decay_tau))
                self._cur_v[i] += alpha_v * (tv - self._cur_v[i])

            if tv <= 0.5 and self._cur_v[i] < 1.0:
                self._cur_v[i] = 0.0

            # If zone was dark or leaping up, snap hue and saturation instantly
            if self._cur_v[i] < 2.0 or tv > self._cur_v[i] * 1.5:
                self._cur_h[i] = th
                self._cur_s[i] = ts
            else:
                diff_h = ((th - self._cur_h[i] + 180.0) % 360.0) - 180.0
                alpha_h = 1.0 - math.exp(-dt / 0.020)
                self._cur_h[i] = (self._cur_h[i] + alpha_h * diff_h) % 360.0

                alpha_s = 1.0 - math.exp(-dt / 0.020)
                self._cur_s[i] += alpha_s * (ts - self._cur_s[i])

            final_h = int(round(self._cur_h[i])) % 360
            final_s = max(0, min(100, int(round(self._cur_s[i]))))
            final_v = max(0, min(100, int(round(self._cur_v[i]))))
            out.append([final_h, final_s, final_v])

        return out
