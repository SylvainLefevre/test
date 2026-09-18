#!/usr/bin/env bash
# Installed at /opt/xtream-filter/deploy.sh, owned by root, mode 700.
# Invoked via a narrowly scoped sudoers rule (see setup-runner.sh) by the
# CI self-hosted runner user only — never run this manually as root without
# checking the source path first.
#
# xtream-filter is plain Python, so "deploying" is just copying the
# xtream_filter/ package to its install location and restarting the
# service; there is no build/compile step.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <path-to-checked-out-repo>" >&2
  exit 1
fi

SRC_REPO="$1"

if [[ ! -f "$SRC_REPO/xtream_filter/__main__.py" ]]; then
  echo "refusing to deploy: $SRC_REPO/xtream_filter/__main__.py not found" >&2
  exit 1
fi

rm -rf /opt/xtream-filter/xtream_filter
cp -r "$SRC_REPO/xtream_filter" /opt/xtream-filter/xtream_filter
chown -R xtream-filter:xtream-filter /opt/xtream-filter/xtream_filter
systemctl restart xtream-filter
