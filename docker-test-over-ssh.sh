#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -eq 0 ]; then
    "$SCRIPT_DIR/docker-run-over-ssh.sh" pytest -q
else
    "$SCRIPT_DIR/docker-run-over-ssh.sh" pytest "$@"
fi
