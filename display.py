"""
DisplayManager – steuert die HUB75 LED-Matrix via rpi-rgb-led-matrix.
Läuft in einem eigenen Thread; Kommandos werden via send_command() übergeben.
"""
import os
import subprocess
import threading
import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from rgbmatrix import RGBMatrix, graphics
from animations import ANIMATIONS

FONT_STYLES = {
    'regular': [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ],
    'bold': [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    ],
    'italic': [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf',
    ],
    'bold-italic': [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf',
    ],
}

FONTS_DIR = os.path.join(os.path.dirname(__file__), 'fonts')

FONT_FILES = {
    'tiny':   '4x6.bdf',
    'small':  '5x8.bdf',
    'medium': '7x13.bdf',
    'large':  '10x20.bdf',
    'huge':   '9x15B.bdf',
}


def parse_color(val, default=(255, 255, 255)):
    """Akzeptiert '#RRGGBB', [r,g,b] oder (r,g,b). Gibt graphics.Color zurück."""
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return graphics.Color(int(val[0]), int(val[1]), int(val[2]))
    if isinstance(val, str) and val.startswith('#') and len(val) == 7:
        return graphics.Color(
            int(val[1:3], 16),
            int(val[3:5], 16),
            int(val[5:7], 16),
        )
    return graphics.Color(*default)


def parse_rgb(val, default=(0, 0, 0)):
    """Wie parse_color, gibt aber (r,g,b) Tupel zurück (für PIL)."""
    c = parse_color(val, default)
    return (c.red, c.green, c.blue)


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
            status = dict(self._status)
        status['system'] = self._system_info()
        return status

    def _system_info(self) -> dict:
        info = {}

        # CPU-Auslastung (1-Minuten-Durchschnitt)
        try:
            with open('/proc/loadavg') as f:
                load1 = float(f.read().split()[0])
            info['cpu_load_1min'] = load1
        except Exception:
            pass

        # CPU-Temperatur
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                info['cpu_temp_c'] = round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass

        # RPi Throttle-Status (Unterspannung, Taktdrosselung)
        try:
            out = subprocess.check_output(
                ['vcgencmd', 'get_throttled'], timeout=2,
                stderr=subprocess.DEVNULL
            ).decode().strip()
            # Format: "throttled=0x50005"
            val = int(out.split('=')[1], 16)
            BITS = {
                0x00001: 'undervoltage_now',
                0x00002: 'freq_capped_now',
                0x00004: 'throttled_now',
                0x00008: 'temp_limit_now',
                0x10000: 'undervoltage_occurred',
                0x20000: 'freq_capped_occurred',
                0x40000: 'throttled_occurred',
                0x80000: 'temp_limit_occurred',
            }
            warnings = [name for bit, name in BITS.items() if val & bit]
            info['throttled_raw'] = hex(val)
            info['warnings'] = warnings
            info['power_ok'] = not any('undervoltage' in w for w in warnings)
        except Exception:
            pass

        return info

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
                elif t == 'split':     self._do_split(cmd)
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

    def _find_system_font(self, style='bold'):
        """Gibt den Pfad zur ersten vorhandenen Systemschrift für den gewünschten Stil zurück."""
        paths = FONT_STYLES.get(style, FONT_STYLES['bold'])
        for p in paths:
            if os.path.exists(p):
                return p
        # Fallback: irgendeine verfügbare Schrift
        for style_paths in FONT_STYLES.values():
            for p in style_paths:
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
        bgcolor  = parse_rgb(cmd.get('bgcolor', '#000000'), default=(0, 0, 0))
        style    = cmd.get('style', 'bold')
        scroll   = bool(cmd.get('scroll', False))
        speed    = float(cmd.get('speed', 30))
        duration = float(cmd.get('duration', 0))
        size     = cmd.get('size')

        if not scroll:
            self._do_text_static(text, color, bgcolor, style, duration,
                                 x=cmd.get('x'), y=cmd.get('y'), size=size)
            return

        # Scrollender Text mit PIL (freie Grösse/Stil/Farbe)
        if size is not None:
            self._do_text_scroll_pil(text, color, bgcolor, style, speed, duration, int(size))
            return

        # Scrollender Text: BDF-Font (Fallback ohne size-Angabe)
        font   = self._load_font(cmd.get('font', 'medium'))
        text_w = sum(font.CharacterWidth(ord(c)) for c in text if ord(c) < 256)
        y      = int(cmd.get('y', self._height // 2 + font.height // 2))
        fps    = 30
        delay  = 1.0 / fps
        pf     = speed / fps
        start  = time.time()
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

    def _do_text_static(self, text, color, bgcolor, style, duration,
                        x=None, y=None, size=None):
        """Statischer Text: auto-fit oder feste Grösse, Zeilenumbrüche via \\n."""
        font_path = self._find_system_font(style)
        if font_path:
            if size is None:
                size = self._fit_font_size(font_path, text,
                                           self._width - 4, self._height - 4)
            font = ImageFont.truetype(font_path, int(size))
        else:
            font = ImageFont.load_default()

        img  = Image.new('RGB', (self._width, self._height), bgcolor)
        draw = ImageDraw.Draw(img)
        bb   = draw.multiline_textbbox((0, 0), text, font=font, align='center')
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        px = int(x) if x is not None else (self._width  - tw) // 2 - bb[0]
        py = int(y) if y is not None else (self._height - th) // 2 - bb[1]
        draw.multiline_text((px, py), text,
                            fill=(color.red, color.green, color.blue),
                            font=font, align='center')
        self._matrix.SetImage(img)
        self._hold(duration)

    def _do_text_scroll_pil(self, text, color, bgcolor, style, speed, duration, size):
        """Scrollender Text mit PIL – unterstützt freie Grösse, Stil und Hintergrundfarbe."""
        font_path = self._find_system_font(style)
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        bb     = dummy.textbbox((0, 0), text, font=font)
        text_w = bb[2] - bb[0]
        text_h = bb[3] - bb[1]
        py     = (self._height - text_h) // 2 - bb[1]

        # Text auf eigenes Image rendern
        txt_img = Image.new('RGB', (text_w, self._height), bgcolor)
        ImageDraw.Draw(txt_img).text(
            (-bb[0], py), text,
            fill=(color.red, color.green, color.blue), font=font
        )

        fps    = 30
        delay  = 1.0 / fps
        pf     = speed / fps
        start  = time.time()
        offset = 0.0

        while not self._should_stop():
            if duration > 0 and time.time() - start > duration:
                break
            frame = Image.new('RGB', (self._width, self._height), bgcolor)
            x_pos = int(self._width - offset)
            frame.paste(txt_img, (x_pos, 0))
            self._matrix.SetImage(frame)
            offset += pf
            if x_pos + text_w < 0:
                offset = 0.0
            time.sleep(delay)

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

    def _do_split(self, cmd: dict):
        """Zwei statische Zeilen oben + scrollender Ticker unten."""
        lines         = cmd.get('lines', [])
        color         = parse_rgb(cmd.get('color', '#FFFFFF'), default=(255, 255, 255))
        bgcolor       = parse_rgb(cmd.get('bgcolor', '#000000'), default=(0, 0, 0))
        ticker        = str(cmd.get('ticker', ''))
        ticker_color  = parse_rgb(cmd.get('ticker_color', '#FFFF00'), default=(255, 255, 0))
        speed         = float(cmd.get('speed', 30))
        duration      = float(cmd.get('duration', 0))
        style         = cmd.get('style', 'bold')

        # Bereiche: obere 75% fuer statische Zeilen, untere 25% fuer Ticker
        ticker_h  = max(16, self._height // 5)
        static_h  = self._height - ticker_h

        # Font fuer statische Zeilen (auto-fit)
        font_path = self._find_system_font(style)
        joined    = '\n'.join(lines) if lines else ''
        if font_path and joined:
            size     = self._fit_font_size(font_path, joined, self._width - 4, static_h - 4)
            st_font  = ImageFont.truetype(font_path, int(size))
        else:
            st_font  = ImageFont.load_default()

        # Ticker-Font
        ticker_size = ticker_h - 4
        tk_font = ImageFont.truetype(font_path, ticker_size) if font_path else ImageFont.load_default()

        # Ticker-Breite messen
        dummy    = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        tk_bb    = dummy.textbbox((0, 0), ticker, font=tk_font)
        ticker_w = tk_bb[2] - tk_bb[0]
        tk_y     = -tk_bb[1] + (ticker_h - (tk_bb[3] - tk_bb[1])) // 2

        # Statisches Bild fuer oberen Bereich einmal rendern
        top_img  = Image.new('RGB', (self._width, static_h), bgcolor)
        top_draw = ImageDraw.Draw(top_img)
        if joined:
            bb = top_draw.multiline_textbbox((0, 0), joined, font=st_font, align='center')
            px = (self._width - (bb[2] - bb[0])) // 2 - bb[0]
            py = (static_h    - (bb[3] - bb[1])) // 2 - bb[1]
            top_draw.multiline_text((px, py), joined, fill=color, font=st_font, align='center')

        fps    = 30
        delay  = 1.0 / fps
        pf     = speed / fps
        start  = time.time()
        offset = 0.0

        while not self._should_stop():
            if duration > 0 and time.time() - start > duration:
                break

            frame = Image.new('RGB', (self._width, self._height), bgcolor)
            frame.paste(top_img, (0, 0))

            # Ticker zeichnen – Text auf breitem Streifen, dann x_pos verschieben
            tk_img = Image.new('RGB', (ticker_w + self._width * 2, ticker_h), bgcolor)
            ImageDraw.Draw(tk_img).text((self._width - tk_bb[0], tk_y), ticker, fill=ticker_color, font=tk_font)
            x_pos  = int(self._width - offset)
            strip  = tk_img.crop((self._width - x_pos, 0, self._width - x_pos + self._width, ticker_h))
            frame.paste(strip, (0, static_h))

            self._matrix.SetImage(frame)
            offset += pf
            if offset >= ticker_w + self._width:
                offset = 0.0
            time.sleep(delay)
