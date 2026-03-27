"""
DisplayManager – steuert die HUB75 LED-Matrix via rpi-rgb-led-matrix.
Läuft in einem eigenen Thread; Kommandos werden via send_command() übergeben.
"""
import os
import threading
import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from rgbmatrix import RGBMatrix, graphics
from animations import ANIMATIONS

SYSTEM_FONTS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]

FONTS_DIR = os.path.join(os.path.dirname(__file__), 'fonts')

FONT_FILES = {
    'tiny':   '4x6.bdf',
    'small':  '5x8.bdf',
    'medium': '7x13.bdf',
    'large':  '10x20.bdf',
    'huge':   '9x15B.bdf',
}


def parse_color(val):
    """Akzeptiert '#RRGGBB', [r,g,b] oder (r,g,b). Fallback: Weiss."""
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return graphics.Color(int(val[0]), int(val[1]), int(val[2]))
    if isinstance(val, str) and val.startswith('#') and len(val) == 7:
        return graphics.Color(
            int(val[1:3], 16),
            int(val[3:5], 16),
            int(val[5:7], 16),
        )
    return graphics.Color(255, 255, 255)


class DisplayManager:

    def __init__(self, options):
        self._matrix  = RGBMatrix(options=options)
        self._canvas  = self._matrix.CreateFrameCanvas()
        self._width   = self._matrix.width
        self._height  = self._matrix.height

        self._cmd_lock    = threading.Lock()
        self._current_cmd = None
        self._stop_evt    = threading.Event()
        self._wake_evt    = threading.Event()
        self._status      = {'type': 'idle'}

        self._font_cache  = {}

        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def send_command(self, cmd: dict):
        """Neues Kommando einreihen; aktuelles wird sofort unterbrochen."""
        with self._cmd_lock:
            self._current_cmd = cmd
        self._stop_evt.set()
        self._wake_evt.set()

    def set_brightness(self, value: int):
        self._matrix.brightness = max(0, min(100, int(value)))

    def get_status(self) -> dict:
        with self._cmd_lock:
            return dict(self._status)

    # ------------------------------------------------------------------
    # Interner Dispatch-Loop
    # ------------------------------------------------------------------

    def _should_stop(self) -> bool:
        return self._stop_evt.is_set()

    def _loop(self):
        while True:
            self._wake_evt.wait()
            self._wake_evt.clear()
            self._stop_evt.clear()

            with self._cmd_lock:
                cmd = self._current_cmd
            if not cmd:
                continue

            t = cmd.get('type', '')
            with self._cmd_lock:
                self._status = {'type': t, 'text': cmd.get('text', '')}

            try:
                if   t == 'text':      self._do_text(cmd)
                elif t == 'image':     self._do_image(cmd)
                elif t == 'gif':       self._do_gif(cmd)
                elif t == 'animation': self._do_animation(cmd)
                elif t == 'clear':     self._do_clear()
                else:
                    print(f'Unbekannter Typ: {t}')
            except Exception as e:
                print(f'Display-Fehler [{t}]: {e}')
                self._do_clear()

            with self._cmd_lock:
                self._status = {'type': 'idle'}

    # ------------------------------------------------------------------
    # Display-Operationen
    # ------------------------------------------------------------------

    def _load_font(self, name: str):
        if name in self._font_cache:
            return self._font_cache[name]
        filename = FONT_FILES.get(name, FONT_FILES['medium'])
        path = os.path.join(FONTS_DIR, filename)
        if not os.path.exists(path):
            # Fallback auf medium
            path = os.path.join(FONTS_DIR, FONT_FILES['medium'])
        f = graphics.Font()
        f.LoadFont(path)
        self._font_cache[name] = f
        return f

    def _do_clear(self):
        self._canvas.Clear()
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def _find_system_font(self):
        for p in SYSTEM_FONTS:
            if os.path.exists(p):
                return p
        return None

    def _fit_font_size(self, font_path, text, max_w, max_h):
        """Grösste Schriftgrösse bei der `text` in max_w×max_h passt (multiline-fähig)."""
        lo, hi, best = 8, max_h, 8
        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        while lo <= hi:
            mid = (lo + hi) // 2
            try:
                font = ImageFont.truetype(font_path, mid)
                bb   = dummy.multiline_textbbox((0, 0), text, font=font)
                if bb[2] - bb[0] <= max_w and bb[3] - bb[1] <= max_h:
                    best = mid
                    lo   = mid + 1
                else:
                    hi = mid - 1
            except Exception:
                break
        return best

    def _do_text(self, cmd: dict):
        text     = str(cmd.get('text', ''))
        color    = parse_color(cmd.get('color', '#FFFFFF'))
        scroll   = bool(cmd.get('scroll', False))
        speed    = float(cmd.get('speed', 30))    # Pixel pro Sekunde
        duration = float(cmd.get('duration', 0))  # 0 = dauerhaft

        # Statischer Text: PIL-Rendering mit optionaler Grösse und Zeilenumbrüchen
        if not scroll:
            self._do_text_autofit(text, color, duration,
                                  x=cmd.get('x'), y=cmd.get('y'),
                                  size=cmd.get('size'))
            return

        # Scrollender Text: hzeller BDF-Font
        font   = self._load_font(cmd.get('font', 'medium'))
        text_w = sum(font.CharacterWidth(ord(c)) for c in text if ord(c) < 256)
        y = int(cmd.get('y', self._height // 2 + font.height // 2))

        if scroll:
            fps   = 30
            delay = 1.0 / fps
            pf    = speed / fps   # Pixel pro Frame
            start = time.time()
            offset = 0.0

            while not self._should_stop():
                if duration > 0 and time.time() - start > duration:
                    break
                x_pos = int(self._width - offset)
                self._canvas.Clear()
                graphics.DrawText(self._canvas, font, x_pos, y, color, text)
                self._canvas = self._matrix.SwapOnVSync(self._canvas)
                offset += pf
                if x_pos + text_w < 0:
                    offset = 0.0
                time.sleep(delay)
        # (statischer Text wird vor dem Scroll-Block via _do_text_autofit gerendert)

    def _do_text_autofit(self, text, color, duration, x=None, y=None, size=None):
        """Text rendern: size=None → automatisch maximale Grösse, sonst feste Grösse.
        Zeilenumbrüche via \\n im text-Parameter werden unterstützt."""
        font_path = self._find_system_font()
        if font_path:
            if size is None:
                size = self._fit_font_size(font_path, text,
                                           self._width - 4, self._height - 4)
            font = ImageFont.truetype(font_path, int(size))
        else:
            font = ImageFont.load_default()

        img  = Image.new('RGB', (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        bb   = draw.multiline_textbbox((0, 0), text, font=font, align='center')
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        px = int(x) if x is not None else (self._width  - tw) // 2 - bb[0]
        py = int(y) if y is not None else (self._height - th) // 2 - bb[1]
        draw.multiline_text((px, py), text, fill=(color.red, color.green, color.blue),
                            font=font, align='center')
        self._matrix.SetImage(img)
        self._hold(duration)

    def _do_animation(self, cmd: dict):
        """Eingebaute Animation abspielen."""
        name     = cmd.get('name', '')
        duration = float(cmd.get('duration', 0))
        anim_fn  = ANIMATIONS.get(name)
        if not anim_fn:
            print(f'Unbekannte Animation: "{name}". Verfügbar: {list(ANIMATIONS)}')
            return

        start = __import__('time').time()

        def stop():
            if self._should_stop():
                return True
            if duration > 0 and __import__('time').time() - start > duration:
                return True
            return False

        anim_fn(self._matrix, self._width, self._height, stop)
        if not self._should_stop():
            self._do_clear()

    def _do_image(self, cmd: dict):
        img = self._fetch_image(cmd)
        if img is None:
            return
        img = img.convert('RGB').resize((self._width, self._height), Image.LANCZOS)
        self._matrix.SetImage(img)
        self._hold(float(cmd.get('duration', 10)))

    def _do_gif(self, cmd: dict):
        img = self._fetch_image(cmd)
        if img is None:
            return

        frames, delays = [], []
        try:
            while True:
                frame = img.copy().convert('RGB').resize(
                    (self._width, self._height), Image.LANCZOS)
                frames.append(frame)
                delays.append(img.info.get('duration', 100) / 1000.0)
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        if not frames:
            return

        loops    = int(cmd.get('loops', 0))    # 0 = endlos
        duration = float(cmd.get('duration', 0))
        start    = time.time()
        count    = 0

        while not self._should_stop():
            for frame, delay in zip(frames, delays):
                if self._should_stop():
                    return
                if duration > 0 and time.time() - start > duration:
                    return
                self._matrix.SetImage(frame)
                time.sleep(delay)
            count += 1
            if loops > 0 and count >= loops:
                break

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _hold(self, duration: float):
        """Hält den aktuellen Frame. 0 = dauerhaft, >0 = Sekunden dann clear."""
        if duration > 0:
            end = time.time() + duration
            while not self._should_stop() and time.time() < end:
                time.sleep(0.05)
            if not self._should_stop():
                self._do_clear()
        else:
            while not self._should_stop():
                time.sleep(0.1)

    def _fetch_image(self, cmd: dict):
        url  = cmd.get('url')
        data = cmd.get('data')
        try:
            if url:
                resp = requests.get(url, timeout=8)
                resp.raise_for_status()
                return Image.open(BytesIO(resp.content))
            if data:
                import base64
                return Image.open(BytesIO(base64.b64decode(data)))
        except Exception as e:
            print(f'Bild-Fehler: {e}')
        return None
