#!/usr/bin/env bash
# Registers a self-hosted GitHub Actions runner on this Raspberry Pi and
# wires up the narrow sudo rule the "Deploy" workflow needs to install new
# code and restart the xtream-filter service.
#
# Run this ON the Raspberry Pi, as a user with sudo rights, AFTER you have
# already run deploy/install.sh at least once (xtream-filter must already
# be installed under /opt/xtream-filter).
#
# Usage:
#   ./setup-runner.sh <repo-url> <registration-token>
#
# Get <repo-url> and <registration-token> from:
#   GitHub repo -> Settings -> Actions -> Runners -> "New self-hosted runner"
#   (choose Linux, then ARM or ARM64 depending on your Pi's OS -- this is
#   about the GitHub Actions runner agent itself, a separate compiled tool
#   from GitHub, unrelated to xtream-filter being plain Python). Copy the
#   --url and --token values from the config.sh command it shows you; the
#   token is only valid for about an hour.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <repo-url> <registration-token>" >&2
  exit 1
fi

REPO_URL="$1"
REG_TOKEN="$2"
RUNNER_USER="github-runner"
RUNNER_HOME="/home/${RUNNER_USER}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d /opt/xtream-filter ]]; then
  echo "/opt/xtream-filter not found. Run deploy/install.sh first." >&2
  exit 1
fi

echo "==> Detecting architecture..."
ARCH="$(uname -m)"
case "$ARCH" in
  armv7l) RUNNER_ARCH="arm" ;;
  aarch64) RUNNER_ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

echo "==> Creating '${RUNNER_USER}' user (if needed)..."
if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  sudo useradd --create-home --shell /bin/bash "$RUNNER_USER"
fi
# Read access to service logs (used by the Deploy workflow on failure),
# without granting sudo for journalctl itself.
sudo usermod -aG systemd-journal "$RUNNER_USER"

echo "==> Fetching latest actions-runner release info..."
LATEST_JSON="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
VERSION="$(echo "$LATEST_JSON" | grep -oP '"tag_name":\s*"v\K[0-9.]+' | head -1)"
if [[ -z "$VERSION" ]]; then
  echo "Could not determine latest actions-runner version." >&2
  exit 1
fi
TARBALL="actions-runner-linux-${RUNNER_ARCH}-${VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${VERSION}/${TARBALL}"

echo "==> Installing actions-runner ${VERSION} (${RUNNER_ARCH}) to ${RUNNER_HOME}/actions-runner..."
sudo -u "$RUNNER_USER" mkdir -p "${RUNNER_HOME}/actions-runner"
curl -fsSL "$DOWNLOAD_URL" -o "/tmp/${TARBALL}"
sudo -u "$RUNNER_USER" tar xzf "/tmp/${TARBALL}" -C "${RUNNER_HOME}/actions-runner"
rm -f "/tmp/${TARBALL}"

echo "==> Configuring the runner (label: raspberry-pi)..."
sudo -u "$RUNNER_USER" bash -c "cd '${RUNNER_HOME}/actions-runner' && ./config.sh --url '${REPO_URL}' --token '${REG_TOKEN}' --unattended --labels raspberry-pi --name '$(hostname)-pi'"

echo "==> Installing the runner as a systemd service..."
(cd "${RUNNER_HOME}/actions-runner" && sudo ./svc.sh install "$RUNNER_USER" && sudo ./svc.sh start)

echo "==> Installing the deploy wrapper script..."
sudo install -o root -g root -m 700 "$REPO_ROOT/deploy/xtream-filter-deploy.sh" /opt/xtream-filter/deploy.sh

echo "==> Installing the narrow sudoers rule..."
SUDOERS_LINE="${RUNNER_USER} ALL=(root) NOPASSWD: /opt/xtream-filter/deploy.sh *"
TMP_SUDOERS="$(mktemp)"
echo "$SUDOERS_LINE" > "$TMP_SUDOERS"
if sudo visudo -c -f "$TMP_SUDOERS" >/dev/null 2>&1; then
  sudo install -o root -g root -m 440 "$TMP_SUDOERS" /etc/sudoers.d/xtream-filter-deploy
  rm -f "$TMP_SUDOERS"
else
  rm -f "$TMP_SUDOERS"
  echo "Generated sudoers rule failed validation, not installed:" >&2
  echo "  $SUDOERS_LINE" >&2
  exit 1
fi

echo
echo "Done. The self-hosted runner is registered and listening for jobs."
echo "Next push/merge to 'main' will trigger .github/workflows/deploy.yml,"
echo "which checks out the repo directly on this Pi and runs deploy.sh to"
echo "install the updated xtream_filter/ package and restart the service."
echo
echo "Check runner status with: sudo ${RUNNER_HOME}/actions-runner/svc.sh status"
