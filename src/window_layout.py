"""Pure helpers for responsive desktop window sizing."""


def responsive_window_geometry(
    screen_width: int, screen_height: int
) -> tuple[int, int, int, int, int, int]:
    """Return width, height, x, y, min_width and min_height for the current screen.

    The initial window uses a proportion of the available display area. Minimum
    dimensions also shrink on small displays, while the native window remains
    user-resizable after it opens.
    """
    sw = max(320, int(screen_width))
    sh = max(320, int(screen_height))
    margin_x = max(12, min(28, int(sw * 0.018)))
    margin_y = max(18, min(36, int(sh * 0.035)))
    available_w = max(280, sw - 2 * margin_x)
    available_h = max(300, sh - 2 * margin_y)
    min_w = min(540, available_w)
    min_h = min(500, available_h)
    # Popped out desktop window sized to exactly 3/4th (75%) of previous footprint
    width = min(available_w, max(min_w, int(sw * 0.86 * 0.75)))
    height = min(available_h, max(min_h, int(sh * 0.88 * 0.75)))
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    return width, height, x, y, min_w, min_h


def responsive_grid_columns(width: int, max_columns: int = 3) -> int:
    """Choose a readable grid column count from available pixels and a per-grid cap."""
    available = max(1, int(width))
    cap = max(1, min(3, int(max_columns)))
    fitted = 1 if available < 470 else (2 if available < 820 else 3)
    return min(cap, fitted)


def tray_window_geometry(
    screen_width: int, screen_height: int
) -> tuple[int, int, int, int, int, int]:
    """Return width, height, x, y, min_width and min_height for the compact tray flyout window.

    Positioned in the bottom-right corner near the Windows notification area / system tray.
    """
    sw = max(320, int(screen_width))
    sh = max(320, int(screen_height))

    # Sleek compact flyout dimensions (similar to modern Windows quick settings / Spotify mini)
    width = min(420, max(360, int(sw * 0.24)))
    height = min(680, max(520, int(sh * 0.65)))

    margin_right = 16
    margin_bottom = 54  # Allowance for taskbar height

    min_w = min(360, sw)
    min_h = min(500, sh)

    width = min(sw, max(min_w, width))
    height = min(sh, max(min_h, height))

    x = max(0, sw - width - margin_right)
    y = max(0, sh - height - margin_bottom)
    return width, height, x, y, min_w, min_h
