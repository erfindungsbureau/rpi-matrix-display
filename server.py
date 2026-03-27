#!/usr/bin/env python3
"""
LED Matrix Display Server
Empfängt Display-Kommandos via HTTP POST von Node-RED oder anderen Clients.

Endpunkte:
  POST /display     – Text, Bild oder GIF anzeigen
  POST /clear       – Display löschen
  POST /brightness  – Helligkeit setzen (0–100)
  GET  /status      – Aktuellen Status abfragen
"""
import os
import sys
from flask import Flask, request, jsonify

# -----------------------------------------------------------------------
# Konfiguration via Umgebungsvariablen (Defaults für RPi 4 + 64×64 Panel)
# -----------------------------------------------------------------------
ROWS       = int(os.environ.get('MATRIX_ROWS',       64))
COLS       = int(os.environ.get('MATRIX_COLS',       64))
CHAIN      = int(os.environ.get('MATRIX_CHAIN',       1))
PARALLEL   = int(os.environ.get('MATRIX_PARALLEL',    1))
BRIGHTNESS = int(os.environ.get('MATRIX_BRIGHTNESS', 80))
SLOWDOWN   = int(os.environ.get('MATRIX_SLOWDOWN',    4))  # 4 = RPi 4
PORT       = int(os.environ.get('SERVER_PORT',      5050))

app = Flask(__name__)
manager = None   # wird in main() gesetzt


# -----------------------------------------------------------------------
# API
# -----------------------------------------------------------------------

@app.route('/display', methods=['POST'])
def display():
    """
    Universeller Display-Endpunkt.

    Text:
      {"type":"text","text":"Hallo","color":"#FF0000","scroll":true,"speed":40}
      {"type":"text","text":"42°C","color":[0,200,255],"font":"large","duration":10}

    Bild (URL):
      {"type":"image","url":"http://192.168.x.x/bild.png","duration":10}

    Bild (Base64):
      {"type":"image","data":"<base64>","duration":5}

    GIF-Animation:
      {"type":"gif","url":"http://.../anim.gif","loops":3}
      {"type":"gif","url":"http://.../anim.gif","loops":0}  ← endlos

    Parameter 'font':  tiny | small | medium (default) | large | huge
    Parameter 'color': "#RRGGBB" oder [r,g,b]
    Parameter 'duration': Sekunden (0 = dauerhaft bis nächstes Kommando)
    Parameter 'scroll': true/false (nur bei type=text)
    Parameter 'speed':  Pixel/Sekunde beim Scrollen (default: 30)
    Parameter 'x','y':  Position in Pixel (optional, default: zentriert)
    """
    cmd = request.get_json(silent=True)
    if not cmd or 'type' not in cmd:
        return jsonify({'error': 'JSON mit Feld "type" erwartet'}), 400
    manager.send_command(cmd)
    return jsonify({'ok': True, 'type': cmd['type']})


@app.route('/clear', methods=['POST'])
def clear():
    """Display schwärzen."""
    manager.send_command({'type': 'clear'})
    return jsonify({'ok': True})


@app.route('/brightness', methods=['POST'])
def brightness():
    """Helligkeit 0–100 setzen."""
    data = request.get_json(silent=True) or {}
    val  = int(data.get('value', 80))
    manager.set_brightness(val)
    return jsonify({'ok': True, 'brightness': val})


@app.route('/status', methods=['GET'])
def status():
    """Aktuellen Anzeige-Status."""
    return jsonify(manager.get_status())


# -----------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------

def main():
    global manager
    try:
        from rgbmatrix import RGBMatrixOptions
    except ImportError:
        print("ERROR: Paket 'rgbmatrix' nicht gefunden.")
        print("       install.sh ausführen oder manuell installieren.")
        sys.exit(1)

    from display import DisplayManager

    options = RGBMatrixOptions()
    options.rows             = ROWS
    options.cols             = COLS
    options.chain_length     = CHAIN
    options.parallel         = PARALLEL
    options.hardware_mapping = 'regular'   # Adafruit Triple Matrix Bonnet #6358
    options.gpio_slowdown    = SLOWDOWN
    options.brightness       = BRIGHTNESS
    options.drop_privileges  = False       # läuft als root via systemd

    manager = DisplayManager(options)

    print(f"Matrix Display Server gestartet – Port {PORT}")
    print(f"Panel: {ROWS}×{COLS}px, chain={CHAIN}, parallel={PARALLEL}, "
          f"slowdown={SLOWDOWN}, brightness={BRIGHTNESS}%")
    print(f"Endpunkte: POST /display  POST /clear  POST /brightness  GET /status")

    app.run(host='0.0.0.0', port=PORT, threaded=True)


if __name__ == '__main__':
    main()
