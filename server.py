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
import json
from flask import Flask, request, jsonify

# -----------------------------------------------------------------------
# Konfiguration aus config.json laden
# -----------------------------------------------------------------------
_cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

ROWS         = _cfg['panel']['rows']
COLS         = _cfg['panel']['cols']
CHAIN        = _cfg['panel']['chain']
PARALLEL     = _cfg['panel']['parallel']
PIXEL_MAPPER = _cfg['panel'].get('pixel_mapper', '')
BRIGHTNESS   = _cfg['hardware']['brightness']
SLOWDOWN     = _cfg['hardware']['gpio_slowdown']
PORT         = _cfg['server']['port']

# Berechnete Gesamtauflösung
TOTAL_WIDTH  = COLS * CHAIN
TOTAL_HEIGHT = ROWS * PARALLEL

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
    Parameter 'size':   Schriftgrösse in Pixel (nur statischer Text, default: automatisch)

    Statischer Text (scroll=false oder weggelassen) wird automatisch so
    skaliert dass er das gesamte Display ausfüllt, ausser 'size' ist gesetzt.
    Zeilenumbrüche: \n im text-Feld, z.B. "Zeile1\nZeile2".

    Animation (GET /animations für alle verfügbaren Namen):
      {"type":"animation","name":"rainbow"}
      {"type":"animation","name":"fire","duration":30}
      {"type":"animation","name":"clock"}
      {"type":"animation","name":"plasma"}
      {"type":"animation","name":"matrix_rain","duration":60}
      {"type":"animation","name":"starfield"}
      {"type":"animation","name":"bouncing_ball"}
      {"type":"animation","name":"color_pulse"}
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


@app.route('/animations', methods=['GET'])
def list_animations():
    """Alle verfügbaren eingebauten Animationen auflisten."""
    from animations import ANIMATIONS
    return jsonify({'animations': list(ANIMATIONS.keys())})


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
    options.hardware_mapping    = 'regular'   # Adafruit Triple Matrix Bonnet #6358
    options.gpio_slowdown       = SLOWDOWN
    options.brightness          = BRIGHTNESS
    options.pixel_mapper_config = PIXEL_MAPPER
    options.drop_privileges     = False       # läuft als root via systemd

    manager = DisplayManager(options)

    print(f"Matrix Display Server gestartet – Port {PORT}")
    print(f"Panels: {ROWS}×{COLS}px, chain={CHAIN}, parallel={PARALLEL}")
    print(f"Gesamtauflösung: {TOTAL_WIDTH}×{TOTAL_HEIGHT}px")
    print(f"Hardware: slowdown={SLOWDOWN}, brightness={BRIGHTNESS}%")
    print(f"Endpunkte: POST /display  POST /clear  POST /brightness  GET /status")

    app.run(host='0.0.0.0', port=PORT, threaded=True)


if __name__ == '__main__':
    main()
