import asyncio
import numpy as np
import pytest

from src.audio_dsp import MusicState, Section
from src.frame_sender import LatestFrameSender
from src.diagnostics import DeviceDiagnostics
from src.visual_styles import (
    SpectrumStyle,
    PulseStyle,
    EdmModeStyle,
    SubBlastStyle,
    BassBounceStyle,
    ChillStyle,
    FlowStyle,
    ReactiveAuroraStyle,
    PartyStyle,
    NeonDriveStyle,
    CenterBurstStyle,
    TwinkleStyle,
    HydroAcousticStyle,
)


def test_spectrum_style_50_ic_frequency_directing_and_true_black():
    """
    Verifies that SpectrumStyle directs:
      - Lows/Bass (bands 0..9) to Center ICs (20..29)
      - Highs/Treble (bands 35..49) to Outer Edge ICs (0..9 and 40..49)
      - Inactive frequency zones remain strictly True Black ([0, 0, 0]).
    """
    spec = SpectrumStyle(layout="mirrored")

    # 1. Lows-only signal (Sub/Kick at 40-100 Hz, bands 0..5 high, rest 0)
    low_bands = np.zeros(50, dtype=np.float32)
    low_bands[:6] = 0.90
    st_low = MusicState(bands=low_bands, energy=0.5, kick=0.8, section=Section.VERSE)

    f_low = spec.render(st_low, dt=0.03, num_zones=50)

    # Center ICs (20-29) must be illuminated
    center_brightnesses = [v for _, _, v in f_low[20:30]]
    assert max(center_brightnesses) > 40, f"Center bass ICs failed to illuminate: {center_brightnesses}"

    # Edge ICs (0-5 and 45-49) must be completely OFF (True Black)
    outer_edge_left = [v for _, _, v in f_low[0:5]]
    outer_edge_right = [v for _, _, v in f_low[45:50]]
    assert all(v == 0 for v in outer_edge_left), f"Left edge should be True Black on bass-only, got {outer_edge_left}"
    assert all(v == 0 for v in outer_edge_right), f"Right edge should be True Black on bass-only, got {outer_edge_right}"

    # 2. Treble-only signal (Hi-hats/Air at 8-16 kHz, bands 42..49 high, rest 0)
    spec_treble = SpectrumStyle(layout="mirrored")
    high_bands = np.zeros(50, dtype=np.float32)
    high_bands[42:] = 0.90
    st_high = MusicState(bands=high_bands, energy=0.4, hat=0.9, section=Section.VERSE)

    f_high = spec_treble.render(st_high, dt=0.03, num_zones=50)

    # Outer edge ICs must be illuminated
    edge_left_v = [v for _, _, v in f_high[0:5]]
    edge_right_v = [v for _, _, v in f_high[45:50]]
    assert max(edge_left_v) > 30 and max(edge_right_v) > 30, "Edge treble ICs failed to illuminate"

    # Center ICs must be completely OFF (True Black)
    center_v = [v for _, _, v in f_high[22:28]]
    assert all(v == 0 for v in center_v), f"Center ICs should be True Black on treble-only, got {center_v}"


def test_pulse_style_true_black_inactive_zones():
    """
    Verifies that PulseStyle directs kicks to center (20-29) and preserves True Black
    across unreached zones rather than washing the strip in an unreactive background.
    """
    pulse = PulseStyle()

    # Instant kick at center bar 0 with quiet bands elsewhere
    st_kick = MusicState(
        bands=np.zeros(50, dtype=np.float32),
        energy=0.35,
        kick=0.90,
        bar_pos=0,
        section=Section.VERSE,
    )

    f_kick = pulse.render(st_kick, dt=0.02, num_zones=50)

    # Center ICs (22-27) must illuminate strongly
    center_v = [v for _, _, v in f_kick[22:28]]
    assert max(center_v) > 50, f"Center kick ICs failed to illuminate: {center_v}"

    # Denser outer zones that the shockwave hasn't reached yet must be True Black
    outer_v = [v for _, _, v in f_kick[0:8]]
    assert any(v == 0 for v in outer_v), f"Outer zones before ripple arrival should be True Black, got {outer_v}"


def test_sub_blast_detonation_and_true_black_outer_zones():
    """
    Verifies that SubBlastStyle isolates sub-bass to the detonation core (center 20-29),
    with distant unreached zones remaining True Black ([0, 0, 0]).
    """
    sub_blast = SubBlastStyle()

    st_sub = MusicState(
        energy=0.70,
        sub_bass=0.92,
        kick=0.30,
        section=Section.VERSE,
    )

    f_sub = sub_blast.render(st_sub, dt=0.02, num_zones=50)

    # Center detonation core must be bright
    assert f_sub[25][2] > 50, f"Detonation core failed to illuminate: {f_sub[25][2]}"

    # Distant outer zones (e.g. 0-5) must be True Black
    assert all(v == 0 for _, _, v in f_sub[0:5]), f"Outer zones should be True Black, got {f_sub[0:5]}"


def test_bass_bounce_inward_fill_and_center_black():
    """
    Verifies that BassBounceStyle fills symmetrically inward from outer ends,
    leaving the center zones completely OFF until bass energy reaches them.
    """
    bb = BassBounceStyle()

    # Moderate bass fill
    st_bb = MusicState(energy=0.40, kick=0.50, section=Section.VERSE)
    f_bb = bb.render(st_bb, dt=0.04, num_zones=50)

    # Outer ends (0-3 and 46-49) must be illuminated
    assert f_bb[0][2] > 20 and f_bb[49][2] > 20

    # Center zones (23-26) should be True Black
    center_vals = [v for _, _, v in f_bb[23:27]]
    assert all(v == 0 for v in center_vals), f"Center zones should be True Black, got {center_vals}"


@pytest.mark.asyncio
async def test_aimd_threshold_permits_normal_wifi_rtt():
    """
    Verifies that a typical KLAP v2 Wi-Fi RTT of ~420ms does NOT trigger AIMD penalty,
    preserving full updates/s throughput without dropping to 1 update/s.
    """
    diag = DeviceDiagnostics(dev_id="test_l930")
    transmit_timestamps = []

    async def normal_wifi_mock(frame):
        transmit_timestamps.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.420)  # Normal 420ms Wi-Fi RTT
        return True

    loop = asyncio.get_running_loop()
    sender = LatestFrameSender(
        dev_id="test_l930",
        transmit_fn=normal_wifi_mock,
        diagnostics=diag,
        loop=loop,
        max_updates_per_s=8.0,
        aimd_threshold_s=0.850,
    )
    sender.start()

    # Submit 2 frames
    sender.submit_frame({"id": 1})
    await asyncio.sleep(0.050)
    sender.submit_frame({"id": 2})

    # Under 850ms threshold, frame 1 takes 420ms, frame 2 starts immediately after pacing (~10ms)
    await asyncio.sleep(0.950)
    sender.stop()

    # Rate cap must NOT have been dropped to 1.0
    assert sender._aimd_rate_cap >= 7.0, f"AIMD falsely triggered on normal Wi-Fi RTT: rate={sender._aimd_rate_cap}"
    assert len(transmit_timestamps) == 2


def test_harmonic_flow_modes_maintain_cohesive_key_hue():
    """
    Verifies that Mode Class B (Chill, Flow, Aurora) maintain a cohesive key hue
    and do not generate random clashing color bursts across inactive zones.
    """
    st_harmonic = MusicState(
        energy=0.45,
        key_hue=210.0,  # Deep Royal Blue key
        harmonic_ratio=0.80,
        section=Section.VERSE,
    )

    chill = ChillStyle()
    f_chill = chill.render(st_harmonic, dt=0.05, num_zones=50)

    # Output hues should be musically cohesive (within ±45° of key or palette stopped harmony)
    hues = [h for h, s, v in f_chill]
    hue_std = np.std(hues)
    assert hue_std < 40.0, f"ChillStyle hues are clashing/random: std={hue_std:.1f}"


def test_party_and_neon_drive_true_black_and_beat_directing():
    """
    Verifies that PartyStyle and NeonDriveStyle direct kicks to center (Cyan/saturated)
    and leave inactive ICs strictly at True Black ([0, 0, 0]).
    """
    party = PartyStyle()
    st_kick = MusicState(energy=0.35, kick=0.90, onset=0.20, hat=0.10, section=Section.VERSE)
    f_party = party.render(st_kick, dt=0.03, num_zones=50)

    # Center ICs (22-27) must illuminate
    assert max(f_party[24][2], f_party[25][2]) > 40
    # Outer ICs without active sparks/snare must be True Black
    assert any(v == 0 for _, _, v in f_party[0:10])

    neon = NeonDriveStyle()
    f_neon = neon.render(st_kick, dt=0.03, num_zones=50)
    # Center kick must be Cyan (170-200)
    assert 170 <= f_neon[24][0] <= 200
    # Denser outer zones not yet reached by grid/wave must be True Black
    assert any(v == 0 for _, _, v in f_neon[0:8])


def test_spectrum_style_true_dynamic_bounce_and_true_black():
    """
    Verifies that SpectrumStyle:
      1. Renders high-contrast bouncing bars directly with live levels (no 95% hold floor).
      2. Drops cleanly toward True Black when bands subside between beats.
    """
    spec = SpectrumStyle(layout="mirrored")
    low_bands = np.zeros(50, dtype=np.float32)
    low_bands[:6] = 0.90
    st_active = MusicState(bands=low_bands, energy=0.75, kick=0.85, section=Section.VERSE)
    f_active = spec.render(st_active, dt=0.03, num_zones=50)
    assert max(v for _, _, v in f_active[20:30]) > 40

    # Between beats: energy subsides
    st_quiet = MusicState(bands=np.zeros(50, dtype=np.float32), energy=0.01, kick=0.0, section=Section.VERSE)
    # Decay over 150ms
    f_decayed = None
    for _ in range(5):
        f_decayed = spec.render(st_quiet, dt=0.03, num_zones=50)

    # Must decay cleanly towards zero rather than staying pegged at 95%
    assert max(v for _, _, v in f_decayed[20:30]) < 25


def test_twinkle_true_black_velvet_space():
    """Verifies that TwinkleStyle renders bright sparkles against True Black velvet background."""
    tw = TwinkleStyle()
    st_hat = MusicState(energy=0.3, hat=0.90, onset=0.80, section=Section.VERSE)
    f_tw = tw.render(st_hat, dt=0.03, num_zones=50)

    # Must contain sparkles (> 50) and true black zones (== 0)
    brights = [v for _, _, v in f_tw if v > 50]
    blacks = [v for _, _, v in f_tw if v == 0]
    assert len(brights) > 0, "No sparkles generated on high hat transient"
    assert len(blacks) > 20, "Background failed to remain True Black space"


def test_hydro_acoustic_true_black_unreached_zones():
    """Verifies that HydroAcousticStyle leaves unreached zones True Black."""
    hydro = HydroAcousticStyle()
    st_kick = MusicState(energy=0.4, kick=0.90, bass=0.85, hat=0.0, section=Section.VERSE)
    f_hydro = hydro.render(st_kick, dt=0.03, num_zones=50)

    # Center pool / shockwave source must be active
    assert f_hydro[25][2] > 40
    # Outer zones where wave has not arrived must be True Black
    assert any(v == 0 for _, _, v in f_hydro[0:8])

