#!/bin/bash
# LED Matrix Display Server – Installations-Skript
# Voraussetzung: Raspberry Pi 4, Raspberry Pi OS (Bookworm/Bullseye)
set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HZELLER_DIR="$INSTALL_DIR/rpi-rgb-led-matrix"

echo "=== LED Matrix Display Server – Installation ==="
echo "    Verzeichnis: $INSTALL_DIR"

# System-Pakete
sudo apt-get update -qq
sudo apt-get install -y python3-dev python3-pip python3-pillow git

# rpi-rgb-led-matrix Library klonen und bauen
if [ ! -d "$HZELLER_DIR" ]; then
    echo "[1/4] rpi-rgb-led-matrix klonen..."
    git clone https://github.com/hzeller/rpi-rgb-led-matrix.git "$HZELLER_DIR"
else
    echo "[1/4] rpi-rgb-led-matrix bereits vorhanden"
fi

echo "[2/4] Python-Bindings bauen..."
cd "$HZELLER_DIR"
make build-python PYTHON=$(which python3) -j$(nproc)
sudo make install-python PYTHON=$(which python3)
cd "$INSTALL_DIR"

# Fonts-Symlink
echo "[3/4] Fonts verlinken..."
ln -sfn "$HZELLER_DIR/fonts" "$INSTALL_DIR/fonts"

# Python-Abhängigkeiten
pip3 install --break-system-packages flask requests pillow 2>/dev/null \
    || pip3 install flask requests pillow

# Audio deaktivieren (Timing-Konflikt mit Matrix-Treiber auf RPi)
echo "[4/4] Audio-Modul deaktivieren (verhindert Timing-Konflikte)..."
BLACKLIST="/etc/modprobe.d/raspi-blacklist.conf"
if ! grep -q "snd_bcm2835" "$BLACKLIST" 2>/dev/null; then
    echo "blacklist snd_bcm2835" | sudo tee -a "$BLACKLIST" > /dev/null
    echo "     → snd_bcm2835 deaktiviert (Neustart nötig)"
fi

# Systemd Service installieren (INSTALL_DIR einsetzen)
SERVICE_FILE="/etc/systemd/system/matrix-display.service"
sudo cp "$INSTALL_DIR/matrix-display.service" "$SERVICE_FILE"
sudo sed -i "s|INSTALL_DIR|$INSTALL_DIR|g" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable matrix-display.service

echo ""
echo "=== Installation abgeschlossen ==="
echo ""
echo "  Starten:    sudo systemctl start matrix-display"
echo "  Stoppen:    sudo systemctl stop matrix-display"
echo "  Logs:       sudo journalctl -u matrix-display -f"
echo ""
echo "  Test (Text):"
echo "    curl -X POST http://localhost:5050/display \\"
echo "         -H 'Content-Type: application/json' \\"
echo "         -d '{\"type\":\"text\",\"text\":\"Hello!\",\"color\":\"#00FF00\",\"scroll\":true}'"
echo ""
echo "  Test (Clear):"
echo "    curl -X POST http://localhost:5050/clear"
