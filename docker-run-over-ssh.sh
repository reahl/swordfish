#!/bin/bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "Usage: $0 <command> [args...]"
    exit 1
fi

SSH_USER="${SF_SSH_USER:-$(whoami)}"
SSH_HOST="${SF_SSH_HOST:-127.0.0.1}"
SSH_PORT="${SF_SSH_PORT:-2222}"
KNOWN_HOSTS_FILE="${SF_SSH_KNOWN_HOSTS_FILE:-/tmp/swordfish_known_hosts}"
WORKSPACE_DIR="${SF_SSH_WORKSPACE_DIR:-/workspace}"

REMOTE_COMMAND=''
for arg in "$@"; do
    printf -v escaped '%q' "$arg"
    REMOTE_COMMAND="${REMOTE_COMMAND} ${escaped}"
done

ssh \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -p "$SSH_PORT" \
    "$SSH_USER@$SSH_HOST" \
    "cd ${WORKSPACE_DIR} && source ~/.profile && source ~/.local/venv/bin/activate &&${REMOTE_COMMAND}"
