"""Generate Other Voices app icon — forking waveform design."""

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ICON_DIR = Path(__file__).parent


def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def smooth_line(draw, points, color, width):
    """Draw a smooth anti-aliased line through points using overlapping circles."""
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        dist = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(dist), 1)
        for s in range(steps + 1):
            t = s / steps
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            r = width / 2
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def gradient_line(draw, points, color_start, color_end, alpha_start, alpha_end, width):
    """Draw a smooth gradient-colored line."""
    total = len(points)
    for i in range(total - 1):
        t = i / max(total - 1, 1)
        color = lerp_color(color_start, color_end, t)
        alpha = int(alpha_start + (alpha_end - alpha_start) * t)
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        r = width / 2
        fill = (*color, alpha)
        dist = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(dist * 0.8), 1)
        for s in range(steps + 1):
            st = s / steps
            x = x1 + (x2 - x1) * st
            y = y1 + (y2 - y1) * st
            draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def draw_icon(size: int) -> Image.Image:
    # Render at 3x for smooth antialiasing
    s = size * 3
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background
    margin = int(s * 0.04)
    radius = int(s * 0.22)
    draw.rounded_rectangle(
        [margin, margin, s - margin, s - margin],
        radius=radius,
        fill=(24, 24, 30, 255),
    )

    cx, cy = s / 2, s / 2
    left_x = s * 0.14
    fork_x = s * 0.40
    right_x = s * 0.88
    line_w = max(4, s * 0.030)

    teal = (70, 215, 205)
    violet = (150, 105, 240)
    light = (195, 200, 215)

    # Unified wave: left_x → fork_x
    steps = 150
    unified = []
    for i in range(steps + 1):
        t = i / steps
        x = left_x + (fork_x - left_x) * t
        amp = s * 0.055 * (1.0 - t * 0.4)
        y = cy + amp * math.sin(t * 2.8 * math.pi)
        unified.append((x, y))

    gradient_line(draw, unified, light, teal, 220, 255, line_w)

    # Fork point
    fork_y = unified[-1][1]

    # Upper fork (teal): gently curves up with oscillation
    steps_f = 180
    upper = []
    for i in range(steps_f + 1):
        t = i / steps_f
        x = fork_x + (right_x - fork_x) * t
        # Smooth ease-out spread
        spread = s * 0.13 * (1 - (1 - t) ** 2)
        amp = s * 0.04 * (0.4 + t * 0.6)
        base_y = fork_y - spread
        y = base_y + amp * math.sin(t * 2.5 * math.pi + 0.3)
        upper.append((x, y))

    gradient_line(draw, upper, teal, (50, 230, 220), 255, 240, line_w)

    # Lower fork (violet): gently curves down with oscillation
    lower = []
    for i in range(steps_f + 1):
        t = i / steps_f
        x = fork_x + (right_x - fork_x) * t
        spread = s * 0.13 * (1 - (1 - t) ** 2)
        amp = s * 0.04 * (0.4 + t * 0.6)
        base_y = fork_y + spread
        y = base_y + amp * math.sin(t * 2.5 * math.pi + 0.3 + math.pi * 0.4)
        lower.append((x, y))

    gradient_line(draw, lower, violet, (170, 120, 255), 255, 240, line_w)

    # Tiny dot at fork point
    dot_r = line_w * 0.45
    draw.ellipse(
        [fork_x - dot_r, fork_y - dot_r, fork_x + dot_r, fork_y + dot_r],
        fill=(220, 225, 240, 180),
    )

    img = img.resize((size, size), Image.LANCZOS)
    return img


def create_icns():
    iconset = ICON_DIR / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)

    icon_specs = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    cache = {}
    for px, filename in icon_specs:
        if px not in cache:
            cache[px] = draw_icon(px)
        cache[px].save(str(iconset / filename), "PNG")

    icns_path = ICON_DIR / "AppIcon.icns"
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"iconutil error: {result.stderr}")
        return

    print(f"Generated: {icns_path}")
    cache[512].save(str(ICON_DIR / "icon_preview.png"), "PNG")
    print(f"Preview: {ICON_DIR / 'icon_preview.png'}")


if __name__ == "__main__":
    create_icns()
