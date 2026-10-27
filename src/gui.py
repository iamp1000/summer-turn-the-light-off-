from __future__ import annotations
import colorsys
import json
import math
from pathlib import Path
import socket
import time
import customtkinter as ctk
from src.colorpicker import ModernColorPicker

# ── Dynamic Glassmorphism Theme Palettes (Matching Reference Designs) ──────────
THEMES = {
    "ambient_drift": {
        "name": "Ambient Drift",
        "bg": "#120a22",
        "surface": "#1d1136",
        "surface_raised": "#271747",
        "surface_high": "#362061",
        "border": "#46297d",
        "border_glow": "#8b5cf6",
        "accent": "#8b5cf6",
        "accent_glow": "#a78bfa",
        "accent_soft": "#311854",
        "power_glow": "#8b5cf6",
        "hero_tint": "#231245",
        "hero_border": "#5c2d9e",
        "text_primary": "#f5f3ff",
        "text_secondary": "#c4b5fd",
        "text_muted": "#8572a8",
    },
    "northern_lights": {
        "name": "Northern Lights",
        "bg": "#061b17",
        "surface": "#0d362e",
        "surface_raised": "#124a3f",
        "surface_high": "#1a6355",
        "border": "#1b6d5e",
        "border_glow": "#10b981",
        "accent": "#10b981",
        "accent_glow": "#34d399",
        "accent_soft": "#11473d",
        "power_glow": "#10b981",
        "hero_tint": "#0f3d35",
        "hero_border": "#1b7d6a",
        "text_primary": "#ecfdf5",
        "text_secondary": "#a7f3d0",
        "text_muted": "#64948a",
    },
    "fireplace": {
        "name": "Fireplace",
        "bg": "#1c0b05",
        "surface": "#38170a",
        "surface_raised": "#4d200e",
        "surface_high": "#662b14",
        "border": "#733017",
        "border_glow": "#f97316",
        "accent": "#f97316",
        "accent_glow": "#fb923c",
        "accent_soft": "#4f1f0d",
        "power_glow": "#f97316",
        "hero_tint": "#42190a",
        "hero_border": "#8f3b18",
        "text_primary": "#fff7ed",
        "text_secondary": "#fed7aa",
        "text_muted": "#996b57",
    },
    "sakura": {
        "name": "Sakura",
        "bg": "#1f0915",
        "surface": "#3d132b",
        "surface_raised": "#541a3c",
        "surface_high": "#6e234f",
        "border": "#7d2859",
        "border_glow": "#f43f5e",
        "accent": "#f43f5e",
        "accent_glow": "#fb7185",
        "accent_soft": "#57183c",
        "power_glow": "#f43f5e",
        "hero_tint": "#471531",
        "hero_border": "#962c68",
        "text_primary": "#fff1f2",
        "text_secondary": "#fecdd3",
        "text_muted": "#9e607f",
    },
    "golden_hour": {
        "name": "Golden Hour",
        "bg": "#1f1304",
        "surface": "#3d2609",
        "surface_raised": "#54340d",
        "surface_high": "#6e4512",
        "border": "#7d4f15",
        "border_glow": "#f59e0b",
        "accent": "#f59e0b",
        "accent_glow": "#fbbf24",
        "accent_soft": "#54350c",
        "power_glow": "#f59e0b",
        "hero_tint": "#472b08",
        "hero_border": "#965c12",
        "text_primary": "#fffbeb",
        "text_secondary": "#fde68a",
        "text_muted": "#997b52",
    },
    "deep_ocean": {
        "name": "Deep Ocean",
        "bg": "#051322",
        "surface": "#0c2847",
        "surface_raised": "#103761",
        "surface_high": "#164c85",
        "border": "#1b5a9e",
        "border_glow": "#06b6d4",
        "accent": "#06b6d4",
        "accent_glow": "#22d3ee",
        "accent_soft": "#0f3a69",
        "power_glow": "#06b6d4",
        "hero_tint": "#0d3259",
        "hero_border": "#1e6bb5",
        "text_primary": "#ecfeff",
        "text_secondary": "#a5f3fc",
        "text_muted": "#5e829e",
    },
}

# Keep the surfaces neutral and restrained across themes. Themes now change the
# accent family, not every background panel, which improves hierarchy and contrast.
for _palette in THEMES.values():
    _palette.update({
        "bg": "#0d1017",
        "surface": "#151923",
        "surface_raised": "#1c2230",
        "surface_high": "#252c3b",
        "border": "#30394a",
        "text_primary": "#f2f4f8",
        "text_secondary": "#b1bacb",
        "text_muted": "#7f8aa0",
    })

def get_theme_for_label(label: str) -> str:
    lbl = (label or "").lower()
    if any(k in lbl for k in ("drift", "cyber", "pulse", "shockwave", "melody", "strobe", "matrix", "synthwave", "glitch", "work", "auto", "hybrid", "director")):
        return "ambient_drift"
    if any(k in lbl for k in ("northern", "aurora", "green", "spring", "forest", "tree")):
        return "northern_lights"
    if any(k in lbl for k in ("fire", "candle", "flame", "lava", "ember", "dinner")):
        return "fireplace"
    if any(k in lbl for k in ("sakura", "pink", "rose", "blossom", "heart", "sunset_glow", "sleep", "plasma")):
        return "sakura"
    if any(k in lbl for k in ("gold", "sun", "warm", "amber", "sunrise", "reading", "mirror", "mirror_eq", "spectrum")):
        return "golden_hour"
    if any(k in lbl for k in ("ocean", "water", "rain", "blue", "cyan", "sea", "deep", "ice", "cool", "comet", "starfield", "stars", "wave")):
        return "deep_ocean"
    return "ambient_drift"

MODE_COLORS = {
    "work":        "#fff9e6",
    "deep_focus":  "#ffffff",
    "coding_night":"#ffe0b2",
    "reading":     "#ffd580",
    "movie":       "#e8f0fe",
    "sunset":      "#ff8c42",
    "dinner":      "#ffb347",
    "sleep":       "#ff5c5c",
    "cyberpunk":   "#d966ff",
    "synthwave":   "#aa44ff",
    "gaming":      "#4488ff",
    "ocean":       "#44ccff",
    "forest":      "#44cc88",
    "meditation":  "#9966ff",
}

MODE_TRANSITIONS = {
    "party": 0,
    "club": 0,
    "chill": 500,
    "lofi": 500,
    "edm": 0,
    "drop": 0,
    "edm_drop": 0,
    "bass_bounce": 0,
    "bounce": 0,
    "center_burst": 0,
    "burst": 0,
    "twinkle": 150,
    "movie": 800,
    "pulse": 200,
    "spectrum": 200,
    "flow": 200,
    "shockwave": 200,
    "mirror_eq": 200,
    "aurora": 200,
    "auto": 200,
}

EFFECT_COLORS = {
    # Creative Original Designs (L930 WRGBIC)
    "oil_slick":           "#06b6d4",
    "silk_ribbons":        "#ec4899",
    "nebula_bloom":        "#8b5cf6",
    "holographic_moire":   "#3b82f6",
    "bioluminescent_tide": "#0ea5e9",
    "ember_drift":         "#f97316",
    "cyberpunk":           "#d946ef",
    # Reworked L930 & L900 Effects
    "tide":             "#00c7be",
    "drift":            "#7c6ef5",
    "dusk":             "#c084fc",
    "breathe":          "#f59e0b",
    "starfield":        "#38bdf8",
    "embers":           "#ea580c",
    "lava_lamp":        "#ff4500",
    "golden_hour":      "#ffcc44",
    "hearth":           "#f97316",
    "comet":            "#af52de",
    "cyber_chase":      "#ec4899",
    "vaporwave_neon":   "#f43f5e",
    "sonar_sweep":      "#10b981",
    "neon_heartbeat":   "#e11d48",
    "lantern_sweep":    "#fbbf24",
    "aurora":           "#34c759",
    "deep_ocean":       "#0284c7",
    "sunrise":          "#f39c12",
    "sunset":           "#e67e22",
    "flicker":          "#f1c40f",
    "ocean":            "#00c7be",
    "raindrop":         "#00d2ff",
    "lightning":        "#5856d6",
    "police":           "#007aff",
    "candy_cane":       "#ff3b30",
    "haunted_mansion":  "#8b5cf6",
    "rainbow":          "#ff3b30",
    "ambient_drift":    "#aa88ff",
    "fireplace":        "#ff6622",
    "ocean_waves":      "#0088ff",
    "color_breath":     "#f59e0b",
    "candle_flicker":   "#ff9933",
}

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


from src.window_layout import responsive_window_geometry, responsive_grid_columns, tray_window_geometry


STARRED_EFFECTS_PATH = Path(__file__).resolve().parent.parent / "starred_effects.json"


def load_starred_effects() -> set[str]:
    """Loads user's starred/loved dynamic effects from disk."""
    try:
        if STARRED_EFFECTS_PATH.exists():
            with open(STARRED_EFFECTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
    except Exception:
        pass
    return {"planar_wind", "colored_bursts", "matrix_rain", "ambient_drift"}


def save_starred_effects(starred: set[str]):
    """Persists user's starred/loved dynamic effects to disk."""
    try:
        with open(STARRED_EFFECTS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(list(starred)), f, indent=2)
    except Exception:
        pass


def make_window_stay_in_taskbar(window):
    """Ensure the borderless window has a persistent taskbar entry and appears in Alt+Tab."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


class TapoGUI:
    """
    Modern glassmorphic desktop GUI matching reference screenshots exactly.
    100% responsive, fully scrollable, zero hidden buttons, with dynamic
    atmospheric themes for Ambient Drift, Northern Lights, Fireplace, Sakura,
    Golden Hour, and Deep Ocean.
    """

    def __init__(self, hub, on_quit, default_mode: str = "tray"):
        self.hub = hub
        self.on_quit = on_quit
        self.window_mode = default_mode  # "tray" (system tray app) or "normal" (popped out)
        self._saved_normal_geometry = None
        self._saved_tray_geometry = None
        
        self.dev_keys = list(hub.devices.keys())
        # Default to L930 device if present, ensuring all 50-zone addressable effects are visible
        l930_key = next((k for k, ctx in hub.devices.items() if getattr(ctx, "model", "") == "L930"), None)
        self.current_dev_id = l930_key or (self.dev_keys[0] if self.dev_keys else "all")
        self.current_theme_key = "ambient_drift"
        self.theme = THEMES[self.current_theme_key]

        self.app = ctk.CTk()
        self.app.title("Summer — Tray Quick Hub" if self.window_mode == "tray" else "Summer — Light Control Hub")
        self.app.resizable(True, True)
        self.app.overrideredirect(True)
        screen_w, screen_h = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
        if self.window_mode == "tray":
            _, _, _, _, min_w, min_h = tray_window_geometry(screen_w, screen_h)
        else:
            _, _, _, _, min_w, min_h = responsive_window_geometry(screen_w, screen_h)
        self.app.minsize(min_w, min_h)
        # Native Windows chrome provides standard minimize, maximize and resize controls.
        # The tray icon remains active independently while this window is hidden.
        self.app.configure(fg_color=self.theme["bg"])

        self.buttons = {}
        self.tab_buttons = {}
        self.vstyle_buttons = {}
        self.accent_buttons = {}
        self.accent_states = {
            "beat_flash": True,
            "hat_sparkle": True,
            "build_tension": True,
            "drop_bloom": True,
        }
        self.style_speed = 1.0
        self.style_intensity = 1.0
        self.style_palette_mode = "auto"
        self._click_test_active = False
        self._click_test_timer = None
        self.quick_level_buttons = {}
        self.card_frames = []
        self._responsive_grids = []
        self._resize_job = None
        self._sync_job = None
        self._last_synced_state = None
        self.active_picker = None
        self.local_ip = get_local_ip()
        self.starred_effects = load_starred_effects()
        self._fx_filter_mode = "all"  # "all", "starred", "1d", "2d"

        # Tap Sync calibration state
        self._tap_times = []
        self._tap_timer_id = None

        # Clean GUI state: canvas previews and meters removed per clutter reduction
        self.strip_canvas = None
        self.lbl_strip_tag = None
        self.lbl_strip_stats = None
        self.tray_strip_canvas = None
        self.spectrum_canvas = None
        self.opt_eq_layout = None
        self.audio_monitor_frame = None
        self.bar_meter_onset = None
        self.bar_meter_kick = None
        self.bar_meter_snare = None
        self.bar_meter_hat = None
        self.lbl_meter_onset = None
        self.lbl_meter_kick = None
        self.lbl_meter_snare = None
        self.lbl_meter_hat = None
        self.lbl_mon_meta = None
        self.lbl_lookahead_val = None
        self.lbl_measured_delay = None
        self.lbl_transition_val = None
        self.gui_lookahead_slider = None
        self.btn_click_test = None
        self.btn_tap_sync = None

        # Clean window controls (Escape or header Close button hides to tray)
        self.app.bind("<Escape>", lambda e: self.hide_window())
        # Closing the window hides it to the tray; Quit remains explicit in the tray menu.
        self.app.protocol("WM_DELETE_WINDOW", self.hide_window)

        self._build_ui()
        self.app.bind("<Configure>", self._on_window_configure, add="+")
        self.hub.subscribe(self._on_hub_update)
        self._setup_global_mousewheel()

    def _setup_global_mousewheel(self):
        """Enable silky-smooth, responsive mousewheel scrolling anywhere over child widgets."""
        def _on_mousewheel(event):
            try:
                canvas = None
                if getattr(self, "window_mode", "normal") == "tray" and hasattr(self, "tray_workspace"):
                    canvas = getattr(self.tray_workspace, "_parent_canvas", None)
                elif hasattr(self, "content_area"):
                    canvas = getattr(self.content_area, "_parent_canvas", None)

                if canvas and canvas.winfo_exists():
                    delta = -1 if event.delta > 0 else 1
                    canvas.yview_scroll(delta * 2, "units")
                    return "break"
            except Exception:
                pass

        self.app.bind_all("<MouseWheel>", _on_mousewheel, add="+")

    def _enable_drag(self, widget):
        def start(event):
            self._dx = event.x
            self._dy = event.y
        def drag(event):
            x = self.app.winfo_x() + (event.x - self._dx)
            y = self.app.winfo_y() + (event.y - self._dy)
            self.app.geometry(f"+{x}+{y}")
        widget.bind("<Button-1>", start, add="+")
        widget.bind("<B1-Motion>", drag, add="+")

    def _register_responsive_grid(self, grid, max_columns: int = 3):
        """Register a grid with a maximum column count for narrow windows."""
        try:
            grid._responsive_max_columns = max(1, min(3, int(max_columns)))
        except (TypeError, ValueError):
            grid._responsive_max_columns = 3
        if grid not in self._responsive_grids:
            self._responsive_grids.append(grid)

    def _on_window_configure(self, event=None):
        """Debounce resize events so reflow does not compete with Tk drawing."""
        if event is not None and getattr(event, "widget", None) is not self.app:
            return
        if self._resize_job is not None:
            try:
                self.app.after_cancel(self._resize_job)
            except Exception:
                pass
        try:
            self._resize_job = self.app.after(90, self._reflow_responsive_grids)
        except Exception:
            self._resize_job = None

    def _reflow_responsive_grids(self):
        self._resize_job = None
        for grid in list(self._responsive_grids):
            try:
                if not grid.winfo_exists():
                    self._responsive_grids.remove(grid)
                    continue
                width = max(1, grid.winfo_width())
                columns = responsive_grid_columns(
                    width, max_columns=getattr(grid, "_responsive_max_columns", 3)
                )
                for col in range(3):
                    grid.columnconfigure(
                        col, weight=1 if col < columns else 0, minsize=0,
                        uniform=f"responsive_{id(grid)}" if col < columns else ""
                    )
                children = [child for child in grid.winfo_children() if str(child.winfo_manager()) == "grid"]
                for index, child in enumerate(children):
                    child.grid_configure(row=index // columns, column=index % columns, sticky="nsew")
            except Exception:
                continue

        # Collapse the rail and shorten target labels before controls get cramped.
        try:
            window_width = self.app.winfo_width()
            compact = window_width < 980
            if compact != getattr(self, "_nav_compact", False):
                self._nav_compact = compact
                self.nav_rail.configure(width=68 if compact else 194)
                self.nav_eyebrow.configure(text="GO" if compact else "WORKSPACE", anchor="center" if compact else "w")
                self.nav_device_note.configure(
                    text=f"{len(self.hub.devices)}" if compact else f"{len(self.hub.devices)} device(s) configured\nLAN controls active",
                    anchor="center" if compact else "w", wraplength=42 if compact else 156
                )
                for page, button in self.nav_buttons.items():
                    glyph, label = self._nav_items[page]
                    button.configure(text=glyph if compact else f"{glyph}   {label}", anchor="center" if compact else "w")

            compact_targets = window_width < 760
            if compact_targets != getattr(self, "_targets_compact", False):
                self._targets_compact = compact_targets
                self.target_label.configure(text="TARGET" if compact_targets else "CONTROL TARGET")
                for dev_id, button in self.tab_buttons.items():
                    button.configure(
                        text=self._device_tab_short_labels[dev_id] if compact_targets else self._device_tab_labels[dev_id],
                        font=ctk.CTkFont(size=11 if compact_targets else 12, weight="bold"),
                    )
        except Exception:
            pass

    def _build_ui(self):
        """Build the redesigned desktop workspace with clear, separate pages."""
        t = self.theme
        sw, sh = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
        if self.window_mode == "tray":
            width, height, x, y, min_w, min_h = tray_window_geometry(sw, sh)
            self._saved_tray_geometry = f"{width}x{height}+{x}+{y}"
        else:
            width, height, x, y, min_w, min_h = responsive_window_geometry(sw, sh)
            self._saved_normal_geometry = f"{width}x{height}+{x}+{y}"
        self.app.minsize(min_w, min_h)
        self.app.geometry(f"{width}x{height}+{x}+{y}")
        self._has_positioned = True
        self.app.configure(fg_color=t["bg"])
        make_window_stay_in_taskbar(self.app)

        self.buttons = {}
        self.tab_buttons = {}
        self.vstyle_buttons = {}
        self.accent_buttons = {}
        self.quick_level_buttons = {}
        self.card_frames = []
        self._responsive_grids = []
        self._resize_job = None

        self.root_frame = ctk.CTkFrame(self.app, fg_color=t["bg"], corner_radius=0)
        self.root_frame.pack(fill="both", expand=True)

        # Top bar: restrained brand block with responsive actions
        is_tray = (self.window_mode == "tray")
        self.header = ctk.CTkFrame(self.root_frame, fg_color=t["bg"], corner_radius=0, height=70 if is_tray else 78)
        self.header.pack(fill="x", padx=12 if is_tray else 22, pady=(10, 8) if is_tray else (14, 10))
        self.header.grid_columnconfigure(1, weight=1)

        logo = ctk.CTkFrame(
            self.header, width=38 if is_tray else 44, height=38 if is_tray else 44, corner_radius=10,
            fg_color=t["surface_raised"], border_width=1, border_color=t["border"]
        )
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 10 if is_tray else 12), sticky="w")
        logo.grid_propagate(False)
        self.header_icon_lbl = ctk.CTkLabel(
            logo, text="✦", font=ctk.CTkFont(size=18 if is_tray else 22, weight="bold"),
            text_color=t["accent_glow"]
        )
        self.header_icon_lbl.place(relx=0.5, rely=0.5, anchor="center")

        self.header_title = ctk.CTkLabel(
            self.header,
            text="Summer · Quick Hub" if is_tray else "Summer  /  Light Control",
            font=ctk.CTkFont(size=15 if is_tray else 20, weight="bold"),
            text_color=t["text_primary"],
            anchor="w"
        )
        self.header_title.grid(row=0, column=1, sticky="w")
        status_line = ctk.CTkFrame(self.header, fg_color="transparent")
        status_line.grid(row=1, column=1, sticky="w", pady=(1, 0) if is_tray else (2, 0))
        self.header_status_dot = ctk.CTkLabel(
            status_line, text="●", font=ctk.CTkFont(size=9 if is_tray else 10), text_color="#35d399"
        )
        self.header_status_dot.pack(side="left", padx=(0, 5))
        self.header_status_lbl = ctk.CTkLabel(
            status_line, text="Local control  ·  Ready",
            font=ctk.CTkFont(size=11 if is_tray else 12), text_color=t["text_secondary"]
        )
        self.header_status_lbl.pack(side="left")

        actions = ctk.CTkFrame(self.header, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self.btn_top_power = ctk.CTkButton(
            actions,
            text="⏻" if is_tray else "⏻  Power",
            width=34 if is_tray else 88,
            height=34 if is_tray else 36,
            corner_radius=8,
            fg_color=t["accent_soft"], hover_color=t["accent"],
            border_width=1, border_color=t["accent"], text_color=t["text_primary"],
            font=ctk.CTkFont(size=13 if is_tray else 12, weight="bold"),
            command=self._handle_power_click
        )
        self.btn_top_power.pack(side="left", padx=(0, 4 if is_tray else 6))
        self.btn_mode_toggle = ctk.CTkButton(
            actions,
            text="⤢ Pop Out" if is_tray else "⤡ Mini Tray",
            width=82 if is_tray else 94,
            height=34 if is_tray else 36,
            corner_radius=8,
            fg_color=t["surface_raised"], hover_color=t["surface_high"],
            border_width=1, border_color=t["accent"], text_color=t["accent_glow"],
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.toggle_window_mode
        )
        self.btn_mode_toggle.pack(side="left", padx=(0, 4 if is_tray else 6))
        self.btn_hide = ctk.CTkButton(
            actions, text="✕",
            width=34 if is_tray else 36,
            height=34 if is_tray else 36,
            corner_radius=8,
            fg_color=t["surface_raised"], hover_color=t["surface_high"],
            border_width=1, border_color=t["border"], text_color=t["text_secondary"],
            font=ctk.CTkFont(size=13, weight="bold"), command=self.hide_window
        )
        self.btn_hide.pack(side="left")

        # Smooth header dragging across entire title area
        self._enable_drag(self.header)
        self._enable_drag(logo)
        self._enable_drag(self.header_icon_lbl)
        self._enable_drag(self.header_title)
        self._enable_drag(status_line)
        self._enable_drag(self.header_status_dot)
        self._enable_drag(self.header_status_lbl)

        # Workspace is split into a stable navigation rail and a page viewport.
        self.workspace = ctk.CTkFrame(self.root_frame, fg_color="transparent")
        self.workspace.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self.nav_rail = ctk.CTkFrame(
            self.workspace, width=194, fg_color=t["surface"],
            corner_radius=10, border_width=1, border_color=t["border"]
        )
        # Hidden for the single-page mixer layout; legacy callbacks remain compatible.
        self.nav_rail.pack_forget()
        self.nav_rail.pack_propagate(False)
        self.nav_eyebrow = ctk.CTkLabel(
            self.nav_rail, text="WORKSPACE", anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=t["text_muted"]
        )
        self.nav_eyebrow.pack(fill="x", padx=16, pady=(20, 12))

        self.nav_buttons = {}
        self._nav_items = {
            "overview": ("⌂", "Overview"),
            "music": ("♫", "Music reactive"),
            "effects": ("✦", "Effects"),
            "diagnostics": ("⌁", "Diagnostics"),
        }
        for page_key, (glyph, label) in self._nav_items.items():
            button = ctk.CTkButton(
                self.nav_rail, text=f"{glyph}   {label}", height=42,
                fg_color=t["accent_soft"] if page_key == "overview" else "transparent",
                hover_color=t["surface_high"], text_color=t["text_primary"] if page_key == "overview" else t["text_secondary"],
                border_width=1 if page_key == "overview" else 0,
                border_color=t["accent"] if page_key == "overview" else t["border"],
                corner_radius=8, anchor="w", font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda p=page_key: self._switch_page(p)
            )
            button.pack(fill="x", padx=8, pady=3)
            self.nav_buttons[page_key] = button

        spacer = ctk.CTkFrame(self.nav_rail, fg_color="transparent", height=12)
        spacer.pack(fill="x", expand=True)
        ctk.CTkFrame(self.nav_rail, height=1, fg_color=t["border"]).pack(fill="x", padx=14, pady=(4, 12))
        ctk.CTkLabel(
            self.nav_rail, text="LOCAL FIRST", anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=t["accent_glow"]
        ).pack(fill="x", padx=16, pady=(0, 4))
        self.nav_device_note = ctk.CTkLabel(
            self.nav_rail,
            text=f"{len(self.hub.devices)} device(s) configured\nLAN controls active",
            justify="left", anchor="w", wraplength=156,
            font=ctk.CTkFont(size=11), text_color=t["text_muted"]
        )
        self.nav_device_note.pack(fill="x", padx=16, pady=(0, 18))

        self.main_column = ctk.CTkFrame(self.workspace, fg_color="transparent")
        self.main_column.pack(fill="both", expand=True)

        # The device selector stays visible while navigating between pages.
        self.tabs_bar = ctk.CTkFrame(
            self.main_column, fg_color=t["surface"], corner_radius=8,
            border_width=1, border_color=t["border"]
        )
        self.tabs_bar.pack(fill="x", pady=(0, 10))
        tabs_inner = ctk.CTkFrame(self.tabs_bar, fg_color="transparent")
        tabs_inner.pack(fill="x", padx=10, pady=8)
        self.target_label = ctk.CTkLabel(
            tabs_inner, text="CONTROL TARGET", font=ctk.CTkFont(size=10, weight="bold"),
            text_color=t["text_muted"]
        )
        self.target_label.pack(side="left", padx=(4, 12))
        self.target_buttons = ctk.CTkFrame(tabs_inner, fg_color="transparent")
        self.target_buttons.pack(side="left", fill="x", expand=True)
        target_items = []
        for dev_id, ctx in self.hub.devices.items():
            model = getattr(ctx, "model", "")
            label = f"{ctx.name}  ·  {model}" if model else ctx.name
            target_items.append((dev_id, label))
        target_items.append(("all", "Both strips"))
        self._device_tab_labels = {dev_id: title_text for dev_id, title_text in target_items}
        self._device_tab_short_labels = {}
        used_short_labels = set()
        for index, (dev_id, title_text) in enumerate(target_items):
            if dev_id == "all":
                short_label = "Both"
            else:
                device_ctx = self.hub.devices.get(dev_id)
                short_label = str(getattr(device_ctx, "model", "") or "").strip().upper()
                if not short_label:
                    short_label = f"Strip {index + 1}"
            if short_label in used_short_labels:
                short_label = f"{short_label} {index + 1}"
            used_short_labels.add(short_label)
            self._device_tab_short_labels[dev_id] = short_label

            selected = dev_id == self.current_dev_id
            btn = ctk.CTkButton(
                self.target_buttons, text=title_text, height=34,
                fg_color=t["accent_soft"] if selected else "transparent",
                hover_color=t["surface_high"],
                text_color=t["text_primary"] if selected else t["text_secondary"],
                border_width=1 if selected else 0,
                border_color=t["accent"] if selected else t["border"],
                font=ctk.CTkFont(size=12, weight="bold"), corner_radius=7,
                command=lambda d=dev_id: self._select_device_tab(d)
            )
            btn.pack(side="left", fill="x", expand=True, padx=3)
            self.tab_buttons[dev_id] = btn

        # Navigation Segment Bar (Overview, Music, Effects)
        self.nav_tabs_bar = ctk.CTkFrame(
            self.main_column, fg_color=t["surface"], corner_radius=8,
            border_width=1, border_color=t["border"]
        )
        self.nav_tabs_bar.pack(fill="x", pady=(0, 10))
        nav_inner = ctk.CTkFrame(self.nav_tabs_bar, fg_color="transparent")
        nav_inner.pack(fill="x", padx=6, pady=6)
        nav_inner.columnconfigure((0, 1, 2), weight=1)

        self.nav_tab_buttons = {}
        for idx, (page_key, glyph, label) in enumerate([
            ("overview", "⌂", "Overview & Scenes"),
            ("music", "♫", "Music Reactive"),
            ("effects", "✦", "Dynamic Effects"),
        ]):
            is_active = (page_key == "overview")
            btn = ctk.CTkButton(
                nav_inner, text=f"{glyph}  {label}", height=36,
                fg_color=t["accent"] if is_active else "transparent",
                hover_color=t["surface_high"],
                text_color="#ffffff" if is_active else t["text_secondary"],
                font=ctk.CTkFont(size=12, weight="bold"), corner_radius=7,
                command=lambda p=page_key: self._switch_page(p)
            )
            btn.grid(row=0, column=idx, sticky="ew", padx=3)
            self.nav_tab_buttons[page_key] = btn

        scroll_kwargs = {
            "fg_color": "transparent",
            "scrollbar_button_color": t["surface_high"],
            "scrollbar_button_hover_color": t["accent"],
            "corner_radius": 0,
        }
        # One shared viewport; all controls remain on the same page.
        self.content_area = ctk.CTkScrollableFrame(self.main_column, **scroll_kwargs)
        self.content_area.pack(fill="both", expand=True)
        self.page_views = {
            key: ctk.CTkFrame(self.content_area, fg_color="transparent")
            for key in ("overview", "music", "effects", "diagnostics")
        }
        for page in self.page_views.values():
            page.pack(fill="x", expand=False, padx=0, pady=0)

        def page_heading(page, eyebrow, title, description):
            heading = ctk.CTkFrame(page, fg_color="transparent")
            heading.pack(fill="x", padx=4, pady=(12, 16))
            ctk.CTkLabel(
                heading, text=eyebrow.upper(), anchor="w",
                font=ctk.CTkFont(size=10, weight="bold"), text_color=t["accent_glow"]
            ).pack(fill="x", pady=(0, 5))
            ctk.CTkLabel(
                heading, text=title, anchor="w",
                font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text_primary"]
            ).pack(fill="x")
            ctk.CTkLabel(
                heading, text=description, anchor="w", wraplength=1000,
                font=ctk.CTkFont(size=11), text_color=t["text_secondary"]
            ).pack(fill="x", pady=(4, 0))

        def make_card(parent, background=None, hero=False):
            frame = ctk.CTkFrame(
                parent, fg_color=background or t["surface"], corner_radius=9,
                border_width=1, border_color=t["hero_border"] if hero else t["border"]
            )
            frame.pack(fill="x", padx=2, pady=(0, 12))
            self.card_frames.append(frame)
            return frame

        def card_heading(parent, title, subtitle=None):
            top = ctk.CTkFrame(parent, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 8))
            ctk.CTkLabel(
                top, text=title, anchor="w",
                font=ctk.CTkFont(size=15, weight="bold"), text_color=t["text_primary"]
            ).pack(fill="x")
            if subtitle:
                ctk.CTkLabel(
                    top, text=subtitle, anchor="w", wraplength=1000,
                    font=ctk.CTkFont(size=12), text_color=t["text_muted"]
                ).pack(fill="x", pady=(3, 0))
            return top

        # ── OVERVIEW ────────────────────────────────────────────────────────
        overview = self.page_views["overview"]
        page_heading(
            overview, "At a glance", "Your lights, under control",
            "Choose a strip, set the room brightness, or jump into a saved scene."
        )

        self.hero_card = make_card(overview, background=t["hero_tint"], hero=True)
        hero_top = ctk.CTkFrame(self.hero_card, fg_color="transparent")
        hero_top.pack(fill="x", padx=20, pady=18)
        hero_top.grid_columnconfigure(0, weight=1)
        tag_row = ctk.CTkFrame(hero_top, fg_color="transparent")
        tag_row.grid(row=0, column=0, sticky="w", pady=(0, 7))
        self.hero_tag = ctk.CTkLabel(
            tag_row, text="L930", fg_color=t["surface_raised"], corner_radius=5,
            padx=9, pady=4, font=ctk.CTkFont(size=10, weight="bold"),
            text_color=t["accent_glow"]
        )
        self.hero_tag.pack(side="left")
        self.hero_title = ctk.CTkLabel(
            hero_top, text="Light strip", anchor="w",
            font=ctk.CTkFont(size=24, weight="bold"), text_color=t["text_primary"]
        )
        self.hero_title.grid(row=1, column=0, sticky="w")
        status_row = ctk.CTkFrame(hero_top, fg_color="transparent")
        status_row.grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.hero_status_dot = ctk.CTkLabel(
            status_row, text="●", font=ctk.CTkFont(size=11), text_color="#35d399"
        )
        self.hero_status_dot.pack(side="left", padx=(0, 6))
        self.hero_status_lbl = ctk.CTkLabel(
            status_row, text="Active", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t["text_secondary"]
        )
        self.hero_status_lbl.pack(side="left")
        self.btn_hero_power = ctk.CTkButton(
            hero_top, text="⏻", width=52, height=52, corner_radius=9,
            fg_color=t["accent_soft"], hover_color=t["accent"],
            border_width=1, border_color=t["accent"],
            font=ctk.CTkFont(size=23, weight="bold"), text_color=t["text_primary"],
            command=self._handle_power_click
        )
        self.btn_hero_power.grid(row=0, column=1, rowspan=3, sticky="e", padx=(16, 0))

        self.bright_card = make_card(overview)
        brightness_header = ctk.CTkFrame(self.bright_card, fg_color="transparent")
        brightness_header.pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(
            brightness_header, text="Brightness", anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=t["text_primary"]
        ).pack(side="left")
        self.bright_val_label = ctk.CTkLabel(
            brightness_header, text="50%", font=ctk.CTkFont(size=16, weight="bold"),
            text_color=t["accent_glow"]
        )
        self.bright_val_label.pack(side="right")
        brightness_slider_row = ctk.CTkFrame(self.bright_card, fg_color="transparent")
        brightness_slider_row.pack(fill="x", padx=18, pady=(0, 12))
        self.lbl_sun_dim = ctk.CTkLabel(
            brightness_slider_row, text="DIM", font=ctk.CTkFont(size=10, weight="bold"),
            text_color=t["text_muted"]
        )
        self.lbl_sun_dim.pack(side="left", padx=(0, 10))
        self.bright_slider = ctk.CTkSlider(
            brightness_slider_row, from_=1, to=100, height=18,
            progress_color=t["accent"], button_color=t["accent_glow"],
            button_hover_color=t["accent"], fg_color=t["surface_high"],
            command=self._on_brightness_slide
        )
        self.bright_slider.set(50)
        self.bright_slider.pack(side="left", fill="x", expand=True)
        self.lbl_sun_bright = ctk.CTkLabel(
            brightness_slider_row, text="BRIGHT", font=ctk.CTkFont(size=10, weight="bold"),
            text_color=t["text_muted"]
        )
        self.lbl_sun_bright.pack(side="left", padx=(10, 0))
        levels_row = ctk.CTkFrame(self.bright_card, fg_color="transparent")
        levels_row.pack(fill="x", padx=18, pady=(0, 16))
        for idx, level in enumerate((15, 40, 70, 100)):
            button = ctk.CTkButton(
                levels_row, text=f"{level}%", height=32, corner_radius=7,
                fg_color=t["surface_raised"], hover_color=t["surface_high"],
                text_color=t["text_secondary"], border_width=1, border_color=t["border"],
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda v=level: self._set_quick_brightness(v)
            )
            button.pack(side="left", fill="x", expand=True, padx=(0 if idx == 0 else 6, 0))
            self.quick_level_buttons[level] = button

        self.preset_card = make_card(overview)
        card_heading(self.preset_card, "Saved scenes", "One click applies a static scene to the selected strip.")
        presets_grid = ctk.CTkFrame(self.preset_card, fg_color="transparent")
        presets_grid.pack(fill="x", padx=14, pady=(0, 16))
        self._register_responsive_grid(presets_grid)
        for col in range(3):
            presets_grid.columnconfigure(col, weight=1, uniform="scenes")
        modes_list = list(self.hub.config.get("modes", {}).keys()) or [
            "work", "deep_focus", "coding_night", "reading", "sunset", "dinner", "movie", "sleep"
        ]
        for idx, name in enumerate(modes_list):
            row, col = divmod(idx, 3)
            label = name.replace("_", " ").title()
            button = self._make_item_button(
                presets_grid, label, MODE_COLORS.get(name, t["accent"]),
                lambda n=name: self._apply_mode(n)
            )
            button.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            self.buttons[f"mode_{name}"] = button

        self.btn_picker = ctk.CTkButton(
            overview, text="＋   Open colour studio", height=44, corner_radius=8,
            fg_color=t["surface_raised"], hover_color=t["surface_high"],
            border_width=1, border_color=t["border"], text_color=t["text_primary"],
            font=ctk.CTkFont(size=13, weight="bold"), command=self._show_picker
        )
        self.btn_picker.pack(fill="x", padx=2, pady=(0, 16))

        # ── MUSIC REACTIVE ──────────────────────────────────────────────────
        music = self.page_views["music"]
        page_heading(
            music, "Live performance", "Make the lights listen",
            "Audio and screen analysis, reactive looks, sensitivity and timing controls."
        )

        self.sync_card = make_card(music)
        card_heading(self.sync_card, "Live inputs", "Choose one reactive source at a time, or switch between them as needed.")
        sync_body = ctk.CTkFrame(self.sync_card, fg_color="transparent")
        sync_body.pack(fill="x", padx=16, pady=(0, 16))
        self._register_responsive_grid(sync_body, max_columns=2)
        sync_body.grid_columnconfigure((0, 1), weight=1, uniform="sync")
        self.btn_music = ctk.CTkButton(
            sync_body, text="♫  AUDIO REACTIVE\nFollow bass, mids, highs and rhythm",
            height=64, corner_radius=8, fg_color=t["surface_raised"],
            hover_color=t["surface_high"], border_width=1, border_color=t["border"],
            text_color=t["text_primary"], font=ctk.CTkFont(size=13, weight="bold"),
            command=self._handle_music_toggle
        )
        self.btn_music.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 12))
        self.btn_scr = ctk.CTkButton(
            sync_body, text="▣  SCREEN SYNC\nTrack the dominant colours on screen",
            height=64, corner_radius=8, fg_color=t["surface_raised"],
            hover_color=t["surface_high"], border_width=1, border_color=t["border"],
            text_color=t["text_primary"], font=ctk.CTkFont(size=13, weight="bold"),
            command=self._handle_screen_toggle
        )
        self.btn_scr.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 12))

        source_row = ctk.CTkFrame(sync_body, fg_color="transparent")
        source_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        source_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            source_row, text="Audio input", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_secondary"]
        ).grid(row=0, column=0, padx=(0, 14), sticky="w")
        audio_devices = self.hub.get_audio_devices()
        audio_names = [d["name"] for d in audio_devices] or ["Auto-Detect Active Audio"]
        current_audio = self.hub.audio_device
        self.audio_opt = ctk.CTkOptionMenu(
            source_row, values=audio_names, command=self._on_audio_device_selected,
            fg_color=t["surface_raised"], button_color=t["surface_high"],
            dropdown_fg_color=t["surface_raised"], text_color=t["text_primary"],
            height=34, corner_radius=7, font=ctk.CTkFont(size=12)
        )
        if current_audio in audio_names:
            self.audio_opt.set(current_audio)
        self.audio_opt.grid(row=0, column=1, sticky="ew")

        self.btn_audio_retry = ctk.CTkButton(
            sync_body, text="↻  Restart audio capture", height=34, width=190,
            corner_radius=7, fg_color=t["surface_raised"], hover_color=t["surface_high"],
            border_width=1, border_color=t["border"], text_color=t["text_secondary"],
            font=ctk.CTkFont(size=12, weight="bold"), command=self._handle_audio_retry
        )
        self.btn_audio_retry.grid(row=2, column=1, sticky="e", pady=(8, 0))

        self.vstyles_frame = ctk.CTkFrame(
            music, fg_color=t["surface"], corner_radius=9,
            border_width=1, border_color=t["border"]
        )
        self.vstyles_frame.pack(fill="x", padx=2, pady=(0, 12))
        vstyles_inner = ctk.CTkFrame(self.vstyles_frame, fg_color="transparent")
        vstyles_inner.pack(fill="x", padx=16, pady=16)
        vstyles_header = ctk.CTkFrame(vstyles_inner, fg_color="transparent")
        vstyles_header.pack(fill="x", pady=(0, 12))
        header_left = ctk.CTkFrame(vstyles_header, fg_color="transparent")
        header_left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            header_left, text="Visual style", anchor="w",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=t["text_primary"]
        ).pack(fill="x")
        ctk.CTkLabel(
            header_left, text="Pick the way the strip responds to the track.",
            anchor="w", font=ctk.CTkFont(size=12), text_color=t["text_muted"]
        ).pack(fill="x", pady=(3, 0))
        self.gui_section_badge = ctk.CTkLabel(
            vstyles_header, text="READY", corner_radius=6,
            fg_color=t["surface_high"], text_color=t["text_muted"],
            padx=9, pady=5, font=ctk.CTkFont(size=11, weight="bold")
        )
        self.gui_section_badge.pack(side="right", padx=(10, 0))
        self.gui_key_pill = ctk.CTkLabel(
            vstyles_header, text="Key —", corner_radius=6,
            fg_color=t["surface_high"], text_color=t["text_secondary"],
            padx=9, pady=5, font=ctk.CTkFont(size=11, weight="bold")
        )
        self.gui_key_pill.pack(side="right", padx=(0, 8))
        self.gui_bpm_lbl = ctk.CTkLabel(
            vstyles_inner, text="Ready · Select a visual style or enable Audio Reactive below", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]
        )
        self.gui_bpm_lbl.pack(fill="x", pady=(0, 10))

        self.btn_auto_mode = ctk.CTkButton(
            vstyles_inner, text="✦   Auto Director   ·   Let the music choose",
            height=44, corner_radius=8, fg_color=t["accent"],
            hover_color=t["accent_soft"], text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._set_visual_style("auto")
        )
        self.btn_auto_mode.pack(fill="x", pady=(0, 10))
        self.vstyle_buttons["auto"] = self.btn_auto_mode

        styles_grid = ctk.CTkFrame(vstyles_inner, fg_color="transparent")
        styles_grid.pack(fill="x", pady=(0, 12))
        self._register_responsive_grid(styles_grid)
        for col in range(3):
            styles_grid.columnconfigure(col, weight=1, uniform="visual-styles")
        style_items = [
            ("pulse", "ϟ  Pulse", "Kick ripple transients"),
            ("spectrum", "▥  Spectrum", "50-band frequency EQ"),
            ("flow", "≈  Flow", "Harmonic color waves"),
            ("edm", "⚡  EDM Drop", "Drop bloom & riser tension"),
            ("chill", "◌  Chill", "Soft ambient breathing"),
            ("party", "✹  Party", "High energy chromatic frenzy"),
            ("neon_drive", "🚘  Neon Drive", "Synthwave 80s neon grid"),
            ("sub_blast", "💥  Sub Blast", "Kinetic bass cannon"),
            ("vocal_glow", "🎤  Vocal Glow", "Human voice & dialogue aura"),
            ("liquid_groove", "💧  Liquid Groove", "Fluid viscous bass waves"),
            ("reactive_aurora", "🌌  Aurora", "Northern lights curtain"),
            ("twinkle", "✧  Twinkle", "Treble & hi-hat sparkle"),
            ("bass_bounce", "↔  Bounce", "Sub-bass elastic bounce"),
            ("center_burst", "✺  Center Burst", "Center-to-edge wave"),
            ("segmented_vu", "📊  Segmented VU", "Staccato noise meter columns"),
            ("bpm_resonator", "🥁  BPM Resonator", "Tempo-locked rocktaves"),
            ("acoustic_string", "🎸  Acoustic String", "Physical string resonance"),
            ("hydro_acoustic", "🌊  Hydro Acoustic", "Waterfall acoustic pressure"),
            ("melodic_contour", "🎵  Melodic Contour", "Pitch-tracking melodic line"),
            ("lofi_vinyl", "📻  Lo-Fi Vinyl", "Warm vintage flutter"),
            ("chain_reaction", "⛓  Chain Reaction", "Stochastic lightning cascade"),
            ("movie", "▣  Movie Sync", "Screen color + vocal aura"),
        ]
        for index, (style_id, title, description) in enumerate(style_items):
            row, col = divmod(index, 3)
            style_button = ctk.CTkButton(
                styles_grid, text=f"{title}\n{description}", anchor="w",
                height=62, corner_radius=7, fg_color=t["surface_high"],
                hover_color=t["accent_soft"], border_width=0,
                text_color=t["text_secondary"], font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda name=style_id: self._set_visual_style(name)
            )
            style_button.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            self.vstyle_buttons[style_id] = style_button

        tuning_card = make_card(music)
        card_heading(tuning_card, "Response tuning", "Adjust how strongly the signal moves the lights and how bright effects can get.")
        tuning_inner = ctk.CTkFrame(tuning_card, fg_color="transparent")
        tuning_inner.pack(fill="x", padx=18, pady=(0, 16))
        self._register_responsive_grid(tuning_inner, max_columns=2)
        tuning_inner.grid_columnconfigure((0, 1), weight=1, uniform="tuning")
        sensitivity_box = ctk.CTkFrame(tuning_inner, fg_color="transparent")
        sensitivity_box.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(0, 12))
        sensitivity_header = ctk.CTkFrame(sensitivity_box, fg_color="transparent")
        sensitivity_header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            sensitivity_header, text="Sensitivity", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t["text_secondary"]
        ).pack(side="left")
        self.lbl_sens_val = ctk.CTkLabel(
            sensitivity_header, text="1.0×", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t["accent_glow"]
        )
        self.lbl_sens_val.pack(side="right")
        self.gui_sens_slider = ctk.CTkSlider(
            sensitivity_box, from_=0.2, to=3.0, number_of_steps=28, height=16,
            command=self._on_audio_sensitivity_change, fg_color=t["surface_high"],
            progress_color=t["accent"], button_color=t["accent_glow"], button_hover_color=t["accent"]
        )
        self.gui_sens_slider.set(1.0)
        self.gui_sens_slider.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            sensitivity_box, text="Lower = subtle  ·  Higher = more reactive",
            font=ctk.CTkFont(size=11), text_color=t["text_muted"]
        ).pack(anchor="w")

        cap_box = ctk.CTkFrame(tuning_inner, fg_color="transparent")
        cap_box.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 12))
        cap_header = ctk.CTkFrame(cap_box, fg_color="transparent")
        cap_header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            cap_header, text="Brightness cap", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t["text_secondary"]
        ).pack(side="left")
        self.lbl_bright_cap_val = ctk.CTkLabel(
            cap_header, text="100%", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t["accent_glow"]
        )
        self.lbl_bright_cap_val.pack(side="right")
        self.slider_bright_cap = ctk.CTkSlider(
            cap_box, from_=30, to=100, number_of_steps=70, height=16,
            command=self._on_bright_cap_slide, fg_color=t["surface_high"],
            progress_color=t["accent"], button_color=t["accent_glow"], button_hover_color=t["accent"]
        )
        self.slider_bright_cap.set(100)
        self.slider_bright_cap.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            cap_box, text="A ceiling for audio-reactive brightness",
            font=ctk.CTkFont(size=11), text_color=t["text_muted"]
        ).pack(anchor="w")

        palette_row = ctk.CTkFrame(tuning_inner, fg_color="transparent")
        palette_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(
            palette_row, text="Palette source", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t["text_secondary"]
        ).pack(side="left")
        self.palette_mode_opt = ctk.CTkOptionMenu(
            palette_row, values=["Auto (Key/Chroma)", "Album Art (Windows Media)", "Fixed (Current)"],
            command=self._on_palette_mode_selected, fg_color=t["surface_raised"],
            button_color=t["surface_high"], text_color=t["text_primary"],
            height=34, corner_radius=7, font=ctk.CTkFont(size=12)
        )
        self.palette_mode_opt.set("Auto (Key/Chroma)")
        self.palette_mode_opt.pack(side="right")

        accents_row = ctk.CTkFrame(tuning_inner, fg_color="transparent")
        accents_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        accent_names = [
            ("beat_flash", "Beat accents"),
            ("hat_sparkle", "Hi-hat sparkle"),
            ("build_tension", "Build tension"),
            ("drop_bloom", "Drop bloom"),
        ]
        self.accent_states = getattr(self, "accent_states", {
            "beat_flash": True, "hat_sparkle": True, "build_tension": True, "drop_bloom": True
        })
        for index, (accent_id, label) in enumerate(accent_names):
            accent_button = ctk.CTkButton(
                accents_row, text=label, height=32, corner_radius=7,
                fg_color=t["accent_soft"], hover_color=t["surface_high"],
                border_width=0, text_color=t["text_primary"],
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda name=accent_id: self._toggle_accent(name)
            )
            accent_button.pack(side="left", fill="x", expand=True, padx=(0 if index == 0 else 6, 0))
            self.accent_buttons[accent_id] = accent_button

        # ── EFFECTS ─────────────────────────────────────────────────────────
        effects = self.page_views["effects"]
        page_heading(
            effects, "Atmosphere library", "Give the room a different texture",
            "Original animated fields for the L930 and gentle ambient looks for the L900."
        )
        self.fx_card = make_card(effects)
        self.fx_header_label = ctk.CTkLabel(
            self.fx_card, text="EFFECTS", anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=t["text_primary"]
        )
        self.fx_header_label.pack(fill="x", padx=18, pady=(16, 4))
        self.fx_grid_frame = ctk.CTkFrame(self.fx_card, fg_color="transparent")
        self.fx_grid_frame.pack(fill="x", padx=12, pady=(8, 16))
        self._render_effects_list()

        # ── DIAGNOSTICS ─────────────────────────────────────────────────────
        diagnostics = self.page_views["diagnostics"]
        page_heading(
            diagnostics, "System health", "Performance & connection",
            "Watch network timing and frame delivery without crowding the lighting controls."
        )
        self.diag_card = make_card(diagnostics)
        diag_top = ctk.CTkFrame(self.diag_card, fg_color="transparent")
        diag_top.pack(fill="x", padx=18, pady=(18, 12))
        ctk.CTkLabel(
            diag_top, text="Transport telemetry", font=ctk.CTkFont(size=16, weight="bold"),
            text_color=t["text_primary"]
        ).pack(side="left")
        self.gui_diag_status = ctk.CTkLabel(
            diag_top, text="● Connecting", font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        )
        self.gui_diag_status.pack(side="right")

        metrics_row = ctk.CTkFrame(self.diag_card, fg_color="transparent")
        metrics_row.pack(fill="x", padx=14, pady=(0, 16))
        self._register_responsive_grid(metrics_row, max_columns=3)
        metrics_row.grid_columnconfigure((0, 1, 2), weight=1, uniform="metrics")
        metric_specs = [
            ("send", "SEND RATE", "--", "#34d399"),
            ("rtt", "ROUND-TRIP", "-- ms", t["accent_glow"]),
            ("drop", "FRAME DROPS", "--%", "#fbbf24"),
        ]
        for index, (key, label, initial, color) in enumerate(metric_specs):
            metric = ctk.CTkFrame(
                metrics_row, fg_color=t["surface_raised"], corner_radius=8,
                border_width=1, border_color=t["border"]
            )
            metric.grid(row=0, column=index, sticky="nsew", padx=4)
            ctk.CTkLabel(
                metric, text=label, font=ctk.CTkFont(size=10, weight="bold"),
                text_color=t["text_muted"]
            ).pack(anchor="w", padx=14, pady=(14, 5))
            value = ctk.CTkLabel(
                metric, text=initial, font=ctk.CTkFont(size=24, weight="bold"),
                text_color=color
            )
            value.pack(anchor="w", padx=14)
            if key == "send":
                self.gui_fps_val = value
                self.gui_render_val = ctk.CTkLabel(
                    metric, text="Render: — calc", font=ctk.CTkFont(size=11),
                    text_color=t["text_secondary"]
                )
                self.gui_render_val.pack(anchor="w", padx=14, pady=(4, 14))
            elif key == "rtt":
                self.gui_rtt_val = value
                self.gui_pacing_val = ctk.CTkLabel(
                    metric, text="Total: — ms", font=ctk.CTkFont(size=11),
                    text_color=t["text_secondary"]
                )
                self.gui_pacing_val.pack(anchor="w", padx=14, pady=(4, 14))
            else:
                self.gui_drop_val = value
                ctk.CTkLabel(
                    metric, text="Lower is better", font=ctk.CTkFont(size=11),
                    text_color=t["text_secondary"]
                ).pack(anchor="w", padx=14, pady=(4, 14))

        details = make_card(diagnostics)
        card_heading(details, "Connection notes")
        info = ctk.CTkFrame(details, fg_color="transparent")
        info.pack(fill="x", padx=18, pady=(0, 18))
        for label, value in (
            ("Control path", "Local network  ·  no per-frame cloud round trip"),
            ("Web dashboard", f"http://{self.local_ip}:{self.hub.config.get('web', {}).get('port', 8765)}"),
            ("Configured devices", ", ".join(str(getattr(ctx, "name", key)) for key, ctx in self.hub.devices.items()) or "None"),
        ):
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(
                row, text=label, width=150, anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=value, anchor="w", wraplength=760,
                font=ctk.CTkFont(size=12), text_color=t["text_secondary"]
            ).pack(side="left", fill="x", expand=True)

        # Persistent status bar along the bottom edge.
        self.status_bar = ctk.CTkFrame(self.root_frame, height=32, fg_color=t["surface"], corner_radius=0)
        self.status_bar.pack(fill="x", side="bottom")
        port = self.hub.config.get("web", {}).get("port", 8765)
        web_url = f"http://{self.local_ip}:{port}"
        self._bar_dev = ctk.CTkLabel(
            self.status_bar, text=f"  Summer Light Hub  ·  Phone dashboard: {web_url}",
            font=ctk.CTkFont(size=10), text_color=t["text_muted"], anchor="w"
        )
        self._bar_dev.pack(side="left", padx=10)
        self._bar_diag = ctk.CTkLabel(
            self.status_bar, text="TX  — FPS  ·  — ms  ·  —% drop",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#34d399", anchor="e"
        )
        self._bar_diag.pack(side="right", padx=10)

        self._build_tray_ui()
        if self.window_mode == "tray":
            self.workspace.pack_forget()
            if hasattr(self, "status_bar"):
                self.status_bar.pack_forget()
            self.tray_workspace.pack(fill="both", expand=True, padx=8, pady=(0, 6))
            self.header_title.configure(text="Summer  ·  Quick Hub")
        else:
            self.tray_workspace.pack_forget()
            self.workspace.pack(fill="both", expand=True, padx=8, pady=(0, 6))
            if hasattr(self, "status_bar"):
                self.status_bar.pack(fill="x", side="bottom")
            self.header_title.configure(text="Summer  /  Light Control")

        self._switch_page("overview")
        self._sync_view_to_device()
        self.app.after(900, self._periodic_telemetry_tick)

    def _build_tray_ui(self):
        """Build the dedicated compact system-tray flyout workspace."""
        t = self.theme
        scroll_kwargs = {
            "fg_color": "transparent",
            "scrollbar_button_color": t["surface_high"],
            "scrollbar_button_hover_color": t["accent"],
            "corner_radius": 0,
        }
        self.tray_workspace = ctk.CTkScrollableFrame(self.root_frame, **scroll_kwargs)

        # 1. Device Targets
        self.tray_targets_frame = ctk.CTkFrame(
            self.tray_workspace, fg_color=t["surface"], corner_radius=8,
            border_width=1, border_color=t["border"]
        )
        self.tray_targets_frame.pack(fill="x", pady=(0, 8))
        tray_targets_inner = ctk.CTkFrame(self.tray_targets_frame, fg_color="transparent")
        tray_targets_inner.pack(fill="x", padx=6, pady=6)
        
        self.tray_tab_buttons = {}
        for dev_id, short_label in self._device_tab_short_labels.items():
            is_selected = (dev_id == self.current_dev_id)
            btn = ctk.CTkButton(
                tray_targets_inner,
                text=short_label,
                height=30,
                fg_color=t["accent_soft"] if is_selected else "transparent",
                hover_color=t["surface_high"],
                text_color=t["text_primary"] if is_selected else t["text_secondary"],
                border_width=1 if is_selected else 0,
                border_color=t["accent"] if is_selected else t["border"],
                font=ctk.CTkFont(size=11, weight="bold"),
                corner_radius=6,
                command=lambda d=dev_id: self._select_device_tab(d)
            )
            btn.pack(side="left", fill="x", expand=True, padx=2)
            self.tray_tab_buttons[dev_id] = btn

        # 2. Hero Card
        self.tray_hero_card = ctk.CTkFrame(
            self.tray_workspace, fg_color=t["hero_tint"], corner_radius=9,
            border_width=1, border_color=t["hero_border"]
        )
        self.tray_hero_card.pack(fill="x", pady=(0, 8))
        
        hero_inner = ctk.CTkFrame(self.tray_hero_card, fg_color="transparent")
        hero_inner.pack(fill="x", padx=12, pady=10)
        hero_inner.columnconfigure(0, weight=1)
        
        top_row = ctk.CTkFrame(hero_inner, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="w")
        self.tray_hero_tag = ctk.CTkLabel(
            top_row, text="L930", fg_color=t["surface_raised"], corner_radius=5,
            padx=8, pady=2, font=ctk.CTkFont(size=10, weight="bold"), text_color=t["accent_glow"]
        )
        self.tray_hero_tag.pack(side="left", padx=(0, 6))
        self.tray_hero_title = ctk.CTkLabel(
            hero_inner, text="Light strip", anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=t["text_primary"]
        )
        self.tray_hero_title.grid(row=1, column=0, sticky="w", pady=(2, 0))
        
        st_row = ctk.CTkFrame(hero_inner, fg_color="transparent")
        st_row.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.tray_hero_status_dot = ctk.CTkLabel(st_row, text="●", font=ctk.CTkFont(size=9), text_color="#35d399")
        self.tray_hero_status_dot.pack(side="left", padx=(0, 4))
        self.tray_hero_status_lbl = ctk.CTkLabel(st_row, text="Active", font=ctk.CTkFont(size=11, weight="bold"), text_color=t["text_secondary"])
        self.tray_hero_status_lbl.pack(side="left")
        
        self.tray_btn_power = ctk.CTkButton(
            hero_inner, text="⏻", width=42, height=42, corner_radius=8,
            fg_color=t["accent_soft"], hover_color=t["accent"], border_width=1, border_color=t["accent"],
            font=ctk.CTkFont(size=18, weight="bold"), text_color=t["text_primary"],
            command=self._handle_power_click
        )
        self.tray_btn_power.grid(row=0, column=1, rowspan=3, sticky="e")

        # 3. Brightness Card
        self.tray_bright_card = ctk.CTkFrame(
            self.tray_workspace, fg_color=t["surface"], corner_radius=9,
            border_width=1, border_color=t["border"]
        )
        self.tray_bright_card.pack(fill="x", pady=(0, 8))
        
        b_top = ctk.CTkFrame(self.tray_bright_card, fg_color="transparent")
        b_top.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(b_top, text="Brightness", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_primary"]).pack(side="left")
        self.tray_bright_val_label = ctk.CTkLabel(b_top, text="50%", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["accent_glow"])
        self.tray_bright_val_label.pack(side="right")
        
        self.tray_bright_slider = ctk.CTkSlider(
            self.tray_bright_card, from_=1, to=100, height=16,
            progress_color=t["accent"], button_color=t["accent_glow"], button_hover_color=t["accent"],
            command=self._on_brightness_slide
        )
        self.tray_bright_slider.pack(fill="x", padx=12, pady=(2, 6))
        
        chips_row = ctk.CTkFrame(self.tray_bright_card, fg_color="transparent")
        chips_row.pack(fill="x", padx=10, pady=(0, 8))
        chips_row.columnconfigure((0, 1, 2, 3), weight=1)
        self.tray_quick_level_buttons = {}
        for idx, lvl in enumerate([20, 50, 80, 100]):
            c_btn = ctk.CTkButton(
                chips_row, text=f"{lvl}%", height=24,
                fg_color=t["surface_raised"], hover_color=t["surface_high"],
                text_color=t["text_secondary"], font=ctk.CTkFont(size=10, weight="bold"),
                corner_radius=5, command=lambda v=lvl: self._set_quick_brightness(v)
            )
            c_btn.grid(row=0, column=idx, padx=2, sticky="ew")
            self.tray_quick_level_buttons[lvl] = c_btn

        # 4. Interactive Modes
        modes_frame = ctk.CTkFrame(self.tray_workspace, fg_color="transparent")
        modes_frame.pack(fill="x", pady=(0, 8))
        modes_frame.columnconfigure((0, 1), weight=1)
        
        self.tray_btn_music = ctk.CTkButton(
            modes_frame, text="♫  Music Reactive", height=36, corner_radius=8,
            fg_color=t["surface_raised"], hover_color=t["surface_high"],
            border_width=1, border_color=t["border"], text_color=t["text_primary"],
            font=ctk.CTkFont(size=11, weight="bold"), command=self._handle_music_toggle
        )
        self.tray_btn_music.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        
        self.tray_btn_scr = ctk.CTkButton(
            modes_frame, text="📺  Screen Sync", height=36, corner_radius=8,
            fg_color=t["surface_raised"], hover_color=t["surface_high"],
            border_width=1, border_color=t["border"], text_color=t["text_primary"],
            font=ctk.CTkFont(size=11, weight="bold"), command=self._handle_screen_toggle
        )
        self.tray_btn_scr.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        # 5. Quick Vibes
        self.scenes_card = ctk.CTkFrame(
            self.tray_workspace, fg_color=t["surface"], corner_radius=9,
            border_width=1, border_color=t["border"]
        )
        self.scenes_card.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(self.scenes_card, text="Quick Vibes", anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_primary"]).pack(fill="x", padx=12, pady=(8, 4))
        
        scenes_grid = ctk.CTkFrame(self.scenes_card, fg_color="transparent")
        scenes_grid.pack(fill="x", padx=8, pady=(0, 8))
        scenes_grid.columnconfigure((0, 1, 2), weight=1)
        
        self.tray_buttons = {}
        tray_scenes = [
            ("work", "💼 Work"),
            ("movie", "🎬 Movie"),
            ("synthwave", "🌆 Synth"),
            ("fireplace", "🔥 Fire"),
            ("sunset", "🌅 Sunset"),
            ("cyberpunk", "⚡ Cyber"),
        ]
        for idx, (m_name, m_lbl) in enumerate(tray_scenes):
            s_btn = ctk.CTkButton(
                scenes_grid, text=m_lbl, height=30, corner_radius=6,
                fg_color=t["surface_raised"], hover_color=t["surface_high"],
                border_width=1, border_color=t["border"], text_color=t["text_secondary"],
                font=ctk.CTkFont(size=10, weight="bold"), command=lambda m=m_name: self._apply_mode(m)
            )
            s_btn.grid(row=idx // 3, column=idx % 3, padx=2, pady=2, sticky="ew")
            self.tray_buttons[f"mode_{m_name}"] = s_btn

        # 6. Dynamic Effects (Shows Starred Favorites First)
        self.fx_card_tray = ctk.CTkFrame(
            self.tray_workspace, fg_color=t["surface"], corner_radius=9,
            border_width=1, border_color=t["border"]
        )
        self.fx_card_tray.pack(fill="x", pady=(0, 8))
        self.lbl_tray_fx_title = ctk.CTkLabel(self.fx_card_tray, text="Dynamic Effects", anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_primary"])
        self.lbl_tray_fx_title.pack(fill="x", padx=12, pady=(8, 4))

        self.fx_grid_tray = ctk.CTkFrame(self.fx_card_tray, fg_color="transparent")
        self.fx_grid_tray.pack(fill="x", padx=8, pady=(0, 8))
        self.fx_grid_tray.columnconfigure((0, 1), weight=1)
        self._update_tray_dynamic_effects()

        # 7. Pop Out Action Card
        self.popout_card = ctk.CTkFrame(
            self.tray_workspace, fg_color=t["hero_tint"], corner_radius=9,
            border_width=1, border_color=t["hero_border"]
        )
        self.popout_card.pack(fill="x", pady=(0, 6))
        
        self.btn_big_popout = ctk.CTkButton(
            self.popout_card, text="⤢  Pop Out to Full Window", height=38, corner_radius=8,
            fg_color=t["accent"], hover_color=t["accent_glow"],
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#ffffff",
            command=self.pop_out
        )
        self.btn_big_popout.pack(fill="x", padx=10, pady=(10, 4))
        
        lbl_hint = ctk.CTkLabel(
            self.popout_card, text=f"Phone app: http://{self.local_ip}:{self.hub.config.get('web', {}).get('port', 8765)}  ·  Esc hides",
            font=ctk.CTkFont(size=9), text_color=t["text_muted"]
        )
        lbl_hint.pack(padx=10, pady=(0, 8))

    def _switch_page(self, page_name: str):
        """Display only the active section cleanly and instantaneously."""
        if page_name not in getattr(self, "page_views", {}):
            return
        self.active_page = page_name
        for key, p_frame in self.page_views.items():
            if key == page_name:
                p_frame.pack(fill="x", expand=False)
            else:
                p_frame.pack_forget()

        for key, btn in getattr(self, "nav_tab_buttons", {}).items():
            is_act = (key == page_name)
            btn.configure(
                fg_color=self.theme["accent"] if is_act else "transparent",
                text_color="#ffffff" if is_act else self.theme["text_secondary"]
            )
        try:
            self.content_area._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _make_item_button(self, parent, label: str, dot_color: str, cmd, is_starred: bool = False, on_star=None):
        t = self.theme
        frame = ctk.CTkFrame(
            parent, fg_color=t["surface_raised"], bg_color=t["surface"],
            border_width=1, border_color=t["border"],
            corner_radius=8, cursor="hand2"
        )
        frame.bind("<Button-1>", lambda e: cmd())

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(expand=True, fill="both", padx=10, pady=8)
        inner.bind("<Button-1>", lambda e: cmd())

        dot = ctk.CTkLabel(inner, text="●", font=ctk.CTkFont(size=10), text_color=dot_color)
        dot.pack(side="left", padx=(0, 6))
        dot.bind("<Button-1>", lambda e: cmd())

        lbl = ctk.CTkLabel(inner, text=label, font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_primary"])
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e: cmd())

        if on_star:
            star_btn = ctk.CTkButton(
                inner,
                text="★" if is_starred else "☆",
                width=26, height=26, corner_radius=5,
                fg_color="transparent",
                hover_color=t["surface_high"],
                text_color="#fbbf24" if is_starred else t["text_muted"],
                font=ctk.CTkFont(size=13, weight="bold"),
                command=on_star
            )
            star_btn.pack(side="right", padx=(2, 0))

        def on_enter(e):
            frame.configure(fg_color=self.theme["surface_high"])
        def on_leave(e):
            is_active = getattr(frame, "_active", False)
            frame.configure(fg_color=self.theme["accent_soft"] if is_active else self.theme["surface_raised"])

        for w in [frame, inner, dot, lbl]:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        frame._active = False
        return frame

    def _update_tray_dynamic_effects(self):
        """Update the quick dynamic effects cards in the tray flyout to showcase starred effects."""
        if not hasattr(self, "fx_grid_tray") or not self.fx_grid_tray.winfo_exists():
            return
        for w in self.fx_grid_tray.winfo_children():
            w.destroy()
        t = self.theme
        full_st = self.hub.get_full_state()
        catalog = full_st.get("effects_catalog", {})
        active_names = full_st.get("effects_l930", [])

        starred_names = [n for n in active_names if n in getattr(self, "starred_effects", set())]
        if starred_names:
            tray_items = [(n, f"★ {catalog.get(n, {}).get('display_name') or n.replace('_', ' ').title()}") for n in starred_names[:6]]
            if hasattr(self, "lbl_tray_fx_title"):
                self.lbl_tray_fx_title.configure(text=f"Starred Favorites ({len(starred_names)})")
        else:
            tray_items = [
                ("ambient_drift", "✦ Ambient Drift"),
                ("bioluminescent_tide", "🌊 Bio Tide"),
                ("nebula_bloom", "🌌 Nebula Bloom"),
                ("rainbow", "🌈 Rainbow"),
            ]
            if hasattr(self, "lbl_tray_fx_title"):
                self.lbl_tray_fx_title.configure(text="Dynamic Effects")

        for idx, (e_name, e_lbl) in enumerate(tray_items):
            e_btn = ctk.CTkButton(
                self.fx_grid_tray, text=e_lbl, height=30, corner_radius=6,
                fg_color=t["surface_raised"], hover_color=t["surface_high"],
                border_width=1, border_color=t["border"], text_color=t["text_secondary"],
                font=ctk.CTkFont(size=10, weight="bold"), command=lambda e=e_name: self._apply_effect(e)
            )
            e_btn.grid(row=idx // 2, column=idx % 2, padx=2, pady=2, sticky="ew")
            self.tray_buttons[f"eff_{e_name}"] = e_btn

    def _set_fx_filter(self, mode: str):
        """Switch active dynamic effects shelf filter: all, starred, 1d, 2d."""
        self._fx_filter_mode = mode
        self._render_effects_list()

    def _toggle_star_effect(self, name: str):
        """Toggle starred favorite status for an effect and refresh displays."""
        if name in self.starred_effects:
            self.starred_effects.remove(name)
        else:
            self.starred_effects.add(name)
        save_starred_effects(self.starred_effects)
        self._render_effects_list()
        self._update_tray_dynamic_effects()

    def _render_effects_list(self):
        # Clean up stale effect button references before destroying widgets
        self.buttons = {k: v for k, v in self.buttons.items() if not k.startswith("eff_")}

        for widget in self.fx_grid_frame.winfo_children():
            widget.destroy()

        is_l930 = False
        if self.current_dev_id in self.hub.devices:
            is_l930 = (self.hub.devices[self.current_dev_id].model == "L930")
        elif self.current_dev_id == "all":
            is_l930 = any(getattr(ctx, "model", "") == "L930" for ctx in self.hub.devices.values())

        t = self.theme

        # ── Parameter Controls Row (Speed, Brightness, Palette) ──
        fx_ctrls = ctk.CTkFrame(self.fx_grid_frame, fg_color=t["surface_raised"], corner_radius=10)
        fx_ctrls.pack(fill="x", pady=(0, 10))
        fc_inner = ctk.CTkFrame(fx_ctrls, fg_color="transparent")
        fc_inner.pack(fill="x", padx=10, pady=8)

        # Row 1: Speed & Brightness
        sb_row = ctk.CTkFrame(fc_inner, fg_color="transparent")
        sb_row.pack(fill="x", pady=(0, 4))
        sb_row.columnconfigure((0, 1), weight=1)

        # Speed
        sp_box = ctk.CTkFrame(sb_row, fg_color="transparent")
        sp_box.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        sp_hdr = ctk.CTkFrame(sp_box, fg_color="transparent")
        sp_hdr.pack(fill="x")
        ctk.CTkLabel(sp_hdr, text="⚡ Speed:", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]).pack(side="left")
        self.lbl_fx_speed = ctk.CTkLabel(sp_hdr, text="1.0x", font=ctk.CTkFont(family="Consolas", size=9, weight="bold"), text_color=t["accent_glow"])
        self.lbl_fx_speed.pack(side="right")
        self.slider_fx_speed = ctk.CTkSlider(
            sp_box, from_=0.2, to=3.0, number_of_steps=28,
            command=self._on_fx_speed_slide,
            fg_color=t["surface_high"], progress_color=t["accent"],
            button_color=t["accent_glow"], height=14
        )
        self.slider_fx_speed.set(1.0)
        self.slider_fx_speed.pack(fill="x", pady=(1, 0))

        # Palette
        pal_box = ctk.CTkFrame(sb_row, fg_color="transparent")
        pal_box.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        pal_hdr = ctk.CTkFrame(pal_box, fg_color="transparent")
        pal_hdr.pack(fill="x")
        ctk.CTkLabel(pal_hdr, text="🎨 Palette:", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]).pack(side="left")
        pal_names = ["sunset", "forest", "fire", "pastel", "tide", "dusk", "ember", "warm_mono"]
        self.opt_fx_pal = ctk.CTkOptionMenu(
            pal_box, values=pal_names,
            command=self._on_fx_palette_selected,
            fg_color=t["surface_high"], button_color=t["surface_raised"],
            text_color=t["text_primary"], height=30, corner_radius=6,
            font=ctk.CTkFont(size=9)
        )
        self.opt_fx_pal.set("sunset")
        self.opt_fx_pal.pack(fill="x", pady=(4, 0))

        # Row 2: Dynamic Effect-Specific Tuning Sliders Container
        self.fx_specific_frame = ctk.CTkFrame(fc_inner, fg_color="transparent")
        self.fx_specific_frame.pack(fill="x", pady=(4, 0))
        self._register_responsive_grid(self.fx_specific_frame, max_columns=2)
        self.fx_specific_frame.columnconfigure((0, 1), weight=1)

        # 1. Tail Length Slider Box
        self.box_fx_tail = ctk.CTkFrame(self.fx_specific_frame, fg_color="transparent")
        tail_hdr = ctk.CTkFrame(self.box_fx_tail, fg_color="transparent")
        tail_hdr.pack(fill="x")
        ctk.CTkLabel(tail_hdr, text="☄ Tail Length:", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]).pack(side="left")
        self.lbl_fx_tail = ctk.CTkLabel(tail_hdr, text="1.0x", font=ctk.CTkFont(family="Consolas", size=9, weight="bold"), text_color=t["accent_glow"])
        self.lbl_fx_tail.pack(side="right")
        self.slider_fx_tail = ctk.CTkSlider(
            self.box_fx_tail, from_=0.3, to=3.0, number_of_steps=27,
            command=self._on_fx_tail_slide,
            fg_color=t["surface_high"], progress_color=t["accent"],
            button_color=t["accent_glow"], height=14
        )
        self.slider_fx_tail.set(1.0)
        self.slider_fx_tail.pack(fill="x", pady=(1, 0))

        # 2. Particle Density Slider Box
        self.box_fx_density = ctk.CTkFrame(self.fx_specific_frame, fg_color="transparent")
        dens_hdr = ctk.CTkFrame(self.box_fx_density, fg_color="transparent")
        dens_hdr.pack(fill="x")
        ctk.CTkLabel(dens_hdr, text="✨ Density:", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]).pack(side="left")
        self.lbl_fx_density = ctk.CTkLabel(dens_hdr, text="1.0x", font=ctk.CTkFont(family="Consolas", size=9, weight="bold"), text_color=t["accent_glow"])
        self.lbl_fx_density.pack(side="right")
        self.slider_fx_density = ctk.CTkSlider(
            self.box_fx_density, from_=0.2, to=3.0, number_of_steps=28,
            command=self._on_fx_density_slide,
            fg_color=t["surface_high"], progress_color=t["accent"],
            button_color=t["accent_glow"], height=14
        )
        self.slider_fx_density.set(1.0)
        self.slider_fx_density.pack(fill="x", pady=(1, 0))

        # 3. Wave Width Slider Box
        self.box_fx_width = ctk.CTkFrame(self.fx_specific_frame, fg_color="transparent")
        width_hdr = ctk.CTkFrame(self.box_fx_width, fg_color="transparent")
        width_hdr.pack(fill="x")
        ctk.CTkLabel(width_hdr, text="🌊 Wave Width:", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]).pack(side="left")
        self.lbl_fx_width = ctk.CTkLabel(width_hdr, text="1.0x", font=ctk.CTkFont(family="Consolas", size=9, weight="bold"), text_color=t["accent_glow"])
        self.lbl_fx_width.pack(side="right")
        self.slider_fx_width = ctk.CTkSlider(
            self.box_fx_width, from_=0.3, to=3.0, number_of_steps=27,
            command=self._on_fx_width_slide,
            fg_color=t["surface_high"], progress_color=t["accent"],
            button_color=t["accent_glow"], height=14
        )
        self.slider_fx_width.set(1.0)
        self.slider_fx_width.pack(fill="x", pady=(1, 0))

        # 4. Flash Strength Slider Box
        self.box_fx_flash = ctk.CTkFrame(self.fx_specific_frame, fg_color="transparent")
        flash_hdr = ctk.CTkFrame(self.box_fx_flash, fg_color="transparent")
        flash_hdr.pack(fill="x")
        ctk.CTkLabel(flash_hdr, text="⚡ Flash Pwr:", font=ctk.CTkFont(size=12, weight="bold"), text_color=t["text_muted"]).pack(side="left")
        self.lbl_fx_flash = ctk.CTkLabel(flash_hdr, text="1.0x", font=ctk.CTkFont(family="Consolas", size=9, weight="bold"), text_color=t["accent_glow"])
        self.lbl_fx_flash.pack(side="right")
        self.slider_fx_flash = ctk.CTkSlider(
            self.box_fx_flash, from_=0.2, to=2.5, number_of_steps=23,
            command=self._on_fx_flash_slide,
            fg_color=t["surface_high"], progress_color=t["accent"],
            button_color=t["accent_glow"], height=14
        )
        self.slider_fx_flash.set(1.0)
        self.slider_fx_flash.pack(fill="x", pady=(1, 0))

        # Refresh visible controls based on active effect
        self._update_effect_specific_controls()

        # Search remains outside the generated buttons and is restored after rebuilds.
        search_wrap = ctk.CTkFrame(self.fx_grid_frame, fg_color="transparent")
        search_wrap.pack(fill="x", pady=(0, 8))
        self.effect_search_entry = ctk.CTkEntry(
            search_wrap, placeholder_text="Search effects by name or behavior…",
            height=30, corner_radius=8, border_color=t["border"],
            fg_color=t["surface_raised"], text_color=t["text_primary"],
            placeholder_text_color=t["text_muted"],
        )
        self.effect_search_entry.pack(fill="x")
        saved_query = getattr(self, "_effect_search_text", "")
        if saved_query:
            self.effect_search_entry.insert(0, saved_query)
        self.effect_search_entry.bind("<KeyRelease>", self._filter_effect_buttons)
        self._effect_group_grids = {}
        self._effect_group_labels = {}

        if is_l930:
            self.fx_header_label.configure(text="L930 50-ZONE WRGBIC EFFECTS")
            full_st = self.hub.get_full_state()
            catalog = full_st.get("effects_catalog", {})

            # Show the full WLED-inspired audition shelf, separated by dimensional behavior.
            # "2D" is spatially projected onto the configured 50-zone strip topology.
            active_names = full_st.get("effects_l930", [])
            starred_names = [name for name in active_names if name in getattr(self, "starred_effects", set())]
            strip_names = [name for name in active_names if catalog.get(name, {}).get("dimension") == "1D"]
            spatial_names = [name for name in active_names if catalog.get(name, {}).get("dimension") == "2D"]

            # Filter Mode Tabs (All, Starred Favorites, 1D Strip, 2D Spatial)
            filter_bar = ctk.CTkFrame(self.fx_grid_frame, fg_color="transparent")
            filter_bar.pack(fill="x", pady=(0, 10))
            filter_opts = [
                ("all", f"All ({len(active_names)})"),
                ("starred", f"★ Starred ({len(starred_names)})"),
                ("1d", f"1D Strip ({len(strip_names)})"),
                ("2d", f"2D Spatial ({len(spatial_names)})"),
            ]
            for mode_key, mode_title in filter_opts:
                is_sel = (getattr(self, "_fx_filter_mode", "all") == mode_key)
                f_btn = ctk.CTkButton(
                    filter_bar,
                    text=mode_title,
                    height=28,
                    corner_radius=6,
                    fg_color=t["accent"] if is_sel else t["surface_raised"],
                    hover_color=t["surface_high"],
                    text_color="#ffffff" if is_sel else t["text_secondary"],
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=lambda k=mode_key: self._set_fx_filter(k)
                )
                f_btn.pack(side="left", padx=(0, 6))

            # Determine groups to display based on active filter mode
            groups = {}
            fx_mode = getattr(self, "_fx_filter_mode", "all")
            if fx_mode == "starred":
                if starred_names:
                    groups["★ Starred Favorites"] = starred_names
                else:
                    empty_lbl = ctk.CTkLabel(
                        self.fx_grid_frame,
                        text="★ No starred effects yet!\nClick the star (☆) on any effect card to save your favorites here for fast access.",
                        font=ctk.CTkFont(size=13),
                        text_color=t["text_muted"],
                        justify="center"
                    )
                    empty_lbl.pack(fill="x", pady=24)
            elif fx_mode == "1d":
                groups["1D Strip Effects"] = strip_names
            elif fx_mode == "2d":
                groups["2D Spatial Projection"] = spatial_names
            else:  # "all"
                if starred_names:
                    groups["★ Starred Favorites"] = starred_names
                groups["1D Strip Effects"] = strip_names
                groups["2D Spatial Projection"] = spatial_names

            for grp_name, eff_names in groups.items():
                if not eff_names:
                    continue

                grp_hdr_frame = ctk.CTkFrame(self.fx_grid_frame, fg_color="transparent")
                grp_hdr_frame.pack(fill="x", pady=(8, 4))

                is_starred_grp = "Starred" in grp_name
                hdr_icon = "★" if is_starred_grp else "●"
                hdr_color = "#fbbf24" if is_starred_grp else t["accent_glow"]
                hdr_text = f"{hdr_icon}  {grp_name.upper()} ({len(eff_names)})"
                grp_lbl = ctk.CTkLabel(
                    grp_hdr_frame, text=hdr_text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=hdr_color, anchor="w"
                )
                grp_lbl.pack(side="left")

                grid = ctk.CTkFrame(self.fx_grid_frame, fg_color="transparent")
                grid.pack(fill="x", pady=(0, 8))
                self._register_responsive_grid(grid)
                grid.columnconfigure((0, 1), weight=1, uniform="fx")
                self._effect_group_grids[grp_name] = grid
                self._effect_group_labels[grp_name] = grp_lbl

                for idx, name in enumerate(eff_names):
                    r, c = divmod(idx, 2)
                    dot_col = EFFECT_COLORS.get(name, self.theme["accent"])
                    display = catalog.get(name, {}).get("display_name") or name.replace("_", " ").title()
                    btn = self._make_item_button(
                        grid, display, dot_col,
                        lambda n=name: self._apply_effect(n),
                        is_starred=(name in getattr(self, "starred_effects", set())),
                        on_star=lambda n=name: self._toggle_star_effect(n)
                    )
                    btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
                    self.buttons[f"eff_{name}"] = btn
        else:
            self.fx_header_label.configure(text="L900 SLOW AMBIENT EFFECTS")
            eff_list = [
                "ambient_drift", "fireplace", "golden_hour", "ocean_waves", "color_breath", "candle_flicker"
            ]
            grid = ctk.CTkFrame(self.fx_grid_frame, fg_color="transparent")
            grid.pack(fill="x")
            self._register_responsive_grid(grid)
            grid.columnconfigure((0, 1), weight=1, uniform="fx")

            for idx, name in enumerate(eff_list):
                r, c = divmod(idx, 2)
                dot_col = EFFECT_COLORS.get(name, self.theme["accent"])
                display = name.replace("_", " ").title()
                btn = self._make_item_button(grid, display, dot_col, lambda n=name: self._apply_effect(n))
                btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
                self.buttons[f"eff_{name}"] = btn

        # Re-bind mousewheel on newly generated effect controls & cards

    def _filter_effect_buttons(self, event=None):
        """Filter effect buttons using labels, groups and catalog descriptions."""
        try:
            query = self.effect_search_entry.get().strip().lower()
            self._effect_search_text = query
            catalog = self.hub.get_full_state().get("effects_catalog", {})
            matching_groups = set()
            for key, button in list(self.buttons.items()):
                if not key.startswith("eff_"):
                    continue
                name = key[4:]
                meta = catalog.get(name, {})
                haystack = f"{name} {meta.get('desc', '')} {meta.get('group', '')}".lower()
                dimension = str(meta.get("dimension", "")).upper()
                grp_target = (
                    "WLED 1D · Strip Effects" if dimension == "1D"
                    else "WLED 2D · Spatial Projection" if dimension == "2D"
                    else ""
                )
                if query in haystack:
                    button.grid()
                    if grp_target:
                        matching_groups.add(grp_target)
                else:
                    button.grid_remove()

            # Reveal a collapsed group when search matches one of its effects.
            for group_name, group_grid in getattr(self, "_effect_group_grids", {}).items():
                group_label = self._effect_group_labels.get(group_name)
                if query and group_name in matching_groups:
                    if not group_grid.winfo_ismapped():
                        group_grid.pack(fill="x", pady=(0, 6))
                    if group_label:
                        hdr_ico = "★" if "Starred" in group_name else "●"
                        group_label.configure(text=f"{hdr_ico}  {group_name.upper()}")
                elif group_name in ("Seasonal", "Novelty (⚠️ Rapid Flashing)"):
                    group_grid.pack_forget()
                    if group_label:
                        group_label.configure(text=f"○  {group_name.upper()} (COLLAPSED)")
        except Exception:
            pass

    def _on_fx_speed_slide(self, val: float):
        v = round(float(val), 2)
        self.lbl_fx_speed.configure(text=f"{v}x")
        dev_ctx = self.hub.devices.get(self.current_dev_id)
        if dev_ctx and hasattr(dev_ctx.fx_engine, "set_parameters"):
            dev_ctx.fx_engine.set_parameters(speed=v)

    def _on_fx_palette_selected(self, pal_name: str):
        dev_ctx = self.hub.devices.get(self.current_dev_id)
        if dev_ctx and hasattr(dev_ctx.fx_engine, "set_parameters"):
            dev_ctx.fx_engine.set_parameters(palette_name=pal_name)

    def _on_fx_tail_slide(self, val: float):
        v = round(float(val), 2)
        self.lbl_fx_tail.configure(text=f"{v}x")
        self.hub.set_effect_params(self.current_dev_id, tail_length=v)

    def _on_fx_density_slide(self, val: float):
        v = round(float(val), 2)
        self.lbl_fx_density.configure(text=f"{v}x")
        self.hub.set_effect_params(self.current_dev_id, particle_density=v)

    def _on_fx_width_slide(self, val: float):
        v = round(float(val), 2)
        self.lbl_fx_width.configure(text=f"{v}x")
        self.hub.set_effect_params(self.current_dev_id, wave_width=v)

    def _on_fx_flash_slide(self, val: float):
        v = round(float(val), 2)
        self.lbl_fx_flash.configure(text=f"{v}x")
        self.hub.set_effect_params(self.current_dev_id, flash_strength=v)

    def _update_effect_specific_controls(self, effect_name: Optional[str] = None):
        """Dynamically reveals only the sliders supported by the selected effect."""
        try:
            if not hasattr(self, "fx_specific_frame"):
                return
            dev = self.hub.devices.get(self.current_dev_id)
            eff = effect_name or (dev.state.get("active_label", "") if dev else "") or ""
            eff_clean = eff.lower().strip()

            catalog = self.hub.get_full_state().get("effects_catalog", {})
            meta = catalog.get(eff_clean, {})
            supported = set(meta.get("supported_controls", ["speed", "brightness"]))

            # Unpack all specific boxes first
            for box in (self.box_fx_tail, self.box_fx_density, self.box_fx_width, self.box_fx_flash):
                box.grid_remove()

            visible_count = 0
            if "tail_length" in supported:
                r, c = divmod(visible_count, 2)
                self.box_fx_tail.grid(row=r, column=c, sticky="ew", padx=(0 if c == 0 else 4, 4 if c == 0 else 0), pady=2)
                visible_count += 1

            if "particle_density" in supported:
                r, c = divmod(visible_count, 2)
                self.box_fx_density.grid(row=r, column=c, sticky="ew", padx=(0 if c == 0 else 4, 4 if c == 0 else 0), pady=2)
                visible_count += 1

            if "wave_width" in supported:
                r, c = divmod(visible_count, 2)
                self.box_fx_width.grid(row=r, column=c, sticky="ew", padx=(0 if c == 0 else 4, 4 if c == 0 else 0), pady=2)
                visible_count += 1

            if "flash_strength" in supported:
                r, c = divmod(visible_count, 2)
                self.box_fx_flash.grid(row=r, column=c, sticky="ew", padx=(0 if c == 0 else 4, 4 if c == 0 else 0), pady=2)
                visible_count += 1

            if visible_count > 0:
                self.fx_specific_frame.pack(fill="x", pady=(4, 0))
            else:
                self.fx_specific_frame.pack_forget()
        except Exception:
            pass

    def _select_device_tab(self, dev_id: str):
        self.current_dev_id = dev_id
        for did, btn in self.tab_buttons.items():
            is_active = (did == dev_id)
            btn.configure(
                fg_color=self.theme["surface_raised"] if is_active else "transparent",
                border_width=1 if is_active else 0,
                border_color=self.theme["accent"] if is_active else self.theme["border"],
                text_color=self.theme["text_primary"] if is_active else self.theme["text_secondary"]
            )
        self._render_effects_list()
        self._sync_view_to_device()

    def _apply_theme(self, theme_key: str):
        """Update accent colours without repainting the entire UI as one glow."""
        if theme_key not in THEMES or theme_key == self.current_theme_key:
            return
        self.current_theme_key = theme_key
        self.theme = THEMES[theme_key]
        t = self.theme

        for name in ("app",):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(fg_color=t["bg"])
                except Exception:
                    pass
        for name in ("root_frame", "header"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(fg_color=t["bg"])
                except Exception:
                    pass
        for name in ("nav_rail", "tabs_bar", "bright_card", "sync_card", "fx_card", "preset_card", "diag_card", "status_bar", "vstyles_frame"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(fg_color=t["surface"], border_color=t["border"])
                except Exception:
                    try:
                        widget.configure(fg_color=t["surface"])
                    except Exception:
                        pass
        for name in ("hero_card", "tray_hero_card", "popout_card"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(fg_color=t["hero_tint"], border_color=t["hero_border"])
                except Exception:
                    pass
        for name in ("tray_bright_card", "scenes_card", "fx_card_tray", "tray_targets_frame"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(fg_color=t["surface"], border_color=t["border"])
                except Exception:
                    pass
        for name in ("btn_top_power", "btn_hero_power"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(fg_color=t["accent_soft"], border_color=t["accent"])
                except Exception:
                    pass
        for name in ("bright_slider", "tray_bright_slider", "gui_sens_slider", "slider_bright_cap", "gui_lookahead_slider"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(
                        fg_color=t["surface_high"], progress_color=t["accent"],
                        button_color=t["accent_glow"], button_hover_color=t["accent"]
                    )
                except Exception:
                    pass
        for name in ("bright_val_label", "hero_tag", "gui_key_pill", "lbl_sens_val", "lbl_bright_cap_val"):
            widget = getattr(self, name, None)
            if widget:
                try:
                    widget.configure(text_color=t["accent_glow"])
                except Exception:
                    pass
        for key, button in getattr(self, "nav_buttons", {}).items():
            try:
                selected = key == getattr(self, "active_page", "overview")
                button.configure(
                    fg_color=t["accent_soft"] if selected else "transparent",
                    text_color=t["text_primary"] if selected else t["text_secondary"],
                    border_width=1 if selected else 0,
                    border_color=t["accent"] if selected else t["border"]
                )
            except Exception:
                pass
        for key, button in getattr(self, "tab_buttons", {}).items():
            try:
                selected = key == self.current_dev_id
                button.configure(
                    fg_color=t["accent_soft"] if selected else "transparent",
                    text_color=t["text_primary"] if selected else t["text_secondary"],
                    border_width=1 if selected else 0,
                    border_color=t["accent"] if selected else t["border"]
                )
            except Exception:
                pass
        for widget in getattr(self, "card_frames", []):
            try:
                if widget is self.hero_card:
                    widget.configure(fg_color=t["hero_tint"], border_color=t["hero_border"])
                else:
                    widget.configure(border_color=t["border"])
            except Exception:
                pass

    def _sync_view_to_device(self):
        if self.current_dev_id == "all":
            devs = list(self.hub.devices.values())
            any_on = any(d.state["power"] for d in devs)
            avg_b = sum(d.state["brightness"] for d in devs) // max(1, len(devs))
            active_labels = [str(device.state.get("active_label", "")) for device in devs]
            label = next((value for value in active_labels if "Audio" in value), "")
            if not label:
                label = next((value for value in active_labels if "Composite" in value), "")
            if not label:
                label = next((value for value in active_labels if "Screen" in value), "Both Sync")
            model_tag = "ALL"
            dev_title = "Both Strips (Sync All)"
        else:
            ctx = self.hub.devices.get(self.current_dev_id)
            if not ctx: return
            any_on = ctx.state["power"]
            avg_b = ctx.state["brightness"]
            label = ctx.state["active_label"]
            model_tag = ctx.model or "L900"
            dev_title = f"{ctx.name} ({model_tag})"

        # Avoid redundant repaints when state has not changed
        curr_sig = (self.current_dev_id, any_on, avg_b, label)
        prev_sig = getattr(self, "_last_synced_state", None)
        self._last_synced_state = curr_sig
        if prev_sig is not None and prev_sig == curr_sig:
            return

        # Dynamic Theme adaptation matching reference design
        target_theme = get_theme_for_label(label)
        self._apply_theme(target_theme)

        self.bright_slider.set(avg_b)
        self.bright_val_label.configure(text=f"{avg_b}%")
        self.hero_tag.configure(text=model_tag)
        self.hero_title.configure(text=dev_title)

        # Hero Status
        if any_on:
            self.hero_status_dot.configure(text_color="#10b981")
            self.hero_status_lbl.configure(text="Active", text_color=self.theme["text_primary"])
            self.btn_top_power.configure(fg_color=self.theme["accent_soft"], border_color=self.theme["power_glow"], text="⏻  Power")
            self.btn_hero_power.configure(fg_color=self.theme["accent_soft"], border_color=self.theme["power_glow"])
        else:
            self.hero_status_dot.configure(text_color=self.theme["text_muted"])
            self.hero_status_lbl.configure(text="Idle / Off", text_color=self.theme["text_muted"])
            self.btn_top_power.configure(fg_color="#3a1111", border_color="#f43f5e", text="⏻  Power")
            self.btn_hero_power.configure(fg_color="#3a1111", border_color="#f43f5e")

        # Quick level button highlights
        for lvl, btn in self.quick_level_buttons.items():
            is_match = (abs(avg_b - lvl) < 5)
            btn.configure(
                fg_color=self.theme["accent_soft"] if is_match else self.theme["surface_raised"],
                text_color=self.theme["accent_glow"] if is_match else self.theme["text_secondary"]
            )

        is_music = "Audio" in label or "Composite" in label
        is_screen = "Screen" in label

        self.btn_music.configure(
            fg_color=self.theme["accent_soft"] if is_music else self.theme["surface_raised"],
            border_color=self.theme["accent"] if is_music else self.theme["border"],
            text_color=self.theme["accent_glow"] if is_music else self.theme["text_primary"]
        )
        self.btn_scr.configure(
            fg_color="#0e3557" if is_screen else self.theme["surface_raised"],
            border_color="#06b6d4" if is_screen else self.theme["border"],
            text_color="#a5f3fc" if is_screen else self.theme["text_primary"]
        )

        for key, btn in list(self.buttons.items()):
            try:
                if not btn.winfo_exists():
                    self.buttons.pop(key, None)
                    continue
                active = (key == f"mode_{label}" or key == f"eff_{label}")
                btn._active = active
                btn.configure(
                    fg_color=self.theme["accent_soft"] if active else self.theme["surface_raised"],
                    border_width=1 if active else 0,
                    border_color=self.theme["accent"] if active else self.theme["border"]
                )
            except Exception:
                self.buttons.pop(key, None)

        self._update_effect_specific_controls(label)

        # Synchronize tray flyout widgets
        if hasattr(self, "tray_bright_slider"):
            self.tray_bright_slider.set(avg_b)
        if hasattr(self, "tray_bright_val_label"):
            self.tray_bright_val_label.configure(text=f"{avg_b}%")
        if hasattr(self, "tray_hero_tag"):
            self.tray_hero_tag.configure(text=model_tag)
        if hasattr(self, "tray_hero_title"):
            self.tray_hero_title.configure(text=dev_title)
        if hasattr(self, "tray_hero_status_lbl"):
            st_text = label if any_on else "Idle / Off"
            self.tray_hero_status_lbl.configure(
                text=st_text,
                text_color=self.theme["text_primary"] if any_on else self.theme["text_muted"]
            )
        if hasattr(self, "tray_hero_status_dot"):
            self.tray_hero_status_dot.configure(
                text_color="#10b981" if any_on else self.theme["text_muted"]
            )
        if hasattr(self, "tray_btn_power"):
            self.tray_btn_power.configure(
                fg_color=self.theme["accent_soft"] if any_on else "#3a1111",
                border_color=self.theme["power_glow"] if any_on else "#f43f5e"
            )
        if hasattr(self, "tray_btn_music"):
            self.tray_btn_music.configure(
                fg_color=self.theme["accent_soft"] if is_music else self.theme["surface_raised"],
                border_color=self.theme["accent"] if is_music else self.theme["border"],
                text_color=self.theme["accent_glow"] if is_music else self.theme["text_primary"]
            )
        if hasattr(self, "tray_btn_scr"):
            self.tray_btn_scr.configure(
                fg_color="#0e3557" if is_screen else self.theme["surface_raised"],
                border_color="#06b6d4" if is_screen else self.theme["border"],
                text_color="#a5f3fc" if is_screen else self.theme["text_primary"]
            )
        for lvl, btn in getattr(self, "tray_quick_level_buttons", {}).items():
            is_match = (abs(avg_b - lvl) < 5)
            btn.configure(
                fg_color=self.theme["accent_soft"] if is_match else self.theme["surface_raised"],
                text_color=self.theme["accent_glow"] if is_match else self.theme["text_secondary"]
            )
        for dev_id, btn in getattr(self, "tray_tab_buttons", {}).items():
            selected = dev_id == self.current_dev_id
            btn.configure(
                fg_color=self.theme["accent_soft"] if selected else "transparent",
                text_color=self.theme["text_primary"] if selected else self.theme["text_secondary"],
                border_width=1 if selected else 0,
                border_color=self.theme["accent"] if selected else self.theme["border"]
            )
        for key, btn in getattr(self, "tray_buttons", {}).items():
            try:
                active = (key == f"mode_{label}" or key == f"eff_{label}")
                btn.configure(
                    fg_color=self.theme["accent_soft"] if active else self.theme["surface_raised"],
                    border_color=self.theme["accent"] if active else self.theme["border"],
                    text_color=self.theme["accent_glow"] if active else self.theme["text_secondary"]
                )
            except Exception:
                pass

    def _on_hub_update(self, full_state: dict):
        try:
            if getattr(self, "_sync_job", None) is not None:
                return  # Coalesce: a sync tick is already queued
            self._sync_job = self.app.after(65, self._flushed_sync_view)
        except Exception:
            pass

    def _flushed_sync_view(self):
        self._sync_job = None
        self._sync_view_to_device()

    def _periodic_telemetry_tick(self):
        try:
            diags = self.hub.get_diagnostics()
            dev_id = self.current_dev_id
            diag = None
            if dev_id == "all":
                keys = list(diags.keys())
                l930_key = next((k for k in keys if self.hub.devices.get(k) and self.hub.devices[k].model == "L930"), None)
                diag = diags.get(l930_key or (keys[0] if keys else None))
            else:
                diag = diags.get(dev_id)

            if diag:
                self.gui_fps_val.configure(text=f"{diag['send_fps']} FPS")
                self.gui_render_val.configure(text=f"{diag['render_fps']} calc")
                self.gui_rtt_val.configure(text=f"{diag['rtt_ms']} ms")
                tot_lat = round(diag.get("total_latency_ms", 0))
                p95_lat = round(diag.get("p95_latency_ms", tot_lat))
                self.gui_pacing_val.configure(text=f"tot: {tot_lat}ms")
                self.gui_drop_val.configure(text=f"{diag['drop_rate_pct']}%")
                st = diag.get("status", "connected").capitalize()
                st_color = "#10b981" if st == "Connected" else ("#f59e0b" if st == "Reconnecting" else "#f43f5e")
                self.gui_diag_status.configure(text=f"● {st}", text_color=st_color)
                self._bar_diag.configure(
                    text=f"LAN Sync Active  ·  {diag['send_fps']} FPS",
                    text_color="#10b981" if st == "Connected" else st_color
                )
                if hasattr(self, "lbl_measured_delay") and self.lbl_measured_delay:
                    if tot_lat > 0:
                        self.lbl_measured_delay.configure(
                            text=f"Measured light delay: {tot_lat} ms (Set Voicemeeter A1 delay: ~{tot_lat} ms)"
                        )
                    else:
                        self.lbl_measured_delay.configure(
                            text="Measured light delay: -- ms (Set Voicemeeter A1 delay: ~-- ms)"
                        )

            # "Both strips" has no literal telemetry key; choose the active renderer,
            # preferring the L930 spectrum monitor when the shared target is selected.
            audio_telem = self.hub.get_audio_telemetry()
            dev_telem = audio_telem.get(self.current_dev_id)
            if self.current_dev_id == "all":
                dev_telem = next(
                    (audio_telem[key] for key, ctx in self.hub.devices.items()
                     if ctx.model == "L930" and key in audio_telem and audio_telem[key].get("renderer_running")),
                    None,
                ) or next(
                    (audio_telem[key] for key in self.hub.devices if key in audio_telem and audio_telem[key].get("renderer_running")),
                    None,
                ) or next(
                    (audio_telem[key] for key, ctx in self.hub.devices.items()
                     if ctx.model == "L930" and key in audio_telem),
                    None,
                ) or next(iter(audio_telem.values()), None)

            if dev_telem and dev_telem.get("active"):
                bpm = round(dev_telem.get("bpm", 120.0))
                deg = round(dev_telem.get("key_hue", 215.0))
                mode = (dev_telem.get("mode", "maj") or "maj").upper()
                source_name = dev_telem.get("audio_source") or "loopback"
                capture_status = dev_telem.get("capture_status", "active")
                is_extreme = bool(dev_telem.get("is_extreme_bass") or dev_telem.get("white_strobe"))
                is_beat = bool(is_extreme or dev_telem.get("kick", 0.0) > 0.65)

                if dev_telem.get("signal_active"):
                    listening_label, listening_color = f"♫  {bpm} BPM", "#34d399"
                    badge_label = "EXTREME BASS" if is_extreme else ("BEAT HIT" if is_beat else "SYNC ACTIVE")
                    badge_color = "#f43f5e" if is_extreme else ("#34d399" if is_beat else self.theme["accent_glow"])
                else:
                    listening_label, listening_color = "Listening · waiting for audio", "#fbbf24"
                    badge_label = "LISTENING"
                    badge_color = "#fbbf24"
                if capture_status == "error":
                    listening_label, listening_color = "Audio capture error", "#fb7185"
                    badge_label = "ERROR"
                    badge_color = "#fb7185"

                self.gui_bpm_lbl.configure(text=listening_label, text_color=listening_color)
                self.gui_section_badge.configure(text=badge_label, text_color=badge_color)
                self.gui_key_pill.configure(text=f"🎼 {deg}° {mode}")

                # Sync active visual style button & cards
                cur_vstyle = dev_telem.get("style", "auto")
                self._update_style_card_selection(cur_vstyle)
                if hasattr(self, "lbl_transition_val") and self.lbl_transition_val:
                    trans = MODE_TRANSITIONS.get(cur_vstyle.lower(), 0)
                    trans_desc = "Flow" if trans > 0 else "Punchy"
                    self.lbl_transition_val.configure(text=f"Transition: {trans}ms ({trans_desc})")
            else:
                status = (dev_telem or {}).get("capture_status", "stopped")
                capture_error = (dev_telem or {}).get("capture_error")
                source_name = (dev_telem or {}).get("audio_source") or "no loopback selected"
                renderer_running = bool((dev_telem or {}).get("renderer_running"))
                if status == "error" or capture_error:
                    message = (capture_error or "Audio capture failed").replace("\n", " ")
                    self.gui_bpm_lbl.configure(text="Capture error", text_color="#fb7185")
                elif status == "starting":
                    self.gui_bpm_lbl.configure(text="Starting audio…", text_color="#fbbf24")
                elif not renderer_running:
                    self.gui_bpm_lbl.configure(text="Audio reactive is off", text_color=self.theme["text_muted"])
                else:
                    self.gui_bpm_lbl.configure(text="Listening · waiting for audio", text_color="#fbbf24")

                self.gui_section_badge.configure(text="READY", text_color=self.theme["text_muted"])
                self.gui_key_pill.configure(text="Key —")
        except Exception:
            pass
        finally:
            try:
                self.app.after(1000, self._periodic_telemetry_tick)
            except Exception:
                pass

    def _periodic_strip_preview_tick(self):
        pass

    def _draw_strip_preview(self, segments: Optional[List[Any]] = None):
        pass

    def _draw_audio_spectrum(self, spectrum: Optional[List[float]] = None):
        pass

    def _on_strip_canvas_hover(self, event=None):
        pass

    def _on_strip_canvas_leave(self, event=None):
        pass

    def _on_brightness_slide(self, val):
        v = int(val)
        self.bright_val_label.configure(text=f"{v}%")
        self.hub.set_brightness(self.current_dev_id, v)

    def _set_quick_brightness(self, lvl: int):
        self.bright_slider.set(lvl)
        self.bright_val_label.configure(text=f"{lvl}%")
        self.hub.set_brightness(self.current_dev_id, lvl)
        for qlvl, btn in self.quick_level_buttons.items():
            is_match = (qlvl == lvl)
            btn.configure(
                fg_color=self.theme["accent_soft"] if is_match else self.theme["surface_raised"],
                text_color=self.theme["accent_glow"] if is_match else self.theme["text_secondary"]
            )

    def _on_audio_device_selected(self, choice: str):
        self.hub.set_audio_device(choice)

    def _handle_power_click(self):
        try:
            self.hub.set_power(self.current_dev_id)
        except Exception as exc:
            import logging
            logging.getLogger("tapo").error(f"Error toggling power for {self.current_dev_id}: {exc}")
            if hasattr(self, "lbl_mon_meta") and self.lbl_mon_meta:
                self.lbl_mon_meta.configure(text=f"Power toggle error: {exc}")

    def _apply_mode(self, name: str):
        try:
            self.hub.apply_mode(self.current_dev_id, name)
        except Exception as exc:
            import logging
            logging.getLogger("tapo").error(f"Error applying mode {name} for {self.current_dev_id}: {exc}")

    def _apply_effect(self, name: str):
        try:
            self.hub.apply_effect(self.current_dev_id, name)
            self._update_effect_specific_controls(name)
        except Exception as exc:
            import logging
            logging.getLogger("tapo").error(f"Error applying effect {name} for {self.current_dev_id}: {exc}")

    def _handle_music_toggle(self):
        try:
            self.hub.toggle_music(self.current_dev_id)
        except Exception as exc:
            import logging
            logging.getLogger("tapo").error(f"Error toggling music for {self.current_dev_id}: {exc}")

    def _handle_audio_retry(self):
        """Restart audio capture for the selected strip(s), showing errors instead of hiding them."""
        try:
            self.hub.retry_audio_capture(self.current_dev_id)
            self.lbl_mon_meta.configure(text="Restarting audio capture…")
            self.gui_bpm_lbl.configure(text="Starting audio…", text_color=self.theme["text_secondary"])
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self.lbl_mon_meta.configure(text=f"Audio retry failed: {message[:100]}")
            self.gui_bpm_lbl.configure(text="Capture error", text_color="#fb7185")

    def _handle_screen_toggle(self):
        try:
            self.hub.toggle_screen(self.current_dev_id)
        except Exception as exc:
            import logging
            logging.getLogger("tapo").error(f"Error toggling screen sync for {self.current_dev_id}: {exc}")

    def _set_visual_style(self, style_name: str):
        # Choosing a visual style is an intent to hear/react now, not just save a preset.
        # Start audio output when it is off so a previous firmware effect doesn't linger.
        if self.current_dev_id == "all":
            target_contexts = list(self.hub.devices.values())
        elif self.current_dev_id in self.hub.devices:
            target_contexts = [self.hub.devices[self.current_dev_id]]
        else:
            target_contexts = []
        if target_contexts and not any(ctx.audio_sync.is_running() for ctx in target_contexts):
            self.hub.toggle_music(self.current_dev_id)
        self.hub.set_music_mode(self.current_dev_id, style_name)
        target_theme = get_theme_for_label(style_name)
        self._apply_theme(target_theme)
        self._update_style_card_selection(style_name)
        if hasattr(self, "lbl_transition_val") and self.lbl_transition_val:
            trans = MODE_TRANSITIONS.get(style_name.lower(), 0)
            trans_desc = "Flow" if trans > 0 else "Punchy"
            self.lbl_transition_val.configure(text=f"Transition: {trans}ms ({trans_desc})")

    def _on_eq_layout_change(self, choice: str):
        layout = "segmented" if "Segmented" in choice else "mirrored"
        targets = [self.hub.devices[self.current_dev_id]] if self.current_dev_id in self.hub.devices else list(self.hub.devices.values())
        for ctx in targets:
            if hasattr(ctx.audio_sync, "_styles"):
                spec = ctx.audio_sync._styles.get("spectrum")
                if spec and hasattr(spec, "set_params"):
                    spec.set_params(layout=layout)

    def _update_style_card_selection(self, current_style: str):
        c_clean = (current_style or "auto").strip().lower()
        for sid, sbtn in self.vstyle_buttons.items():
            is_act = (
                (sid == c_clean) or
                (sid == "auto" and c_clean in ("auto", "hybrid", "director")) or
                (sid == "spectrum" and c_clean in ("spectrum", "segmented", "segmented_vu", "staccato")) or
                (sid == "party" and c_clean in ("party", "club")) or
                (sid == "chill" and c_clean in ("chill", "lofi", "calm")) or
                (sid == "edm" and c_clean in ("edm", "drop", "edm_drop"))
            )
            if isinstance(sbtn, ctk.CTkButton):
                sbtn.configure(
                    fg_color=self.theme["accent"] if is_act else self.theme["surface_high"],
                    text_color="#ffffff" if is_act else self.theme["text_secondary"]
                )
            elif isinstance(sbtn, ctk.CTkFrame):
                sbtn.configure(
                    fg_color=self.theme["accent_soft"] if is_act else self.theme["surface_high"],
                    border_width=1 if is_act else 0,
                    border_color=self.theme["accent_glow"] if is_act else self.theme["border"]
                )

    def _toggle_accent(self, name: str):
        self.accent_states[name] = not self.accent_states.get(name, True)
        st = self.accent_states[name]
        btn = self.accent_buttons.get(name)
        if btn:
            btn.configure(
                fg_color=self.theme["accent_soft"] if st else self.theme["surface_high"],
                text_color=self.theme["accent_glow"] if st else self.theme["text_muted"]
            )
        self.hub.set_accent(self.current_dev_id, name, st)

    def _on_speed_slide(self, val: float):
        v = round(float(val), 1)
        self.lbl_speed_val.configure(text=f"{v:.1f}x")
        self.style_speed = v
        self.hub.set_style_params(self.current_dev_id, speed=v)

    def _on_intensity_slide(self, val: float):
        v = round(float(val), 1)
        self.lbl_intensity_val.configure(text=f"{v:.1f}x")
        self.style_intensity = v
        self.hub.set_style_params(self.current_dev_id, intensity=v)

    def _on_bright_cap_slide(self, val: float):
        b = int(val)
        self.lbl_bright_cap_val.configure(text=f"{b}%")
        self.hub.set_style_params(self.current_dev_id, brightness_cap=float(b))

    def _on_palette_mode_selected(self, choice: str):
        if "Album Art" in choice:
            mode = "album_art"
        elif "Fixed" in choice:
            mode = "fixed"
        else:
            mode = "auto"
        self.style_palette_mode = mode
        self.hub.set_style_params(self.current_dev_id, palette_mode=mode)

    def _toggle_click_test(self):
        self._click_test_active = not getattr(self, "_click_test_active", False)
        if self.btn_click_test:
            if self._click_test_active:
                self.btn_click_test.configure(text="⏹ Stop Flash", text_color="#f43f5e")
                self._run_click_test_pulse()
            else:
                self.btn_click_test.configure(text="🎯 Click-Test Flash", text_color="#10b981")

    def _run_click_test_pulse(self):
        if not getattr(self, "_click_test_active", False):
            return
        try:
            import winsound
            winsound.Beep(1200, 25)
        except Exception:
            pass
        self._click_test_timer = self.app.after(500, self._run_click_test_pulse)

    def _on_audio_sensitivity_change(self, val: float):
        v = round(float(val), 1)
        if self.lbl_sens_val:
            self.lbl_sens_val.configure(text=f"{v:.1f}x")
        self.hub.set_audio_sensitivity(self.current_dev_id, v)

    def _on_lookahead_slide(self, val: float):
        ms = int(val)
        if self.lbl_lookahead_val:
            self.lbl_lookahead_val.configure(text=f"{ms}ms")
        self.hub.set_audio_lookahead(self.current_dev_id, ms)

    def _handle_tap_sync(self):
        now = time.monotonic()
        self._tap_times.append(now)

        if self._tap_timer_id:
            self.app.after_cancel(self._tap_timer_id)

        count = len(self._tap_times)
        if count < 4:
            if self.btn_tap_sync:
                self.btn_tap_sync.configure(text=f"🎯 {count}/4", text_color=self.theme["accent_glow"])
            self._tap_timer_id = self.app.after(3500, self._reset_tap_sync)
        else:
            diffs = [self._tap_times[i] - self._tap_times[i - 1] for i in range(1, len(self._tap_times))]
            avg_int = sum(diffs) / len(diffs)

            calibrated = 45
            if 0.25 <= avg_int <= 1.2:
                calibrated = min(120, max(20, int(round((avg_int * 80.0) / 5.0) * 5)))

            if self.gui_lookahead_slider:
                self.gui_lookahead_slider.set(calibrated)
            if self.lbl_lookahead_val:
                self.lbl_lookahead_val.configure(text=f"{calibrated}ms")
            self.hub.set_audio_lookahead(self.current_dev_id, calibrated)

            if self.btn_tap_sync:
                self.btn_tap_sync.configure(text="✅ Done", text_color="#10b981")
            self._tap_times = []
            self.app.after(2500, self._reset_tap_sync)

    def _reset_tap_sync(self):
        self._tap_times = []
        if self.btn_tap_sync:
            self.btn_tap_sync.configure(text="🎯 Tap", text_color="#10b981")

    def _show_picker(self):
        if self.active_picker:
            return
        try:
            self.content_area.pack_forget()
        except Exception:
            pass
        self.active_picker = ModernColorPicker(
            self.main_column, on_apply=self._handle_picker_apply, on_cancel=self._hide_picker
        )
        self.active_picker.pack(fill="both", expand=True, padx=2, pady=(0, 2))

    def _handle_picker_apply(self, h, s, v):
        self.hub.apply_custom_color(self.current_dev_id, h, s, v)
        self._hide_picker()

    def _hide_picker(self):
        if self.active_picker:
            self.active_picker.pack_forget()
            self.active_picker.destroy()
            self.active_picker = None
        try:
            self.content_area.pack(fill="both", expand=True)
        except Exception:
            pass

    def hide_window(self):
        """Hide the desktop window without stopping the tray-resident app."""
        try:
            if self.app.winfo_viewable():
                if getattr(self, "window_mode", "normal") == "tray":
                    self._saved_tray_geometry = self.app.geometry()
                else:
                    self._saved_normal_geometry = self.app.geometry()
            self.app.withdraw()
        except Exception:
            pass

    def pop_out(self):
        """Pop out of system tray into full normal desktop window with Alt+Tab and taskbar presence."""
        try:
            if self.app.winfo_viewable() and getattr(self, "window_mode", "normal") == "tray":
                self._saved_tray_geometry = self.app.geometry()
        except Exception:
            pass

        self.window_mode = "normal"
        self.app.title("Summer — Light Control Hub")

        try:
            self.app.withdraw()
            self.app.overrideredirect(False)
        except Exception:
            pass

        if hasattr(self, "tray_workspace"):
            self.tray_workspace.pack_forget()
        if hasattr(self, "workspace"):
            self.workspace.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        if hasattr(self, "status_bar"):
            self.status_bar.pack(fill="x", side="bottom")

        sw, sh = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
        w, h, x, y, min_w, min_h = responsive_window_geometry(sw, sh)
        self.app.minsize(min_w, min_h)

        if self._saved_normal_geometry:
            self.app.geometry(self._saved_normal_geometry)
        else:
            self.app.geometry(f"{w}x{h}+{x}+{y}")
            self._saved_normal_geometry = f"{w}x{h}+{x}+{y}"

        if hasattr(self, "header"):
            try:
                self.header.pack_configure(padx=22)
            except Exception:
                pass
        if hasattr(self, "btn_top_power"):
            self.btn_top_power.configure(text="⏻  Power", width=88, height=36)
        if hasattr(self, "btn_mode_toggle"):
            self.btn_mode_toggle.configure(text="⤡ Mini Tray", width=94, height=36)
        if hasattr(self, "btn_hide"):
            self.btn_hide.configure(text="✕", width=36, height=36)
        if hasattr(self, "header_title"):
            self.header_title.configure(text="Summer  /  Light Control", font=ctk.CTkFont(size=20, weight="bold"))

        self.app.deiconify()
        self.app.lift()
        try:
            self.app.focus_force()
        except Exception:
            pass
        make_window_stay_in_taskbar(self.app)
        self._sync_view_to_device()
        self._on_window_configure()

    def dock_to_tray(self):
        """Dock from normal window into compact borderless system tray flyout mode."""
        try:
            if self.app.winfo_viewable() and getattr(self, "window_mode", "normal") == "normal":
                self._saved_normal_geometry = self.app.geometry()
        except Exception:
            pass

        self.window_mode = "tray"
        self.app.title("Summer — Tray Quick Hub")

        try:
            self.app.withdraw()
            self.app.overrideredirect(True)
        except Exception:
            pass

        if hasattr(self, "workspace"):
            self.workspace.pack_forget()
        if hasattr(self, "status_bar"):
            self.status_bar.pack_forget()
        if hasattr(self, "tray_workspace"):
            self.tray_workspace.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        sw, sh = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
        w, h, x, y, min_w, min_h = tray_window_geometry(sw, sh)
        self.app.minsize(min_w, min_h)

        if self._saved_tray_geometry:
            self.app.geometry(self._saved_tray_geometry)
        else:
            self.app.geometry(f"{w}x{h}+{x}+{y}")
            self._saved_tray_geometry = f"{w}x{h}+{x}+{y}"

        if hasattr(self, "header"):
            try:
                self.header.pack_configure(padx=12)
            except Exception:
                pass
        if hasattr(self, "btn_top_power"):
            self.btn_top_power.configure(text="⏻", width=34, height=34)
        if hasattr(self, "btn_mode_toggle"):
            self.btn_mode_toggle.configure(text="⤢ Pop Out", width=82, height=34)
        if hasattr(self, "btn_hide"):
            self.btn_hide.configure(text="✕", width=34, height=34)
        if hasattr(self, "header_title"):
            self.header_title.configure(text="Summer  ·  Quick Hub", font=ctk.CTkFont(size=15, weight="bold"))

        self.app.deiconify()
        self.app.lift()
        try:
            self.app.focus_force()
        except Exception:
            pass
        make_window_stay_in_taskbar(self.app)
        self._sync_view_to_device()

    def toggle_window_mode(self):
        """Toggle between tray mini mode and normal popped-out window."""
        if getattr(self, "window_mode", "normal") == "tray":
            self.pop_out()
        else:
            self.dock_to_tray()

    def toggle_tray_window(self):
        """Toggle system tray mini window: hide if open in tray mode, else show in tray mode."""
        try:
            is_visible = self.app.winfo_viewable()
        except Exception:
            is_visible = False

        if is_visible and getattr(self, "window_mode", "normal") == "tray":
            self.hide_window()
        else:
            if getattr(self, "window_mode", "normal") != "tray":
                self.dock_to_tray()
            else:
                self.show_window()

    def show_window(self):
        """Show window in its current mode (tray or normal)."""
        if getattr(self, "window_mode", "normal") == "tray":
            try:
                self.app.withdraw()
                self.app.overrideredirect(True)
            except Exception:
                pass
            if not getattr(self, "_has_positioned", False):
                sw, sh = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
                w, h, x, y, min_w, min_h = tray_window_geometry(sw, sh)
                self.app.minsize(min_w, min_h)
                self.app.geometry(f"{w}x{h}+{x}+{y}")
                self._has_positioned = True
            self.app.deiconify()
            self.app.lift()
            try:
                self.app.focus_force()
            except Exception:
                pass
            make_window_stay_in_taskbar(self.app)
            self._sync_view_to_device()
        else:
            try:
                self.app.withdraw()
                self.app.overrideredirect(False)
            except Exception:
                pass
            if not getattr(self, "_has_positioned", False):
                sw, sh = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
                width, height, x, y, min_w, min_h = responsive_window_geometry(sw, sh)
                self.app.minsize(min_w, min_h)
                self.app.geometry(f"{width}x{height}+{x}+{y}")
                self._has_positioned = True
            self.app.deiconify()
            self.app.lift()
            try:
                self.app.focus_force()
            except Exception:
                pass
            make_window_stay_in_taskbar(self.app)
            self._on_window_configure()
            self._sync_view_to_device()

    def run(self):
        self.app.mainloop()

    def quit(self):
        try:
            if hasattr(self, "hub") and self.hub:
                self.hub.shutdown()
        except Exception:
            pass
        if callable(self.on_quit):
            try:
                self.on_quit()
            except Exception:
                pass
        try:
            self.app.destroy()
        except Exception:
            pass