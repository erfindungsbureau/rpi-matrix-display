"""
Eingebaute LED-Matrix-Animationen.
Jede Funktion: anim(matrix, width, height, stop_fn) → None
stop_fn() gibt True zurück wenn abgebrochen werden soll.
"""
import time
import math
import random
import colorsys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

FPS   = 30
DELAY = 1.0 / FPS

SYSTEM_FONTS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]


# -----------------------------------------------------------------------
# Hilfsfunktionen
# -----------------------------------------------------------------------

def _find_font():
    import os
    for p in SYSTEM_FONTS:
        if os.path.exists(p):
            return p
    return None


def _show(matrix, arr):
    """numpy uint8 RGB-Array (H,W,3) → Matrix."""
    matrix.SetImage(Image.fromarray(arr, 'RGB'))


def _hsv_to_rgb(h):
    """Numpy-Array von Hue-Werten [0,1] → uint8 RGB-Array (..., 3)."""
    h6 = (h * 6.0) % 6.0
    i  = h6.astype(np.int32)
    f  = h6 - i
    q  = 1.0 - f    # p=0, v=1
    t  = f

    r = np.select([i==0, i==1, i==2, i==3, i==4], [1., q, 0., 0., t], default=1.)
    g = np.select([i==0, i==1, i==2, i==3, i==4], [t,  1., 1., q,  0.], default=0.)
    b = np.select([i==0, i==1, i==2, i==3, i==4], [0., 0., t,  1., 1.], default=q)

    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def _fit_font_size(font_path, text, max_w, max_h):
    """Grösste Schriftgrösse finden bei der `text` in max_w × max_h passt."""
    lo, hi, best = 8, max_h, 8
    dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            font = ImageFont.truetype(font_path, mid)
            bb   = dummy.textbbox((0, 0), text, font=font)
            if bb[2] - bb[0] <= max_w and bb[3] - bb[1] <= max_h:
                best = mid
                lo   = mid + 1
            else:
                hi = mid - 1
        except Exception:
            break
    return best


# -----------------------------------------------------------------------
# Animationen
# -----------------------------------------------------------------------

def rainbow(matrix, width, height, stop):
    """Horizontaler Regenbogen-Gradient der vorwärts fliesst."""
    x = np.linspace(0, 1, width)
    t = 0.0
    while not stop():
        hue   = np.tile(((x + t) % 1.0)[np.newaxis, :], (height, 1))
        frame = _hsv_to_rgb(hue)
        _show(matrix, frame)
        t = (t + 0.015) % 1.0
        time.sleep(DELAY)


def plasma(matrix, width, height, stop):
    """Sine-Wave Plasma-Effekt mit Regenbogenfarben."""
    xs = np.linspace(0, 4 * math.pi, width)
    ys = np.linspace(0, 4 * math.pi, height)
    xg, yg = np.meshgrid(xs, ys)
    dg = np.sqrt(xg ** 2 + yg ** 2)
    t  = 0.0
    while not stop():
        v   = (np.sin(xg + t) +
               np.sin(yg + t * 0.7) +
               np.sin((xg + yg) / 2 + t * 1.3) +
               np.sin(dg / 2 + t)) / 4.0
        hue = (v + 1.0) / 2.0
        _show(matrix, _hsv_to_rgb(hue))
        t += 0.05
        time.sleep(DELAY)


def fire(matrix, width, height, stop):
    """Feuer-Simulation, aufsteigende Flammen."""
    # Palette: schwarz → rot → orange → gelb → weiss
    idx = np.arange(256) / 255.0
    pal = np.stack([
        np.clip(idx * 3,     0, 1),
        np.clip(idx * 3 - 1, 0, 1),
        np.clip(idx * 3 - 2, 0, 1),
    ], axis=-1)
    pal = (pal * 255).astype(np.uint8)

    buf = np.zeros((height + 2, width), dtype=np.float32)
    while not stop():
        buf[height, :]     = np.random.uniform(0.6, 1.0, width)
        buf[height + 1, :] = buf[height, :]
        for y in range(height - 1, -1, -1):
            buf[y] = (np.roll(buf[y+1], -1) + buf[y+1] +
                      np.roll(buf[y+1],  1) + buf[y+2]) / 4.05
        raw   = (np.clip(buf[:height], 0, 1) * 255).astype(np.uint8)
        frame = pal[raw]
        _show(matrix, frame)
        time.sleep(DELAY)


def starfield(matrix, width, height, stop):
    """3D-Sternenfeld – Sterne fliegen auf den Betrachter zu."""
    N  = 250
    cx, cy = width / 2.0, height / 2.0
    stars = np.column_stack([
        np.random.uniform(-1, 1, N),
        np.random.uniform(-1, 1, N),
        np.random.uniform(0.01, 1.0, N),
    ])
    while not stop():
        frame        = np.zeros((height, width, 3), dtype=np.uint8)
        stars[:, 2] -= 0.018
        dead          = stars[:, 2] <= 0
        stars[dead]   = np.column_stack([
            np.random.uniform(-1, 1, dead.sum()),
            np.random.uniform(-1, 1, dead.sum()),
            np.ones(dead.sum()),
        ])
        sx  = (stars[:, 0] / stars[:, 2] * cx + cx).astype(int)
        sy  = (stars[:, 1] / stars[:, 2] * cy + cy).astype(int)
        bri = ((1 - stars[:, 2]) * 255).astype(np.uint8)
        ok  = (sx >= 0) & (sx < width) & (sy >= 0) & (sy < height)
        frame[sy[ok], sx[ok]] = bri[ok, np.newaxis]
        _show(matrix, frame)
        time.sleep(DELAY)


def matrix_rain(matrix, width, height, stop):
    """Matrix-Regen: fallende grüne Zeichen."""
    font_path = _find_font()
    char_h    = 10
    char_w    = 6
    try:
        font = ImageFont.truetype(font_path, char_h) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    cols   = width // char_w
    drops  = np.random.randint(-height, 0, cols).astype(float)
    speeds = np.random.randint(1, 4, cols).astype(float)
    chars  = list('01アイウエオカキクサシスセタチツテトナニ')
    frame  = np.zeros((height, width, 3), dtype=np.uint8)

    while not stop():
        frame = (frame * 0.82).astype(np.uint8)
        img   = Image.fromarray(frame, 'RGB')
        draw  = ImageDraw.Draw(img)
        for c in range(cols):
            y = int(drops[c])
            if 0 <= y < height:
                ch  = random.choice(chars)
                x   = c * char_w
                draw.text((x, y), ch, fill=(160, 255, 160), font=font)
            drops[c] += speeds[c]
            if drops[c] > height + char_h:
                drops[c]  = -random.randint(char_h, height)
                speeds[c] = random.randint(1, 4)
        frame = np.array(img)
        matrix.SetImage(img)
        time.sleep(DELAY)


def clock(matrix, width, height, stop):
    """Grosse Live-Uhr (HH:MM), füllt das Display."""
    font_path = _find_font()
    if not font_path:
        return
    size  = _fit_font_size(font_path, '00:00', width - 4, height - 4)
    font  = ImageFont.truetype(font_path, size)
    last  = ''
    while not stop():
        now = datetime.now().strftime('%H:%M')
        if now != last:
            img  = Image.new('RGB', (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            bb   = draw.textbbox((0, 0), now, font=font)
            x    = (width  - (bb[2] - bb[0])) // 2 - bb[0]
            y    = (height - (bb[3] - bb[1])) // 2 - bb[1]
            draw.text((x, y), now, fill=(255, 200, 0), font=font)
            matrix.SetImage(img)
            last = now
        time.sleep(0.5)


def bouncing_ball(matrix, width, height, stop):
    """Leuchtender Ball prallt mit Farbspur von den Wänden ab."""
    bx, by = float(width // 2), float(height // 2)
    vx     = random.choice([-4.0, -3.0, 3.0, 4.0])
    vy     = random.choice([-2.5, -1.5, 1.5, 2.5])
    hue    = 0.0
    frame  = np.zeros((height, width, 3), dtype=np.uint8)
    radius = 4

    while not stop():
        frame = (frame * 0.87).astype(np.uint8)
        bx   += vx
        by   += vy
        if bx <= radius or bx >= width - 1 - radius:
            vx   = -vx
            hue  = (hue + 0.12) % 1.0
            bx   = max(float(radius), min(float(width  - 1 - radius), bx))
        if by <= radius or by >= height - 1 - radius:
            vy   = -vy
            hue  = (hue + 0.12) % 1.0
            by   = max(float(radius), min(float(height - 1 - radius), by))
        r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                dist = math.sqrt(dx*dx + dy*dy)
                if dist <= radius:
                    nx, ny = int(bx) + dx, int(by) + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        bright = max(0.0, 1.0 - dist / radius)
                        frame[ny, nx] = [int(r*bright), int(g*bright), int(b*bright)]
        _show(matrix, frame)
        time.sleep(DELAY)


def color_pulse(matrix, width, height, stop):
    """Sanft pulsierende Vollfarbe, durchläuft den Regenbogen."""
    t = 0.0
    while not stop():
        hue   = (t * 0.3) % 1.0
        val   = (math.sin(t * math.pi) + 1) / 2 * 0.9 + 0.1
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, val)
        frame = np.full((height, width, 3),
                        [int(r*255), int(g*255), int(b*255)], dtype=np.uint8)
        _show(matrix, frame)
        t    += 0.04
        time.sleep(DELAY)


# -----------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------

ANIMATIONS = {
    'rainbow':       rainbow,
    'plasma':        plasma,
    'fire':          fire,
    'starfield':     starfield,
    'matrix_rain':   matrix_rain,
    'clock':         clock,
    'bouncing_ball': bouncing_ball,
    'color_pulse':   color_pulse,
}
