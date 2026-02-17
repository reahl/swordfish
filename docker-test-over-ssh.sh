#!/bin/bash
set -euo pipefail

SSH_USER="${SF_SSH_USER:-$(whoami)}"
SSH_HOST="${SF_SSH_HOST:-127.0.0.1}"
SSH_PORT="${SF_SSH_PORT:-2222}"
KNOWN_HOSTS_FILE="${SF_SSH_KNOWN_HOSTS_FILE:-/tmp/swordfish_known_hosts}"

REMOTE_PYTEST_ARGS='-q'
if [ "$#" -gt 0 ]; then
    REMOTE_PYTEST_ARGS=''
    for arg in "$@"; do
        printf -v escaped '%q' "$arg"
        REMOTE_PYTEST_ARGS="${REMOTE_PYTEST_ARGS} ${escaped}"
    done
fi

ssh \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -p "$SSH_PORT" \
    "$SSH_USER@$SSH_HOST" \
    "cd /workspace && source ~/.local/venv/bin/activate && if ! python -c 'import reahl' >/dev/null 2>&1; then pip install -e .; fi && pytest ${REMOTE_PYTEST_ARGS}"
