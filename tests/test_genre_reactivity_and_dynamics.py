import numpy as np
import pytest
from src.audio_dsp import (
    LowPassKickDetector,
    DynamicSongCalibrator,
    MusicAnalyzer,
    MusicState,
    Section,
)
from src.visual_styles import (
    AcousticStringStyle,
    HydroAcousticStyle,
    LofiVinylStyle,
    MelodicContourStyle,
    BpmResonatorStyle,
    SubBlastStyle,
    create_style_instances,
)


def test_rock_metal_double_kick_separation_at_high_bpm():
    """
    Verifies that LowPassKickDetector dynamically adapts its decay envelope at high BPM (e.g. 180-200 BPM)
    so rapid double-kick strikes produce distinct, separated transient valleys and peaks.
    """
    fs = 44100
    detector = LowPassKickDetector(samplerate=fs, fc=120.0)
    
    # Generate two 60 Hz kick bursts separated by 90ms (typical of 16th-note double kick at 170 BPM)
    kick_samples = int(fs * 0.035)  # 35ms kick thump
    t_kick = np.arange(kick_samples) / fs
    kick_wave = (np.sin(2 * np.pi * 60 * t_kick) * np.exp(-t_kick * 30)).astype(np.float32)
    
    silence_samples = int(fs * 0.055)  # 55ms interval between strikes
    silence = np.zeros(silence_samples, dtype=np.float32)
    
    # First kick
    env_peak_1 = detector.process(kick_wave, dt=len(kick_wave) / fs, bpm=180.0)
    assert env_peak_1 > 0.15, "First kick thump should produce a strong envelope response"
    
    # Inter-kick gap (envelope should decay cleanly for the next strike)
    env_valley = detector.process(silence, dt=len(silence) / fs, bpm=180.0)
    assert env_valley < env_peak_1 * 0.65, "Envelope must decay sufficiently between rapid double kicks"
    
    # Second kick (must produce a fresh distinct peak above the valley)
    env_peak_2 = detector.process(kick_wave, dt=len(kick_wave) / fs, bpm=180.0)
    assert env_peak_2 > env_valley * 1.30, "Second double-kick strike must punch cleanly above the valley"


def test_rap_trap_sub_bass_808_glide_detection():
    """
    Verifies that deep 808 sub-bass glides (35-65 Hz) are captured in state.sub_bass
    and advance the bass ripple hue phase for chromatic color rippling.
    """
    fs = 44100
    analyzer = MusicAnalyzer(samplerate=fs, blocksize=1024, sensitivity=1.0)
    
    # Generate 808 sub-bass glide: pitch sweep from 65 Hz down to 35 Hz over 0.4s
    t_glide = np.linspace(0, 0.4, int(fs * 0.4), endpoint=False, dtype=np.float32)
    freq_sweep = np.linspace(65, 35, len(t_glide))
    phase = 2 * np.pi * np.cumsum(freq_sweep) / fs
    glide_samples = (0.75 * np.sin(phase)).astype(np.float32)
    
    initial_phase = analyzer.bass_ripple_phase
    
    # Process blocks through analyzer
    sub_bass_detected = False
    for i in range(0, len(glide_samples), 1024):
        block = glide_samples[i:i+1024]
        if len(block) < 1024:
            break
        state = analyzer.process_samples(block)
        if state.sub_bass > 0.30:
            sub_bass_detected = True
            
    assert sub_bass_detected, "Deep 808 glide must be detected in state.sub_bass"
    assert analyzer.bass_ripple_phase != initial_phase, "808 sub-bass surge must advance bass_ripple_phase"


def test_volume_agnostic_adaptive_dynamic_range():
    """
    Verifies that quiet music (low RMS ~0.005) scales smoothly across the full normalized
    energy range (0.0 to 1.0) rather than being crushed by a rigid, high floor.
    """
    calibrator = DynamicSongCalibrator(sensitivity=1.0)
    
    # Warm up calibrator with quiet listening volume (RMS fluctuating between 0.003 and 0.008)
    now = 0.0
    dt = 0.03
    for step in range(50):
        # Quiet verse/intro
        val = 0.003 + 0.005 * (step % 5) / 4.0
        now += dt
        calibrator.update(rms=val, kick=val * 0.5, now=now, dt=dt)
    
    # Check that a quiet peak (RMS = 0.008) produces meaningful normalized energy (> 0.60)
    energy, _, _, is_silent = calibrator.update(rms=0.008, kick=0.004, now=now + dt, dt=dt)
    assert not is_silent, "Audible quiet music (-42 dBFS) must not be flagged silent"
    assert energy > 0.60, f"Quiet music peak should adaptively scale to full energy, got {energy}"


def test_all_music_styles_strict_silence_shutdown():
    """
    Verifies that every visual style returns strictly [(0, 0, 0)] * num_zones when state.silent is True
    or energy == 0.0, with zero residual light leaks.
    """
    silent_state = MusicState(
        energy=0.0,
        kick=0.0,
        snare=0.0,
        hat=0.0,
        bass=0.0,
        mid=0.0,
        sub_bass=0.0,
        section=Section.SILENT,
        silent=True,
    )
    
    styles = [
        AcousticStringStyle(),
        HydroAcousticStyle(),
        LofiVinylStyle(),
        MelodicContourStyle(),
        BpmResonatorStyle(),
        SubBlastStyle(),
    ]
    
    for s in styles:
        frame = s.render(silent_state, dt=0.03, num_zones=50)
        assert len(frame) == 50
        for h, sat, v in frame:
            assert v == 0, f"{s.__class__.__name__} leaked brightness (v={v}) during silence!"


def test_sub_blast_style_responds_to_sub_bass():
    """
    Verifies that SubBlastStyle triggers kinetic outward shockwaves and wide-spectrum colors
    specifically when sub_bass energy is high.
    """
    sub_blast = SubBlastStyle()
    
    sub_state = MusicState(
        energy=0.85,
        kick=0.20,  # low kick
        sub_bass=0.88,  # high 808 sub-bass
        bass=0.85,
        bass_ripple_phase=180.0,
        section=Section.VERSE,
    )
    
    frame = sub_blast.render(sub_state, dt=0.03, num_zones=50)
    
    # Center zone should have high brightness from the sub-bass detonation
    center_v = frame[25][2]
    assert center_v > 50, f"SubBlastStyle should detonate strongly on high sub_bass, got center_v={center_v}"
