#!/usr/bin/env bash
# Installs xtream-filter as a systemd service on a Raspberry Pi (or any
# Debian/Ubuntu-based, systemd-based Linux). Run this ON the Pi, as a user
# with sudo rights, from the root of this repository.
#
# Uses only apt packages (python3 + python3-yaml) plus the Python standard
# library: no compiler, no pip, no virtualenv needed.
set -euo pipefail

INSTALL_DIR="/opt/xtream-filter"
SERVICE_USER="xtream-filter"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing system dependencies (python3, python3-yaml)..."
sudo apt-get update
sudo apt-get install -y python3 python3-yaml

echo "==> Creating system user '$SERVICE_USER' (if needed)..."
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> Installing application code to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo rm -rf "$INSTALL_DIR/xtream_filter"
sudo cp -r "$REPO_ROOT/xtream_filter" "$INSTALL_DIR/xtream_filter"

if [[ ! -f "$INSTALL_DIR/config.yaml" ]]; then
  echo "==> No existing config.yaml, installing config.example.yaml as a starting point."
  sudo cp "$REPO_ROOT/config.example.yaml" "$INSTALL_DIR/config.yaml"
  echo "    EDIT $INSTALL_DIR/config.yaml before starting the service (source credentials, filters)."
else
  echo "==> Existing config.yaml found, leaving it untouched."
fi

sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> Installing systemd unit..."
sudo cp "$REPO_ROOT/deploy/xtream-filter.service" /etc/systemd/system/xtream-filter.service
sudo systemctl daemon-reload
sudo systemctl enable xtream-filter

echo
echo "Done. Next steps:"
echo "  1. sudo nano $INSTALL_DIR/config.yaml   # set your source credentials and filters"
echo "  2. sudo systemctl start xtream-filter"
echo "  3. journalctl -u xtream-filter -f       # watch logs"
echo "  4. curl http://localhost:8081/healthz"
