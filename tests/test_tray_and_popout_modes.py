from __future__ import annotations
from unittest.mock import MagicMock
import pytest

from src.tray import TrayApp
from src.window_layout import tray_window_geometry, responsive_window_geometry
from src.gui import TapoGUI


def test_tray_app_builds_menu_with_tray_mode_and_popout():
    show_tray_mock = MagicMock()
    pop_out_mock = MagicMock()
    hide_mock = MagicMock()
    quit_mock = MagicMock()

    tray = TrayApp(
        mode_names=["work", "movie"],
        effect_names=["ambient_drift"],
        on_mode_apply=MagicMock(),
        on_effect_apply=MagicMock(),
        on_toggle_power=MagicMock(),
        on_music_toggle=MagicMock(),
        on_screen_toggle=MagicMock(),
        on_show_dashboard=MagicMock(),
        on_hide_dashboard=hide_mock,
        on_show_tray=show_tray_mock,
        on_pop_out=pop_out_mock,
        on_quit=quit_mock,
    )

    menu = tray._build_menu()
    items = list(menu.items)
    item_texts = [getattr(item, "text", "") for item in items]

    assert "Quick Controls (Tray Mode)" in item_texts
    assert "Pop Out (Normal Window)" in item_texts
    assert "Hide Window to Tray" in item_texts
    assert "Toggle Power" in item_texts
    assert "Quit" in item_texts


def test_tray_window_geometry_calculation():
    # 1080p display
    w, h, x, y, min_w, min_h = tray_window_geometry(1920, 1080)
    assert 360 <= w <= 420
    assert 520 <= h <= 680
    assert x + w <= 1920
    assert y + h <= 1080
    assert x > 1400  # Anchored right
    assert y > 300   # Anchored near bottom


@pytest.fixture
def fake_hub():
    hub = MagicMock()
    d1 = MagicMock(model="L900", state={"power": True, "brightness": 50, "active_label": "Work"})
    d1.name = "moo ni tor"
    d2 = MagicMock(model="L930", state={"power": True, "brightness": 60, "active_label": "Ambient Drift"})
    d2.name = "chhat"
    hub.devices = {"strip1": d1, "strip2": d2}
    hub.config = {"web": {"port": 8765}, "modes": {"work": {}}, "effects": {}}
    hub.get_diagnostics.return_value = {}
    hub.get_audio_telemetry.return_value = {}
    return hub


def test_tapo_gui_mode_lifecycle(fake_hub):
    on_quit = MagicMock()
    
    # 1. Initialize in default "tray" mode
    gui = TapoGUI(fake_hub, on_quit=on_quit, default_mode="tray")
    try:
        assert gui.window_mode == "tray"
        assert "Pop Out" in gui.btn_mode_toggle.cget("text")

        # 2. Test show_window in tray mode
        gui.show_window()
        assert gui.window_mode == "tray"
        assert gui.app.overrideredirect() is True or gui.app.overrideredirect() == 1
        assert gui.btn_hide.cget("text") == "✕"

        # 3. Test pop_out() transition to normal window
        gui.pop_out()
        assert gui.window_mode == "normal"
        assert "Mini Tray" in gui.btn_mode_toggle.cget("text")
        assert gui.btn_hide.cget("text") == "✕"

        # 4. Test dock_to_tray() transition back to tray mode
        gui.dock_to_tray()
        assert gui.window_mode == "tray"
        assert "Pop Out" in gui.btn_mode_toggle.cget("text")

        # 5. Test toggle_window_mode()
        gui.toggle_window_mode()
        assert gui.window_mode == "normal"
        gui.toggle_window_mode()
        assert gui.window_mode == "tray"

        # 6. Test hide_window() and toggle_tray_window()
        gui.hide_window()
        gui.toggle_tray_window()
    finally:
        gui.app.destroy()


def test_make_window_stay_in_taskbar():
    from src.gui import make_window_stay_in_taskbar
    mock_win = MagicMock()
    mock_win.winfo_id.return_value = 0
    make_window_stay_in_taskbar(mock_win)


def test_starred_effects_filtering_and_toggle(fake_hub):
    on_quit = MagicMock()
    gui = TapoGUI(fake_hub, on_quit=on_quit, default_mode="normal")
    try:
        assert isinstance(gui.starred_effects, set)
        gui._set_fx_filter("starred")
        assert gui._fx_filter_mode == "starred"
        gui._set_fx_filter("all")
        assert gui._fx_filter_mode == "all"
    finally:
        gui.app.destroy()

