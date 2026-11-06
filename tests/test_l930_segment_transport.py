from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.device_l930 import L930Controller, make_50_zone_effect


def test_l930_effect_preserves_all_50_distinct_zones():
    colors = [[(i * 7) % 360, 82, 55 + (i % 35)] for i in range(50)]

    effect = make_50_zone_effect(colors, pre_corrected=True)

    assert effect.sequence == colors
    assert len(effect.sequence) == 50
    assert effect.sequence[0] != effect.sequence[-1]


class _SuccessfulTry:
    @staticmethod
    def is_success():
        return True


class _RawDevice:
    def __init__(self):
        self.effect = None

    async def set_light_effect(self, effect):
        self.effect = effect
        return _SuccessfulTry()


def test_controller_sends_frames_via_supported_50_zone_effect():
    device = _RawDevice()
    controller = object.__new__(L930Controller)
    controller._device = device
    controller._is_on = True
    controller._lock = asyncio.Lock()
    controller._failure_streak = 0
    controller._last_successful_response = 0.0
    controller.last_b = 50
    controller.last_segments = [[0, 0, 0] for _ in range(50)]
    controller.music_transition_ms = 0
    controller.default_transition_ms = 0

    colors = [[i * 5 % 360, 100, 70] for i in range(50)]
    accepted = asyncio.run(controller.transmit_frame({"segments": colors, "_pre_corrected": True}))

    assert accepted is True
    assert device.effect is not None
    assert device.effect.sequence == colors
    assert len(device.effect.sequence) == 50
